"""One-shot spreadsheet import: CSV tab exports -> DynamoDB.

Usage: python backend/scripts/import_spreadsheet.py <csv_dir> [--table merlins-cards]
Re-running is safe: ids are deterministic, so rows overwrite instead of duplicate.
"""

import argparse

from merlins_collection.services.dynamodb import InventoryRepository
from merlins_collection.services.spreadsheet_import import run_import


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_dir", help="directory of <Tab>.csv exports")
    parser.add_argument("--table", default="merlins-cards")
    args = parser.parse_args()
    repo = InventoryRepository(args.table)
    for tab, summary in run_import(args.csv_dir, repo).items():
        print(f"{tab}: {summary}")


if __name__ == "__main__":
    main()
