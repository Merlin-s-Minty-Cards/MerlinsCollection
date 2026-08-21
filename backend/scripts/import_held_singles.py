"""Scoped replace of the RAW singles inventory from the updated workbook.

The owner decided to track only current inventory. This replaces just the raw
singles — slabs, sealed, bulk and consignments are left untouched — with the
currently-held singles (not sold, not lost) from the new ``.xlsx``, matched to
the catalog by the normal importer (which now uses the row's TCGplayer link to
break set ties). Matched cards link and get a market price on the tile; the rest
come in flagged ``needs_review``.

Safe order: the new singles are written FIRST (fresh ULIDs, no collision), and
only then are the previously-stored raw items (captured up front) deleted — so
the inventory is never empty, and a mid-run failure leaves recoverable
duplicates rather than a hole.

    cd backend
    python scripts/import_held_singles.py --xlsx "../data/spreadsheet/7-25-2026 Inventory.xlsx"
    python scripts/import_held_singles.py --xlsx ... --dry-run   # count only, no writes
"""

from __future__ import annotations

import argparse
from collections import Counter

import openpyxl

from merlins_collection.config import settings
from merlins_collection.services.card_text import build_catalog_index
from merlins_collection.services.dynamodb import InventoryRepository
from merlins_collection.services.spreadsheet_import import ImportContext, import_singles, map_location


def read_held_single_rows(xlsx_path):
    """Held singles (not sold, not lost) as dicts keyed by the sheet's headers."""
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb["Singles"]
    it = ws.iter_rows(values_only=True)
    header = [str(h).strip() if h is not None else "" for h in next(it)]
    held = []
    for values in it:
        row = {h: v for h, v in zip(header, values) if h}
        name = str(row.get("Name") or "").strip()
        if not name:
            continue
        sold = str(row.get("Sold") or "").strip() or str(row.get("Date Sold") or "").strip()
        if sold or map_location(row.get("Location"))["status"] == "lost":
            continue
        held.append(row)
    return held


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--xlsx", required=True)
    parser.add_argument("--table", default=settings.dynamodb_table_name)
    parser.add_argument("--region", default=settings.aws_region)
    parser.add_argument("--dry-run", action="store_true", help="count only; write nothing")
    args = parser.parse_args(argv)

    repo = InventoryRepository(args.table, region_name=args.region)
    print(f"Table {args.table} ({args.region})")

    print("Building catalog index (read-only scan)...")
    index = build_catalog_index(repo.iter_catalog_cards())

    held_rows = read_held_single_rows(args.xlsx)
    print(f"Held singles in workbook: {len(held_rows)}")

    existing = repo.list_inventory()
    old_raw_ids = [i.item_id for i in existing if i.kind == "raw"]
    kinds = Counter(i.kind for i in existing)
    print(f"Current inventory: {dict(kinds)}  (raw to be replaced: {len(old_raw_ids)})")

    if args.dry_run:
        # Match without writing, to preview the auto-link rate.
        ctx = ImportContext(repo=_CountingRepo(), catalog_index=index)
        summary = import_singles(held_rows, ctx)
        linked = sum(1 for it in ctx.repo.items if it.card_id)
        print(f"[dry-run] would write {summary['imported']} singles "
              f"({linked} auto-linked, {summary['imported'] - linked} needs_review), "
              f"then delete {len(old_raw_ids)} old raw items. No writes made.")
        return

    # 1) ADD the new held singles (fresh ULIDs). Written straight to the table.
    ctx = ImportContext(repo=repo, catalog_index=index)
    summary = import_singles(held_rows, ctx)
    print(f"Wrote {summary['imported']} new singles "
          f"(skipped {summary['skipped']}, needs_review {summary['needs_review']}).")

    # 2) DELETE the previously-stored raw items, captured before the add.
    for i, iid in enumerate(old_raw_ids, 1):
        repo.delete_inventory_item(iid)
        if i % 50 == 0:
            print(f"  deleted {i}/{len(old_raw_ids)} old raw items...")
    print(f"Deleted {len(old_raw_ids)} old raw items.")

    after = Counter(i.kind for i in repo.list_inventory())
    print(f"Done. Inventory now: {dict(after)}")


class _CountingRepo:
    """A no-write repo for --dry-run: collects items instead of persisting."""

    def __init__(self):
        self.items = []

    def put_inventory_item(self, item):
        self.items.append(item)

    def record_sale(self, txn):  # held rows have no sales; present for safety
        pass


if __name__ == "__main__":
    main()
