"""One-time script: remove catalog junk. RFC 0021.

Two junk cohorts, and they are NOT interchangeable:

- **Digital-only** — TCG Pocket (series ``tcgp``) rows, ingested before RFC
  0021's exclusion existed. Identified via the SAME
  ``services.catalog_sync.excluded_set_ids`` authority the ingest filter now
  uses — one code path, two callers.
- **Legacy** — dead pokemontcg.io-era rows with no ``<api_lang>:`` prefix at
  all (``"xy7-54"``). ``parse_card_id`` already names this cohort in its own
  docstring.

A THIRD bucket exists and is **never deleted**: a ``card_id`` with a ``:`` but
an UNKNOWN language prefix. ``parse_card_id`` returns ``None`` for this too,
but purging it would be a data-destroying false positive the moment RFC 0023
adds 16 more language codes — or against any hand-seeded row today. It is
reported, grouped by language code, and left alone.

**IN-USE GUARD.** A catalog row an inventory item points at is never deleted,
regardless of cohort: ``card_id`` is the join key for pricing, images and
identity, and removing it would silently unprice an owned card and strand it
with a dangling reference. Skipped candidates are reported under
``in_use_skipped`` with their item ids, for manual triage.

**Rails, matching ``scripts/seed_catalog.py``** (the closest sibling — a
destructive full-table walk, not the additive ``backfill_catalog_sets.py``
rail): dry run by default; ``--execute --confirm-table <table>`` to write.

**Chunked progress is mandatory, not a nicety.** CLAUDE.md records a
90-minute silent script that was indistinguishable from a hang. This walks
31,603+ catalog rows and their price children.

**The whole ``CARD#<card_id>`` partition is deleted, not just the identity
row** — ``PRICE#RAW#…``/``PRICE#GRADED#…``/``GRADEDPRICE#…`` children go with
it, or they orphan into rows nothing can ever read again.

**A ``catalog_set`` registry row is deregistered ONLY when every one of its
cards was actually deleted.** If the in-use guard held even one card back,
the set still has catalog rows, and deregistering it would make it invisible
to the Set filter while it still matches search — reported under
``sets_kept_partial`` instead.

**Cache invalidation is NOT this script's job.**
``services.catalog_cache`` is process-local to the running Lambda; this is a
separate process. The script prints a one-line reminder; it does not add a
cache-busting endpoint for a one-time run.

Run from ``backend/`` with the project venv active:

    python scripts/purge_catalog_junk.py                                   # DRY RUN
    python scripts/purge_catalog_junk.py --execute --confirm-table merlins-cards
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import defaultdict

from merlins_collection.config import settings
from merlins_collection.models.inventory import SEEDED_LANGUAGES
from merlins_collection.services.catalog_sync import excluded_set_ids
from merlins_collection.services.dynamodb import InventoryRepository
from merlins_collection.services.tcgdex import TcgdexClient, parse_card_id

# How often to print a scan-progress line, in cards examined. CLAUDE.md: a
# script silent for 90 minutes against ~70,000 rows was indistinguishable
# from a hang. This catalog is 31,603+ rows, so progress every 2,000 keeps a
# line appearing at least every few seconds against a live table.
SCAN_CHUNK_SIZE = 2000

# Same reasoning for the delete phase, sized smaller because a delete
# (partition query + batch_writer) costs more per row than a classify read.
DELETE_CHUNK_SIZE = 200

SAMPLE_SIZE = 10


def _repository(table: str, region: str):
    """The live repository; patched out in tests so nothing touches real AWS."""
    return InventoryRepository(table, region_name=region)


def _held_card_ids(repo) -> dict[str, list[str]]:
    """``card_id -> [item_id, ...]`` for every inventory item pointing at a
    catalog card. One full walk, held in memory — inventory is thousands of
    rows, not millions, unlike the catalog this function guards.
    """
    held: dict[str, list[str]] = defaultdict(list)
    for item in repo.list_inventory():
        card_id = getattr(item, "card_id", None)
        if card_id:
            held[card_id].append(item.item_id)
    return held


def classify_catalog(repo, client, *, progress=None) -> dict:
    """One READ-ONLY walk of the catalog, sorting every row into a cohort.

    Nothing is written here regardless of what the caller does with the
    result — dry run and execute both start from the identical plan.

    The three cohorts, per the RFC:

        no ":" separator at all            -> LEGACY, purgeable
        ":" present, language unknown      -> REPORTED, never purged
        ":" present, set is excluded       -> DIGITAL, purgeable

    A candidate held by an inventory item is diverted into ``in_use``
    regardless of cohort, and never appears in ``digital``/``legacy``.
    """
    progress = progress or (lambda *a, **k: None)
    # SEEDED_LANGUAGES, not the full `Language` enum -- RFC 0023 grew it to 19
    # members and this script only ever needs exclusion sets for languages the
    # catalog actually holds rows in; walking the rest is 16+ wasted live
    # TCGdex calls per run for no candidate they could ever match.
    excluded_by_language = {
        language: excluded_set_ids(client, language) for language in SEEDED_LANGUAGES
    }
    held = _held_card_ids(repo)

    digital: list = []
    legacy: list = []
    unknown_language: dict[str, list[str]] = defaultdict(list)
    in_use: dict[str, list[str]] = {}
    # Per-(composite)-set bookkeeping for the registry deregistration decision.
    # Only DIGITAL cards populate this — a legacy card's `set_id` predates the
    # composite scheme and was never in the `catalog_set` registry to begin
    # with, so there is nothing there to deregister.
    digital_set_totals: dict[str, int] = defaultdict(int)
    digital_set_in_use: dict[str, int] = defaultdict(int)

    scanned = 0
    started = time.monotonic()
    for card in repo.iter_catalog_cards():
        scanned += 1
        card_id = card.card_id
        parsed = parse_card_id(card_id)
        if ":" not in card_id:
            cohort = "legacy"
        elif parsed is None:
            cohort = "unknown_language"
        else:
            language, _tcgdex_id = parsed
            set_parsed = parse_card_id(card.set_id)
            raw_set_id = set_parsed[1] if set_parsed else None
            is_digital = (raw_set_id is not None and
                         raw_set_id in excluded_by_language.get(language, frozenset()))
            cohort = "digital" if is_digital else None

        if cohort == "unknown_language":
            unknown_language[card_id.split(":", 1)[0]].append(card_id)
        elif cohort == "digital":
            digital_set_totals[card.set_id] += 1
            if card_id in held:
                digital_set_in_use[card.set_id] += 1
                in_use[card_id] = held[card_id]
            else:
                digital.append(card)
        elif cohort == "legacy":
            if card_id in held:
                in_use[card_id] = held[card_id]
            else:
                legacy.append(card)
        # cohort is None: a normal, physical, catalogued card. Not counted.

        if scanned % SCAN_CHUNK_SIZE == 0:
            elapsed = time.monotonic() - started
            progress(
                f"  scan: {scanned:,} examined ({elapsed:.0f}s) — "
                f"{len(digital)} digital, {len(legacy)} legacy, "
                f"{sum(len(v) for v in unknown_language.values())} unknown-language, "
                f"{len(in_use)} in-use so far"
            )

    elapsed = time.monotonic() - started
    progress(f"  scan complete: {scanned:,} cards examined in {elapsed:.0f}s")

    sets_kept_partial = sorted(
        set_id for set_id, count in digital_set_in_use.items() if count > 0
    )
    sets_fully_purged = sorted(
        set_id for set_id in digital_set_totals if digital_set_in_use.get(set_id, 0) == 0
    )

    return {
        "scanned": scanned,
        "digital": digital,
        "legacy": legacy,
        "unknown_language": dict(unknown_language),
        "in_use": in_use,
        "sets_kept_partial": sets_kept_partial,
        "sets_fully_purged": sets_fully_purged,
    }


def _delete_candidates(repo, cards, *, progress=None) -> tuple[int, int]:
    """Delete each card's whole partition. Returns ``(cards_deleted, child_rows_deleted)``."""
    progress = progress or (lambda *a, **k: None)
    total = len(cards)
    cards_deleted = 0
    child_rows_deleted = 0
    for index, card in enumerate(cards, start=1):
        rows = repo.delete_catalog_card_partition(card.card_id)
        if rows:
            cards_deleted += 1
            child_rows_deleted += rows - 1  # META counted separately from children
        if index % DELETE_CHUNK_SIZE == 0 or index == total:
            progress(f"  delete: {index:,}/{total:,} candidates processed "
                     f"({cards_deleted} deleted so far)")
    return cards_deleted, child_rows_deleted


