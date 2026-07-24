"""One-shot spreadsheet import: CSV tab exports -> DynamoDB.

Usage: python backend/scripts/import_spreadsheet.py <csv_dir> [--table merlins-cards]
                                                   [--allow-empty "Payouts,Debts"]
                                                   [--force-replace]

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
from merlins_collection.services.spreadsheet_import import run_import


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
    args = parser.parse_args()
    allow_empty = frozenset(
        t.strip() for t in args.allow_empty.split(",") if t.strip()
    )
    repo = InventoryRepository(args.table)
    for tab, summary in run_import(args.csv_dir, repo, allow_empty=allow_empty,
                                   force_replace=args.force_replace).items():
        print(f"{tab}: {summary}")


if __name__ == "__main__":
    main()
