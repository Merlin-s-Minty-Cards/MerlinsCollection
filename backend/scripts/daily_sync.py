"""Daily scheduled job: price snapshots + inventory market-value refresh.

This is the executable entry point for ``services.catalog_sync.run_daily_sync``.
It exists because it must: the Phase 1 rewrite of ``seed_catalog.py`` left the
daily job with zero callers, which silently took the graded-slab snapshot, the
sealed snapshot and the market-value refresh offline **with a green test suite**
(revision-1 verdict, BLOAT-1). A silently-disabled scheduled job is invisible
until someone asks why a chart has been flat for a month, so the job now has a
script that runs it and a test that drives that script the way cron would.

**Five** steps, in a load-bearing order. The TCGdex depth pass
(``refresh_held_prices``) runs first and the graded pricing pass
(``refresh_graded_prices``, RFC 0009 T7) second, because the three
DynamoDB-only steps that follow snapshot and denormalize whatever those two
wrote — the other order publishes yesterday's figures for a day.

Those first two are the only steps that talk to an upstream API, and both only
for stock the business actually holds: ~300 paced TCGdex requests, plus at most
50 metered pricing lookups (the free tier is 100 credits and a graded lookup
costs 2). A TCGdex outage costs the day's raw refresh; an unset or dead pricing
key costs the day's slab prices and **nothing else**, because that step degrades
alone rather than aborting the run. The site reads every price from DynamoDB and
never from a vendor.

Exit codes, because this job is unattended and its only universally-readable
signal is the one the shell gets:

===  ============================================================
  0  the depth pass completed (per-card failures may still be > 0)
  1  the depth pass ABORTED on consecutive failures — upstream is down
  2  the depth pass was SKIPPED — the catalog lock was held, it did nothing
===  ============================================================

``1`` and ``2`` are distinct because they need different responses: chase
TCGdex, versus clear a stale lock. ``2`` is non-zero rather than a quiet
success on purpose — a lock-skip is tolerable once and pathological if it
repeats, no single run can tell those apart, and with the reseed side unwired
the only thing that can be holding this lock is a dead depth pass. A week of
silent no-ops must not look like a week of clean runs.

Run from ``backend/`` with the project venv active:

    python scripts/daily_sync.py
"""

from __future__ import annotations

import sys
from datetime import date

from merlins_collection.config import settings
from merlins_collection.services.catalog_sync import run_daily_sync
from merlins_collection.services.dynamodb import InventoryRepository
from merlins_collection.services.tcgdex import TcgdexClient


EXIT_OK = 0
EXIT_ABORTED = 1
EXIT_SKIPPED = 2


def _repository():
    """The live repository; patched out in tests so nothing touches real AWS."""
    return InventoryRepository(settings.dynamodb_table_name,
                               region_name=settings.aws_region)


def _report(summary: dict) -> int:
    """Print the run's verdict in a form an operator can act on; return its code.

    The per-key dump above this is the detail; this is the headline. Every state
    other than a completed run gets a shouted, greppable prefix AND a non-zero
    code, so both a human reading stdout and a monitor that only ever sees
    ``$?`` learn the same thing. The three DynamoDB-only steps run regardless of
    what the depth pass did, which is why the messages say which part failed.
    """
    if summary.get("skipped"):
        print(f"SKIPPED: the depth pass did not run ({summary['skipped']}). "
              f"No TCGdex prices were refreshed today; the DynamoDB-only steps "
              f"still ran. Clear a stale catalog lock if this repeats.")
        return EXIT_SKIPPED
    if summary.get("aborted"):
        print(f"ABORTED: the depth pass stopped after "
              f"{summary.get('failures', '?')} consecutive failures — treat "
              f"TCGdex as down. Existing prices are untouched; the "
              f"DynamoDB-only steps still ran.")
        return EXIT_ABORTED
    print("OK: all steps completed.")
    return EXIT_OK


def main() -> int:
    """Run the daily steps, print the summary, and return a shell exit code."""
    repo = _repository()
    print(
        f"Daily sync against DynamoDB table "
        f"'{settings.dynamodb_table_name}' ({settings.aws_region})..."
    )
    # The client owns an HTTP connection pool, so it is closed on every path —
    # including a raise — rather than left to the interpreter on a long-lived host.
    with TcgdexClient() as client:
        summary = run_daily_sync(repo, client, date.today())
    for key, value in summary.items():
        print(f"  {key}: {value}")
    return _report(summary)


if __name__ == "__main__":
    sys.exit(main())
