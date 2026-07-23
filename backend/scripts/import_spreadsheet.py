"""One-shot spreadsheet import: CSV tab exports -> DynamoDB.

Usage: python backend/scripts/import_spreadsheet.py <csv_dir> [--table merlins-cards]
                                                   [--allow-empty "Payouts,Debts"]

Re-running is safe: the whole new dataset is loaded under a fresh generation and
the previous one is swapped out only if every tab succeeded.

A present tab that imports ZERO records fails the run by default, because a
truncated export and a genuinely empty ledger look identical on disk. If a ledger
really is empty for this period, acknowledge it explicitly with --allow-empty.
"""

import argparse

from merlins_collection.services.dynamodb import InventoryRepository
from merlins_collection.services.spreadsheet_import import run_import


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_dir", help="directory of <Tab>.csv exports")
    parser.add_argument("--table", default="merlins-cards")
    parser.add_argument(
        "--allow-empty", default="",
        help="comma-separated tab names that are legitimately empty this run "
             '(e.g. --allow-empty "Payouts,Debts")',
    )
    args = parser.parse_args()
    allow_empty = frozenset(
        t.strip() for t in args.allow_empty.split(",") if t.strip()
    )
    repo = InventoryRepository(args.table)
    for tab, summary in run_import(args.csv_dir, repo,
                                   allow_empty=allow_empty).items():
        print(f"{tab}: {summary}")


if __name__ == "__main__":
    main()
