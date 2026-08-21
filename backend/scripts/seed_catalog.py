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
  back implausibly short, instead of reporting a successful no-op. "Implausibly
  short" is measured PER LANGUAGE (``MIN_EXPECTED_RATIO_BY_LANGUAGE``): TCGdex
  is ~98.7% complete in English and ~50% in Japanese, so one flat floor would
  have to be either too loose to catch an English regression or so tight it
  rejects a correct Japanese seed;
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
#
# The floor is PER LANGUAGE because "complete" means something different per
# language upstream, and one flat number cannot be both a real check for
# English and a survivable one for Japanese. It is the fallback for a language
# with no entry in the table below.
MIN_EXPECTED_RATIO = 0.9

# THIS IS NOT A WEAKENED RAIL — it is the same rail calibrated to what each
# language's upstream actually contains. Measured live against TCGdex on
# 2026-07-28 (see claude-progress.txt LOG 2026-07-28 "LIVE WIPE ATTEMPT",
# FOLLOW-UP):
#
#   EN  23,444 of 23,746 advertised (98.7%) — only 25 of 218 sets missing, all
#       niche promo products. A normal long tail; 0.9 is a real check here and
#       stays untouched.
#   JA   8,159 of 16,192 advertised (50.4%) — 108 of TCGdex's 177 JA sets carry
#       set metadata (name, official card count) but ZERO card-level rows, even
#       when queried individually at `GET /v2/ja/sets/<id>`. Spanning 2003-2024
#       and including mainline releases, so this is not a long tail: nobody has
#       entered those cards into TCGdex's community database yet. Confirmed
#       reproducible across repeated raw fetches — not an outage, not our
#       pagination, and it will not resolve by retrying later. TCGdex's own
#       status page treats per-language completeness as an accepted, varying
#       steady state rather than a tracked defect.
#
# 0.4 for JA is ~10 points of margin under the measured 50.4%, so ordinary
# set-count drift does not false-positive, while a genuine regression — TCGdex
# losing more data, or our own walk truncating — still trips it. If JA's real
# ratio climbs as the community fills sets in, RAISE this to sit just under the
# new figure. Lowering it further needs the same treatment this entry got:
# measure upstream first, then move the number, and say so here. The owner
# accepted TCGdex's current Japanese completeness as normal on 2026-07-28,
# because a half-populated JP catalog is what exists and beats no JP at all.
MIN_EXPECTED_RATIO_BY_LANGUAGE = {
    Language.EN: 0.9,
    Language.JP: 0.4,
}

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
                  min_expected_ratio: float | None = None,
                  allow_unverified: bool = False, id_sink: set | None = None) -> dict:
    """Upsert every card of one language as a brief catalog row.

    Returns a summary counting what was mapped (``cards_seeded``), actually
    written (``cards_written``), skipped because a priced row already existed
    (``cards_preserved``) and failed to map (``failures``).

    A run that cannot corroborate its own size against ``list_sets`` raises
    unless ``allow_unverified`` is set: an unverifiable run is not a passing
    run. See the ``SeedAborted`` at the bottom of this function.

    ``min_expected_ratio`` defaults to ``None``, meaning "use this language's
    floor" from ``MIN_EXPECTED_RATIO_BY_LANGUAGE``. Resolving it here rather
    than in the signature is what lets every caller — ``main`` below and
    ``wipe_catalog.wipe_and_reseed`` — get the right floor per language without
    either of them knowing the table exists. Passing a number still overrides
    it outright.

    ``id_sink``, when given, collects every card id this run mapped. The wipe's
    DRY RUN needs it to predict honestly: a dry run writes nothing, so without
    the ids it would report the whole catalog as "would be deleted" instead of
    just the rows the reseed does not replace. It is deliberately NOT returned in
    the summary, which gets printed.
    """
    if min_expected_ratio is None:
        min_expected_ratio = MIN_EXPECTED_RATIO_BY_LANGUAGE.get(language,
                                                                MIN_EXPECTED_RATIO)
    set_names, expected = _set_metadata(client, language)

    synced_at = datetime.now(timezone.utc)
    cards: list = []
    seeded = 0
    written = 0
    preserved = 0
    failures = 0

    def flush():
        """Write the buffer, preserving any row a depth pass has already priced.

        CLOSED IN PHASE 2.0a (was Council rev-2 / Chaos S2). This used to
        ``batch_get`` the ids, filter out the ``detail="full"`` rows and then
        ``batch_upsert`` the rest — check-then-act, with a window between the
        read and the write in which a depth pass could land a priced row and
        have it silently overwritten by a ``brief`` one. The decision now lives
        in a ``ConditionExpression`` inside ``batch_upsert_catalog_cards``, so
        DynamoDB evaluates it in the same operation as the write and no
        interleaving exists to lose. There is deliberately no pre-read here.
        """
        nonlocal cards, written, preserved
        if not cards:
            return
        if id_sink is not None:
            id_sink.update(c.card_id for c in cards)
        if execute:
            skipped = repo.batch_upsert_catalog_cards(cards, preserve_priced=True)
            preserved += skipped
            written += len(cards) - skipped
            if WRITE_PACING_SECONDS:
                time.sleep(WRITE_PACING_SECONDS)
        else:
            # A dry run has to predict `cards_preserved` too, or it reports 0 for
            # a run that would in fact skip thousands of priced rows. This read is
            # safe precisely because it writes nothing — the race the condition
            # closes needs a write to be a race.
            existing = repo.batch_get_catalog_cards([c.card_id for c in cards])
            preserved += sum(
                getattr(existing.get(c.card_id), "detail", None) == "full"
                for c in cards
            )
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
            f"the set list advertises ({seeded / expected:.1%}), below the "
            f"{min_expected_ratio:.0%} floor for {language.value}; a truncated "
            f"walk must not look like a successful run: {summary}"
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
