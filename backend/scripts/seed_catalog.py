"""On-demand catalog seed: pull TCGdex card IDENTITY into DynamoDB.

This is the "breadth" pass and only the breadth pass. TCGdex returns a whole
language's catalog from one list request, but that response carries identity
only — ``{id, localId, name, image?}`` — because **pricing exists solely on the
per-card detail endpoint**. Pricing every card would be ~23,000 extra requests
per language to produce figures for cards the business does not own and no
surface can render, so prices are acquired separately, for held cards only
(RFC 0003 §0 and §2).

What that means in practice: after this script the matcher can resolve any row
on the sheet in either language, and every card is stored with no price. The
depth pass that hydrates full metadata + prices for held cards, and the
generation load-then-swap that makes a reseed atomic, land in Phase 2.

**This is a production writer aimed at a live customer-facing table, so it has
rails** (revision-1 verdict, FRAIL-2/3/4):

- it is a **dry run by default**; writing requires ``--execute`` AND naming the
  target table back via ``--confirm-table``;
- it **never overwrites a ``detail="full"`` row**. Once the Phase-2 depth pass
  has run, an unguarded re-run of this weekly seed would ``put_item`` every
  price away and revert those rows to ``brief`` — whole-item writes do not
  merge — and recovery would be a full depth re-run;
- it **aborts non-zero** on a wholesale mapping failure or a catalog that comes
  back implausibly short, instead of reporting a successful no-op;
- writes are paced, because the 0.1 s politeness budget in ``TcgdexClient`` is
  aimed at the party that is NOT under load.

Run from ``backend/`` with the project venv active:

    python scripts/seed_catalog.py                                  # dry run
    python scripts/seed_catalog.py --execute --confirm-table merlins-cards
    python scripts/seed_catalog.py --language ja --execute --confirm-table ...
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone

from merlins_collection.config import settings
from merlins_collection.models.inventory import Language
from merlins_collection.services.dynamodb import InventoryRepository
from merlins_collection.services.tcgdex import (
    LANGUAGE_API_CODE,
    TcgdexClient,
    to_catalog_card_brief,
)

BATCH_SIZE = 500

# Abort if more than this fraction of rows fail to map. One upstream casing
# change can make every single card raise; without this the run returns
# `{"cards_seeded": 0, "failures": 23444}` with exit code 0 and the catalog
# quietly stays stale for a week.
MAX_FAILURE_RATIO = 0.1

# Abort if the seed lands below this fraction of the card count the set list
# itself advertises. This is the magnitude rail against a silently truncated
# walk: `list_sets` already reports how many cards each set holds and the seed
# used to fetch that and throw it away.
MIN_EXPECTED_RATIO = 0.9

# Pause between write batches. boto3 otherwise bursts ~23k rows into a table
# that is concurrently serving `/inventory`.
WRITE_PACING_SECONDS = 0.2


class SeedAborted(RuntimeError):
    """A rail fired: the run is wrong in a way that must not exit 0."""


def _set_metadata(client, language):
    """Return ``(set_names, expected_cards)``; degrade rather than abort.

    Matching keys on name + number + language and treats the set only as a
    corroborating signal, so an unavailable set list costs display quality and
    the magnitude cross-check, but not the seed itself.
    """
    try:
        sets = client.list_sets(language)
    except Exception as exc:  # noqa: BLE001 - breadth must not hinge on set names
        print(f"  set list unavailable ({exc}); seeding without set names")
        return {}, None

    set_names = {s["id"]: s.get("name", "") for s in sets}
    counts = [
        (s.get("cardCount") or {}).get("total")
        for s in sets
        if isinstance((s.get("cardCount") or {}).get("total"), int)
    ]
    return set_names, (sum(counts) if counts else None)


def seed_language(repo, client, language: Language, *, batch_size: int = BATCH_SIZE,
                  execute: bool = False, max_failure_ratio: float = MAX_FAILURE_RATIO,
                  min_expected_ratio: float = MIN_EXPECTED_RATIO,
                  allow_unverified: bool = False) -> dict:
    """Upsert every card of one language as a brief catalog row.

    Returns a summary counting what was mapped (``cards_seeded``), actually
    written (``cards_written``), skipped because a priced row already existed
    (``cards_preserved``) and failed to map (``failures``).

    A run that cannot corroborate its own size against ``list_sets`` raises
    unless ``allow_unverified`` is set: an unverifiable run is not a passing
    run. See the ``SeedAborted`` at the bottom of this function.
    """
    set_names, expected = _set_metadata(client, language)

    synced_at = datetime.now(timezone.utc)
    cards: list = []
    seeded = 0
    written = 0
    preserved = 0
    failures = 0

    def flush():
        """Write the buffer, preserving any row a depth pass has already priced.

        KNOWN, DELIBERATELY DEFERRED (Council rev-2 verdict, Chaos S2 — ruled a
        **Phase 2 precondition**, not a Phase 1 gate): the read → decide → write
        below is check-then-act with no ``ConditionExpression`` and no lock, so
        a depth pass interleaving between the ``batch_get`` and the
        ``batch_upsert`` can have its ``detail="full"`` row overwritten by the
        unconditional ``put_item``. Phase 1 ships no depth pass, so nothing can
        construct the interleaving today. **Phase 2 must add the
        ``ConditionExpression`` (or take ``acquire_import_lock``) before the
        depth pass and the live wipe ship** — do not let this drop between
        phases.
        """
        nonlocal cards, written, preserved
        if not cards:
            return
        existing = repo.batch_get_catalog_cards([c.card_id for c in cards])
        keep = [
            c for c in cards
            if getattr(existing.get(c.card_id), "detail", None) != "full"
        ]
        preserved += len(cards) - len(keep)
        if execute and keep:
            repo.batch_upsert_catalog_cards(keep)
            written += len(keep)
            if WRITE_PACING_SECONDS:
                time.sleep(WRITE_PACING_SECONDS)
        cards = []
        print(f"  mapped {seeded}, written {written}, preserved {preserved}")

    try:
        for raw in client.iter_brief_cards(language):
            try:
                cards.append(to_catalog_card_brief(raw, language, set_names=set_names,
                                                   synced_at=synced_at))
            except Exception as exc:  # noqa: BLE001 - one bad row must not abort
                failures += 1
                # Logged with the id and exception type rather than swallowed
                # into an integer: a systematic upstream change and a quiet day
                # must not look the same.
                print(f"  skipped {raw.get('id')!r}: {type(exc).__name__}: {exc}")
                continue
            seeded += 1
            if len(cards) >= batch_size:
                flush()
    finally:
        # FRAIL-3: an exception raised by the generator in the `for` header is
        # not caught by the per-row guard above. Without this, up to
        # `batch_size - 1` successfully mapped cards are discarded, no summary
        # prints, and the operator gets a traceback instead of "seeded 11,500 of
        # ~23,444" — so they cannot tell how far it got or where to resume.
        flush()

    summary = {
        "language": language.value, "cards_seeded": seeded,
        "cards_written": written, "cards_preserved": preserved,
        "failures": failures, "cards_expected": expected,
    }

    attempted = seeded + failures
    if attempted and failures / attempted > max_failure_ratio:
        raise SeedAborted(
            f"{failures} of {attempted} rows failed to map "
            f"({failures / attempted:.0%} > {max_failure_ratio:.0%}); "
            f"aborting rather than reporting a successful no-op: {summary}"
        )
    if expected and seeded < expected * min_expected_ratio:
        raise SeedAborted(
            f"catalog came back short: seeded {seeded} of the {expected} cards "
            f"the set list advertises; a truncated walk must not look like a "
            f"successful run: {summary}"
        )
    if not expected and not allow_unverified:
        # LOGIC-1. Without an expected count the magnitude rail above is not
        # leaky, it is DISARMED — `if expected and ...` is a no-op when
        # `expected` is falsy. A struggling free API degrades `/sets` and
        # `/cards` together, which is exactly when a truncated walk is most
        # likely and least detectable, so the one run that most needs the rail
        # is the one that silently loses it. Refuse instead: the operator can
        # re-run when the API is healthy, or force it with --allow-unverified.
        raise SeedAborted(
            f"catalog size could not be verified: the set list gave no card "
            f"counts to cross-check {seeded} seeded rows against, so a "
            f"truncated walk would be indistinguishable from a complete one. "
            f"Re-run when the set list is available, or pass "
            f"--allow-unverified to accept an unchecked catalog: {summary}"
        )
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", action="append", choices=sorted(LANGUAGE_API_CODE.values()),
                        help="API language code to seed (repeatable); default: all")
    parser.add_argument("--execute", action="store_true",
                        help="actually write; without it this is a dry run")
    parser.add_argument("--confirm-table",
                        help="the table name you intend to write to; must match "
                             "the configured target when --execute is given")
    parser.add_argument("--allow-unverified", action="store_true",
                        help="accept a catalog whose size could not be "
                             "cross-checked against the set list (the run "
                             "aborts without this)")
    args = parser.parse_args(argv)
    languages = ([lang for lang in Language if LANGUAGE_API_CODE[lang] in args.language]
                 if args.language else list(Language))

    table, region = settings.dynamodb_table_name, settings.aws_region
    mode = "WRITING to" if args.execute else "DRY RUN against"
    print(f"Seeding TCGdex catalog identity — {mode} DynamoDB table '{table}' ({region})...")

    if args.execute and args.confirm_table != table:
        print(
            f"refusing to write: --confirm-table={args.confirm_table!r} does not "
            f"match the configured target {table!r}. This table serves "
            f"/inventory; name it explicitly to write to it.",
            file=sys.stderr,
        )
        return 2

    repo = InventoryRepository(table, region_name=region)
    with TcgdexClient() as client:
        for language in languages:
            print(f"{language.label}:")
            try:
                summary = seed_language(repo, client, language,
                                        execute=args.execute,
                                        allow_unverified=args.allow_unverified)
                print(f"  {summary}")
            except SeedAborted as exc:
                print(f"  ABORTED: {exc}", file=sys.stderr)
                return 1
    if not args.execute:
        print("\nDry run: nothing was written. Re-run with "
              f"--execute --confirm-table {table}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