def purge_catalog_junk(repo, client, *, execute: bool = False, progress=None) -> dict:
    """Classify the catalog and, if ``execute``, delete what it found.

    Returns the full result: JSON-safe summary counts (the keys the RFC's
    summary schema names) plus underscore-prefixed raw lists for sampling —
    the CLI prints sample rows from them and tests assert against them
    directly. ``digital_candidates``/``legacy_candidates`` are always the
    PREDICTED counts (populated on a dry run too, mirroring
    ``seed_catalog.py``'s ``cards_seeded`` vs ``cards_written`` split);
    ``cards_deleted``/``child_rows_deleted``/``sets_deregistered`` are the
    ACTUAL counts and stay zero unless ``execute`` is set.
    """
    progress = progress or (lambda *a, **k: None)
    plan = classify_catalog(repo, client, progress=progress)

    candidates = plan["digital"] + plan["legacy"]
    cards_deleted = child_rows_deleted = sets_deregistered = 0
    if execute:
        cards_deleted, child_rows_deleted = _delete_candidates(
            repo, candidates, progress=progress
        )
        if plan["sets_fully_purged"]:
            sets_deregistered = repo.delete_catalog_sets(plan["sets_fully_purged"])

    return {
        "dry_run": not execute,
        "scanned": plan["scanned"],
        "digital_candidates": len(plan["digital"]),
        "legacy_candidates": len(plan["legacy"]),
        "unknown_language_reported": sum(len(v) for v in plan["unknown_language"].values()),
        "in_use_skipped": len(plan["in_use"]),
        "cards_deleted": cards_deleted,
        "child_rows_deleted": child_rows_deleted,
        "sets_deregistered": sets_deregistered,
        "sets_kept_partial": plan["sets_kept_partial"],
        # Underscore-prefixed: not part of the printed summary line, but the
        # sample-row report (and tests) need the raw objects/ids.
        "_digital_cards": plan["digital"],
        "_legacy_cards": plan["legacy"],
        "_unknown_language": plan["unknown_language"],
        "_in_use": plan["in_use"],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--table", default=settings.dynamodb_table_name,
                        help="DynamoDB table to read/write (default: %(default)s)")
    parser.add_argument("--region", default=settings.aws_region,
                        help="AWS region (default: %(default)s)")
    parser.add_argument("--execute", action="store_true",
                        help="actually delete. WITHOUT THIS FLAG NOTHING IS DELETED.")
    parser.add_argument("--confirm-table",
                        help="the table name you intend to write to; must match "
                             "--table when --execute is given")
    return parser


