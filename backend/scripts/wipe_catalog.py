"""Phase 2: replace the card data in DynamoDB with a fresh TCGdex catalog.

This is the ONE destructive script in the tree. It removes the dead
pokemontcg.io-era catalog, every price derived from it, and the holdings the old
spreadsheet import wrote — and it leaves the business master data alone
(shows, consignors, config, auth, rate-limit counters).

**Load, then swap.** The order is the whole design. The fresh catalog is written
first, stamped with a new catalog generation; only once it has fully landed does
``purge_card_data`` delete everything that is not of that generation. The table
therefore goes from "old catalog" straight to "new catalog" — it is never
half-empty while ``/inventory`` is being served — and any failure before the
swap leaves the old world intact and merely wastes the load.

**Rails**, copied from ``seed_catalog.py`` rather than reinvented:

- **dry run by default**; deleting requires ``--execute`` AND naming the target
  table back via ``--confirm-table``. A dry run loads nothing and deletes
  nothing; it reports what would go.
- the **single-flight import lock**, so a spreadsheet import and this cannot
  interleave, and so two operators cannot both run it.
- it **refuses to swap** if the load aborted, raised, or produced an empty
  catalog. Deleting the old catalog because the new one never arrived is the
  one outcome this script must not be able to produce.

``daily_sync.py`` carries none of this because it is additive-only. That
exemption does not transfer here.

Run from ``backend/`` with the project venv active:

    python scripts/wipe_catalog.py                                  # dry run
    python scripts/wipe_catalog.py --execute --confirm-table merlins-cards
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

from merlins_collection.config import settings
from merlins_collection.models.inventory import Language, new_ulid
from merlins_collection.services.dynamodb import (
    ImportInProgressError,
    InventoryRepository,
)
from merlins_collection.services.tcgdex import LANGUAGE_API_CODE, TcgdexClient


def _load_seed():
    """Import ``seed_catalog.py`` off disk — ``scripts/`` is not a package.

    The reseed is deliberately NOT reimplemented here: ``seed_language`` already
    carries the failure-ratio and magnitude rails, and a second copy of that
    logic would be a second thing to keep correct.
    """
    path = Path(__file__).resolve().parent / "seed_catalog.py"
    spec = importlib.util.spec_from_file_location("seed_catalog", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("seed_catalog", module)
    spec.loader.exec_module(module)
    return module


seed_catalog = _load_seed()


def _repository():
    """The live repository; patched out in tests so nothing touches real AWS."""
    return InventoryRepository(settings.dynamodb_table_name,
                               region_name=settings.aws_region)


def _client():
    """The live TCGdex client; patched out in tests."""
    return TcgdexClient()


def wipe_and_reseed(repo, client, languages, *, execute: bool = False,
                    allow_unverified: bool = False) -> dict:
    """Load a fresh catalog under a new generation, then swap the old one out.

    Returns ``{"loaded": [...per-language summaries...], "removed": {entity: n}}``.
    Raises ``seed_catalog.SeedAborted`` if the load failed one of its own rails,
    or if it produced nothing to swap to.
    """
    gen = new_ulid()
    repo.acquire_import_lock(gen)  # raises ImportInProgressError if one is running
    try:
        repo.set_catalog_generation(gen)
        loaded = []
        # A dry run writes nothing, so nothing carries `gen`. Collect the ids the
        # reseed WOULD write so the purge can report a real prediction instead of
        # "the entire catalog" — this is the operator's last check before an
        # irreversible, backup-less wipe, so an inflated number is worse than no
        # number at all. On a real run the rows are stamped and this is not needed.
        predicted_ids: set | None = None if execute else set()
        for language in languages:
            print(f"{language.label}:")
            summary = seed_catalog.seed_language(
                repo, client, language, execute=execute,
                allow_unverified=allow_unverified, id_sink=predicted_ids,
            )
            print(f"  {summary}")
            loaded.append(summary)

        seeded = sum(s["cards_seeded"] for s in loaded)
        if not seeded:
            raise seed_catalog.SeedAborted(
                "the reseed produced no cards; refusing to swap, because "
                "deleting the live catalog and putting nothing in its place is "
                "worse than leaving it stale"
            )

        # The sweep is scoped to the languages this run actually reseeded. A
        # `--language en` retry stamps only English rows, so an unscoped purge
        # would delete the whole Japanese catalog as "not of this generation"
        # and exit 0. Legacy rows carrying no language prefix are still removed —
        # they are the dead pokemontcg.io catalog this wipe exists to clear.
        removed = repo.purge_card_data(
            keep_catalog_gen=gen,
            languages={LANGUAGE_API_CODE[lang] for lang in languages},
            keep_card_ids=predicted_ids,
            dry_run=not execute,
        )
        return {"loaded": loaded, "removed": removed}
    finally:
        repo.set_catalog_generation(None)
        repo.release_import_lock(gen)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", action="append",
                        choices=sorted(LANGUAGE_API_CODE.values()),
                        help="API language code to seed (repeatable); default: all")
    parser.add_argument("--execute", action="store_true",
                        help="actually load and delete; without it this is a dry run")
    parser.add_argument("--confirm-table",
                        help="the table name you intend to wipe; must match the "
                             "configured target when --execute is given")
    parser.add_argument("--allow-unverified", action="store_true",
                        help="accept a catalog whose size could not be "
                             "cross-checked against the set list (the run "
                             "aborts without this)")
    args = parser.parse_args(argv)
    languages = ([lang for lang in Language if LANGUAGE_API_CODE[lang] in args.language]
                 if args.language else list(Language))

    table, region = settings.dynamodb_table_name, settings.aws_region
    mode = "WIPING AND RESEEDING" if args.execute else "DRY RUN against"
    print(f"Card-data wipe + TCGdex reseed — {mode} DynamoDB table "
          f"'{table}' ({region})...")

    if args.execute and args.confirm_table != table:
        print(
            f"refusing to wipe: --confirm-table={args.confirm_table!r} does not "
            f"match the configured target {table!r}. This table serves "
            f"/inventory; name it explicitly to delete from it.",
            file=sys.stderr,
        )
        return 2

    repo = _repository()
    with _client() as client:
        try:
            result = wipe_and_reseed(repo, client, languages, execute=args.execute,
                                     allow_unverified=args.allow_unverified)
        except ImportInProgressError as exc:
            print(f"REFUSED: {exc}", file=sys.stderr)
            return 1
        except seed_catalog.SeedAborted as exc:
            print(f"ABORTED before the swap; nothing was deleted: {exc}",
                  file=sys.stderr)
            return 1

    verb = "removed" if args.execute else "would remove"
    print(f"\nCard data {verb}:")
    for entity, count in sorted(result["removed"].items()):
        print(f"  {entity}: {count}")
    scope = ", ".join(sorted(LANGUAGE_API_CODE[lang] for lang in languages))
    print(f"  preserved: shows, consignors, config, auth and rate-limit rows; "
          f"hand-entered graded prices; sealed/bulk price history; and every "
          f"language outside this run's scope ({scope})")
    if not args.execute:
        print("\nDry run: nothing was loaded and nothing was deleted. Re-run with "
              f"--execute --confirm-table {table}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
