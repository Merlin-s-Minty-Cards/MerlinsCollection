"""One-off backfill: build the ``catalog_set`` registry from the seeded catalog.

The registry (RFC 0008 T8) is one small row per set, so
``GET /admin/catalog/sets`` can list every set with a single query. Going
forward the catalog sync maintains it from the set-list response it already
fetches. This script exists for the catalog that is ALREADY seeded — ~31,600
card rows written before the registry existed, which no sync will revisit
because ``sync_new_sets`` deliberately never walks a set that has cards.

    cd backend
    ../.venv/Scripts/python.exe scripts/backfill_catalog_sets.py            # DRY RUN
    ../.venv/Scripts/python.exe scripts/backfill_catalog_sets.py --execute

Call the venv interpreter explicitly. A bare ``python`` on this machine resolves
to an unrelated environment that cannot import ``merlins_collection``, and the
file has no shebang, so invoking it as ``scripts/backfill_catalog_sets.py``
hands it to the shell, which reads this docstring as commands.

**ALREADY RUN against ``merlins-cards`` on 2026-08-06** — 284 sets registered
from 31,603 card rows. Re-running is a harmless upsert that refreshes the counts.

**A DRY RUN IS THE DEFAULT.** Nothing is written without ``--execute``; the dry
run prints every set it would register.

**This is the one place a full catalog scan is acceptable, and it is why the
script exists at all.** Deriving the set list from card rows is a ~12-page,
11-second read — the operation T9 diagnosed as the cause of the dead catalog
search. That is fine to pay ONCE, offline, from a CLI. It is not fine on a
request path, which is exactly what the registry exists to prevent, so nothing
importable by the API imports this module.

``card_count`` is counted from real rows here, matching what the sync writes —
never TCGdex's advertised ``cardCount.total``, which for over half of TCGdex's
Japanese sets describes cards nobody has entered and our catalog does not have.

The write is an upsert and touches nothing but ``catalog_set`` rows: no card,
inventory, price or transaction row is read for mutation or written.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from merlins_collection.config import settings
from merlins_collection.models.inventory import Language
from merlins_collection.services.dynamodb import InventoryRepository
from merlins_collection.services.tcgdex import parse_card_id


def build_registry_rows(repo, *, now: datetime | None = None) -> list[dict]:
    """Aggregate the catalog's card rows into one registry row per set.

    A single pass over the scan — the cards are streamed, never all held in
    memory, since the whole catalog parsed at once measures ~93 MB.

    ``language`` comes from the card's own stored field, with the ``set_id``
    prefix as the fallback for pre-language rows. A set whose cards disagree
    about their language takes the first one seen; that would be a data defect
    upstream of this script and is not something a backfill should silently
    "fix" by picking a winner per row.
    """
    stamped_at = (now or datetime.now(timezone.utc)).isoformat()
    rows: dict[str, dict] = {}
    for card in repo.iter_catalog_cards():
        if not card.set_id:
            continue
        row = rows.get(card.set_id)
        if row is None:
            rows[card.set_id] = row = {
                "set_id": card.set_id,
                "set_name": card.set_name or "",
                "language": _language_of(card),
                "card_count": 0,
                "updated_at": stamped_at,
            }
        # A brief row seeded without `set_names` carries an empty set_name; a
        # later, named row for the same set fills it in rather than being
        # ignored because the first row happened to be blank.
        if not row["set_name"] and card.set_name:
            row["set_name"] = card.set_name
        row["card_count"] += 1
    return sorted(rows.values(), key=lambda r: r["set_id"])


def _language_of(card) -> str:
    if card.language:
        return card.language.value if hasattr(card.language, "value") else str(card.language)
    parsed = parse_card_id(card.set_id)
    return parsed[0].value if parsed else Language.EN.value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--table", default=settings.dynamodb_table_name,
                        help="DynamoDB table to read/write (default: %(default)s)")
    parser.add_argument("--region", default=settings.aws_region,
                        help="AWS region (default: %(default)s)")
    parser.add_argument("--execute", action="store_true",
                        help="actually write. WITHOUT THIS FLAG NOTHING IS WRITTEN.")
    return parser


def _make_stdout_printable() -> None:
    """Let this script's own output survive a console that is not UTF-8.

    Windows consoles default to cp1252, which cannot encode the Japanese set
    names this catalog is full of. The listing below is printed BEFORE the write,
    so on a default Windows shell the first Japanese set raised
    ``UnicodeEncodeError`` and killed the run having written nothing — with the
    English sets already scrolled past, it looked like the backfill had worked.

    ``errors="replace"`` keeps it merely lossy on an old console instead of
    fatal, and a modern terminal renders the names properly. This touches
    display only: the rows written to DynamoDB carry the real names either way.
    """
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        # A stream that cannot be reconfigured (a pipe someone wrapped, a test
        # double) still prints; it just keeps whatever encoding it arrived with.
        pass


def main(argv=None) -> dict:
    args = _parser().parse_args(argv)
    _make_stdout_printable()
    repo = InventoryRepository(args.table, region_name=args.region)

    mode = "EXECUTE" if args.execute else "DRY RUN — nothing will be written"
    print(f"{args.table} ({args.region}) — {mode}")
    print("scanning the catalog once; this takes ~10s against the live table…")

    rows = build_registry_rows(repo)
    for row in rows:
        print(f"  {row['set_id']:<24} {row['language']:<3} "
              f"{row['card_count']:>6} cards  {row['set_name']}")

    written = repo.put_catalog_sets(rows) if args.execute else 0
    summary = {"sets_found": len(rows), "sets_written": written,
               "cards_scanned": sum(r["card_count"] for r in rows),
               "executed": bool(args.execute)}
    print(f"\n{summary}")
    if not args.execute and rows:
        print("re-run with --execute to write these rows.")
    return summary


if __name__ == "__main__":
    main()