def _sample(cards, n=SAMPLE_SIZE):
    return [{"card_id": c.card_id, "name": c.name, "set_name": c.set_name}
            for c in cards[:n]]


def main(argv=None) -> int:
    args = _parser().parse_args(argv)

    if args.execute and args.confirm_table != args.table:
        print(f"refusing to delete: --confirm-table={args.confirm_table!r} does "
              f"not match --table {args.table!r}. This table serves /inventory; "
              f"name it explicitly to write to it.", file=sys.stderr)
        return 2

    repo = _repository(args.table, args.region)
    mode = "EXECUTE" if args.execute else "DRY RUN"
    print(f"Purging catalog junk — {mode} against DynamoDB table "
          f"{args.table!r} ({args.region})...")

    with TcgdexClient() as client:
        result = purge_catalog_junk(repo, client, execute=args.execute, progress=print)

    summary = {k: v for k, v in result.items() if not k.startswith("_")}
    print(f"\n{summary}")

    for label, key in (("digital", "_digital_cards"), ("legacy", "_legacy_cards")):
        cards = result[key]
        if cards:
            print(f"\n{label} sample (up to {SAMPLE_SIZE} of {len(cards)}):")
            for row in _sample(cards):
                print(f"  {row}")

    if result["_unknown_language"]:
        print("\nunknown-language rows (reported, never purged):")
        for code, ids in sorted(result["_unknown_language"].items()):
            print(f"  {code}: {len(ids)} rows, e.g. {ids[:SAMPLE_SIZE]}")

    if result["_in_use"]:
        print("\nin-use candidates skipped (manual triage needed):")
        for card_id, item_ids in result["_in_use"].items():
            print(f"  {card_id}: held by {item_ids}")

    if not args.execute:
        print(f"\nDry run: nothing was deleted. Re-run with "
              f"--execute --confirm-table {args.table}")
    else:
        print("\nReminder: the running Lambda's in-process catalog cache still "
              "holds the deleted rows until its TTL expires.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
