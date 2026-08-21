"""Scheduled sync dispatcher: EventBridge Scheduler → ECS RunTask entry point.

This script is the single CLI entry point for all automated sync jobs. It is
invoked by ECS tasks triggered by EventBridge Scheduler, with the specific job
selected via ``--job``:

    python -m scripts.scheduled_sync --job prices
    python -m scripts.scheduled_sync --job catalog

Each invocation logs a single structured JSON summary line to stdout (the only
thing CloudWatch will reliably capture from a Fargate task) and exits 0 on
success, non-zero on failure, so ECS surfaces the failure and EventBridge
retry / DLQ can act on it.

**Architecture decision (ECS over Lambda):** these jobs run inside the existing
backend container image, which already carries all dependencies (boto3,
merlins_collection, tcgdex client) and whose ECS task role already grants the
required DynamoDB access. A new-set catalog sync can exceed Lambda's hard
15-minute timeout. ECS RunTask reuses the existing infrastructure with no new
deployment artefacts.
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import date

from merlins_collection.config import settings
from merlins_collection.services.catalog_sync import run_daily_sync, sync_new_sets
from merlins_collection.services.dynamodb import InventoryRepository
from merlins_collection.services.tcgdex import TcgdexClient

VALID_JOBS = ("prices", "catalog")


def _repository():
    """The live repository; patched out in tests so nothing touches real AWS."""
    return InventoryRepository(settings.dynamodb_table_name,
                               region_name=settings.aws_region)


# Alias so tests can monkeypatch the context manager without touching the real
# import — mirrors how test_daily_sync.py patches TcgdexClient on the script.
_tcgdex_client = TcgdexClient


def _json_summary(*, job: str, status: str, summary: dict | None = None,
                   error: str | None = None) -> str:
    """Build the single structured JSON line for CloudWatch."""
    payload: dict = {"job": job, "status": status}
    if summary is not None:
        payload["summary"] = summary
    if error is not None:
        payload["error"] = error
    return json.dumps(payload, default=str)


def main(argv: list[str] | None = None) -> int:
    """Parse args, dispatch the requested job, and return a shell exit code."""
    parser = argparse.ArgumentParser(
        description="Dispatch a scheduled sync job.",
    )
    parser.add_argument(
        "--job",
        required=True,
        choices=VALID_JOBS,
        help="Which sync job to run: 'prices' or 'catalog'.",
    )
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        # argparse calls sys.exit on --help or invalid args; translate to a
        # return code so the caller (tests, ECS) gets a clean signal.
        return 2

    repo = _repository()

    try:
        with _tcgdex_client() as client:
            if args.job == "prices":
                result = run_daily_sync(repo, client, date.today())
            elif args.job == "catalog":
                result = sync_new_sets(repo, client, dry_run=False)
            else:
                # Should be unreachable (argparse enforces choices), but belt
                # and suspenders.
                print(_json_summary(job=args.job, status="error",
                                    error=f"Unknown job: {args.job}"))
                return 1
    except Exception as exc:
        print(_json_summary(job=args.job, status="error",
                            error=f"{type(exc).__name__}: {exc}"))
        traceback.print_exc(file=sys.stderr)
        return 1

    print(_json_summary(job=args.job, status="ok", summary=result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
