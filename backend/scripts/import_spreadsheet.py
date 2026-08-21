"""One-shot spreadsheet import: CSV tab exports -> DynamoDB.

Usage: python backend/scripts/import_spreadsheet.py <csv_dir> [--table merlins-cards]
                                                   [--allow-empty "Payouts,Debts"]
                                                   [--force-replace]
                                                   [--singles-only]

--SINGLES-ONLY is a separate, narrower run. It reads exactly one file --
Singles_enriched_v3.csv -- and touches only inventory_item/transaction: the guard
below asks about those two entities alone, and the commit sweep may delete only
those two. Shows, debts, payouts, consignors, cash accounts, buying policies,
payment methods and balance sheets are neither probed nor swept. It exists
because the live table holds real, backup-less business data from those other
ledgers that this rebuild does not re-import, and the full run below can only
either refuse over that data or replace all of it. Without this flag the run is
byte-for-byte what it always was: all 18 tabs, full guard, full sweep.

RE-IMPORT IS DELIBERATELY LOCKED. This is a ONE-SHOT migration tool. Once the
spreadsheet has been imported, the DATABASE is the source of truth: corrections,
and eventually the app's own write endpoints, land there, not in the sheet. A
second import is not an "update": it REPLACES every import-owned record
(inventory, transactions, expenses, debts, payouts, shows, consignors, cash
accounts, buying policies, payment methods, balance-sheet snapshots) with
whatever the sheet currently says, discarding everything written since.

So if the target table already holds any import-owned business data, the run
refuses with ExistingBusinessDataError before writing anything. Passing
--force-replace is the operator's deliberate acknowledgement that replacing the
live business data is the intent. The catalog (catalog_card / price_point) is not
import-owned, so a freshly seeded catalog-only table still imports without it.

The replace itself is still safe once you have opted in: the whole new dataset is
loaded under a fresh generation and the previous one is swapped out only if every
tab succeeded.

A present tab that imports ZERO records fails the run by default, because a
truncated export and a genuinely empty ledger look identical on disk. If a ledger
really is empty for this period, acknowledge it explicitly with --allow-empty.
"""

import argparse

from merlins_collection.services.dynamodb import InventoryRepository
from merlins_collection.services.spreadsheet_import import (
    SINGLES_ONLY_CSV_NAME,
    run_import,
    run_singles_only_import,
)


def main() -> None:
    # Raw description: the re-import lock explanation is the most important thing
    # on this page and must not be reflowed into one unreadable blob.
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("csv_dir", help="directory of <Tab>.csv exports")
    parser.add_argument("--table", default="merlins-cards")
    parser.add_argument(
        "--allow-empty", default="",
        help="comma-separated tab names that are legitimately empty this run "
             '(e.g. --allow-empty "Payouts,Debts")',
    )
    parser.add_argument(
        "--force-replace", action="store_true",
        help="proceed even though the table already holds business data, "
             "REPLACING it with the spreadsheet's contents (see module docstring)",
    )
    parser.add_argument(
        "--singles-only", action="store_true",
        help=f"import ONLY {SINGLES_ONLY_CSV_NAME}, guarding and sweeping only "
             f"inventory_item/transaction (see module docstring)",
    )
    args = parser.parse_args()
    if args.singles_only and args.allow_empty:
        # --allow-empty names TABS, and a Singles-only run has exactly one, which
        # is never allowed to be empty. Silently ignoring the flag would leave the
        # operator believing an acknowledgement was accepted.
        parser.error("--allow-empty does not apply to --singles-only: that run "
                     "reads one file and refuses to commit it empty.")
    allow_empty = frozenset(
        t.strip() for t in args.allow_empty.split(",") if t.strip()
    )
    repo = InventoryRepository(args.table)
    if args.singles_only:
        summaries = run_singles_only_import(args.csv_dir, repo,
                                            force_replace=args.force_replace)
    else:
        summaries = run_import(args.csv_dir, repo, allow_empty=allow_empty,
                               force_replace=args.force_replace)
    for tab, summary in summaries.items():
        print(f"{tab}: {summary}")


if __name__ == "__main__":
    main()
