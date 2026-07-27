"""Daily scheduled job: price snapshots + inventory market-value refresh.

This is the executable entry point for ``services.catalog_sync.run_daily_sync``.
It exists because it must: the Phase 1 rewrite of ``seed_catalog.py`` left the
daily job with zero callers, which silently took the graded-slab snapshot, the
sealed snapshot and the market-value refresh offline **with a green test suite**
(revision-1 verdict, BLOAT-1). A silently-disabled scheduled job is invisible
until someone asks why a chart has been flat for a month, so the job now has a
script that runs it and a test that drives that script the way cron would.

Read-only against TCGdex — it touches no upstream API at all. The three steps
work off data already in DynamoDB: manual graded values, sealed item values, and
catalog prices written by the (Phase 2) depth pass.

Run from ``backend/`` with the project venv active:

    python scripts/daily_sync.py
"""

from __future__ import annotations

import sys
from datetime import date

from merlins_collection.config import settings
from merlins_collection.services.catalog_sync import run_daily_sync
from merlins_collection.services.dynamodb import InventoryRepository


def _repository():
    """The live repository; patched out in tests so nothing touches real AWS."""
    return InventoryRepository(settings.dynamodb_table_name,
                               region_name=settings.aws_region)


def main() -> int:
    """Run the daily steps, print the summary, and return a shell exit code."""
    repo = _repository()
    print(
        f"Daily sync against DynamoDB table "
        f"'{settings.dynamodb_table_name}' ({settings.aws_region})..."
    )
    summary = run_daily_sync(repo, date.today())
    for key, value in summary.items():
        print(f"  {key}: {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
