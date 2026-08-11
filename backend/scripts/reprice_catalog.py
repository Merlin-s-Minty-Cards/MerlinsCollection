"""One-time overnight run: re-price the WHOLE catalog, chunk by chunk.

    cd backend
    ../.venv/Scripts/python.exe scripts/reprice_catalog.py                  # DRY RUN
    ../.venv/Scripts/python.exe scripts/reprice_catalog.py --limit 200 --execute --confirm-table merlins-cards
    ../.venv/Scripts/python.exe scripts/reprice_catalog.py --execute --confirm-table merlins-cards

Call the venv interpreter explicitly. A bare ``python`` on this machine resolves
to an unrelated environment that cannot import ``merlins_collection``, and this
file has no shebang, so invoking it as ``scripts/reprice_catalog.py`` hands it to
the shell, which reads this docstring as commands.

**THIS IS NOT A SCHEDULED JOB, AND IT IS NOT A SEED.** Three jobs in this repo
touch the catalog and they are easy to confuse:

- ``scripts/seed_catalog.py`` CREATES catalog rows (identity only, no prices);
- the nightly ``refresh_held_prices`` prices only the ~300 cards we HOLD, and
  the nightly ``refresh_catalog_prices`` cycle prices ~5,500 unheld rows a night
  so the whole catalog is covered within a week;
- **this** script prices every unheld row in ONE run, so the weekly cycle starts
  from full coverage instead of taking ~6 nights to reach it. It is also how to
  force a full re-price after a catalog reseed.

It is a DRIVER, not a second implementation: the pricing is
``services.catalog_sync.refresh_catalog_prices``, the same function the nightly
cycle calls. Two implementations of "price a card" is a divergence this repo has
already paid for twice.

**A DRY RUN IS THE DEFAULT.** Nothing is written without ``--execute`` AND
naming the target table back via ``--confirm-table``. The dry run prints the
candidate count, the chunk plan and the estimated runtime, so "leave it going
overnight" is a decision made with a number rather than a hope.

**Why it works in chunks.** The catalog lock's TTL is 3600 s and the full run is
~2 h 18 min, so a single hold would outlive its own lock — at which point the
lock looks like a crashed holder and becomes stealable, and a write landing
across a reseed's swap carries the superseded generation and is swept, making
the card silently disappear from a live catalog. Chunking takes and releases the
lock per chunk (~2,000 cards, ~9 min), which needs no new primitive — no
heartbeat, no renew, no raised TTL — and lets a waiting reseed in between chunks
instead of starving it for two hours. If a chunk cannot take the lock the script
STOPS and says so; resume by re-running it.

**Resumability is free and there is nothing to configure.** Candidates are
chosen never-priced-first then stalest-first, so a card this run priced is now
the freshest thing in the catalog: kill the run at 90 minutes, re-run it, and it
continues with whatever is still unpriced or oldest. No checkpoint file, no
``--resume``, no state that can be wrong.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from merlins_collection.config import settings
from merlins_collection.services.catalog_sync import (
    SECONDS_PER_CARD,
    refresh_catalog_prices,
    select_catalog_refresh_candidates,
)
from merlins_collection.services.dynamodb import InventoryRepository
from merlins_collection.services.tcgdex import TcgdexClient

EXIT_OK = 0
EXIT_ABORTED = 1
EXIT_REFUSED = 2
EXIT_LOCKED = 3
EXIT_INTERRUPTED = 4

DEFAULT_CHUNK_SIZE = 2000

# 3600 s of lock TTL / 0.262 s per card is ~13,700, and a chunk that large would
# finish at the exact moment its own lock expired. 12,000 keeps a margin while
# still refusing loudly rather than clamping silently — a chunk size is typed by
# a person at 11 p.m. and a silent clamp would hide the typo until the morning.
MAX_CHUNK_SIZE = 12000


def _repository(table: str, region: str):
    """The live repository; patched out in tests so nothing touches real AWS."""
    return InventoryRepository(table, region_name=region)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--table", default=settings.dynamodb_table_name,
                        help="DynamoDB table to read/write (default: %(default)s)")
    parser.add_argument("--region", default=settings.aws_region,
                        help="AWS region (default: %(default)s)")
    parser.add_argument("--execute", action="store_true",
                        help="actually write. WITHOUT THIS FLAG NOTHING IS WRITTEN.")
    parser.add_argument("--confirm-table",
                        help="the table name you intend to write to; must match "
                             "--table when --execute is given")
    parser.add_argument("--limit", type=int, default=None,
                        help="price at most N cards (prove it on a slice first)")
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE,
                        help="cards per lock acquisition (default: %(default)s, "
                             f"max {MAX_CHUNK_SIZE})")
    parser.add_argument("--request-delay", type=float, default=0.1,
                        help="seconds between TCGdex requests (default: %(default)s)")
    parser.add_argument("--max-consecutive-failures", type=int, default=25,
                        help="abort the run after this many in a row "
                             "(default: %(default)s)")
    return parser


def _format_duration(seconds: float) -> str:
    hours, remainder = divmod(int(seconds), 3600)
    minutes = remainder // 60
    return f"{hours}h{minutes:02d}m" if hours else f"{minutes}m"


def main(argv=None) -> int:
    args = _parser().parse_args(argv)

    if args.execute and args.confirm_table != args.table:
        print(f"refusing to write: --confirm-table={args.confirm_table!r} does "
              f"not match --table {args.table!r}. This table serves /inventory; "
              f"name it explicitly to write to it.", file=sys.stderr)
        return EXIT_REFUSED
    if not 1 <= args.chunk_size <= MAX_CHUNK_SIZE:
        print(f"refusing to run: --chunk-size must be between 1 and "
              f"{MAX_CHUNK_SIZE}. A larger chunk holds the catalog lock past "
              f"its own 3600s TTL, which loses catalog rows rather than prices.",
              file=sys.stderr)
        return EXIT_REFUSED

    repo = _repository(args.table, args.region)
    mode = "EXECUTE" if args.execute else "DRY RUN — nothing will be written"
    print(f"{args.table} ({args.region}) — {mode}")
    print("selecting candidates (one full catalog scan, ~10s against the live "
          "table)…")

    # Selected ONCE for the whole run, then fed to the pass in chunks. Letting
    # each chunk re-select would re-fetch every card TCGdex 404s — those never
    # get a fresher `last_synced_at`, so they stay at the head of the
    # stalest-first queue and would lead every chunk of the run.
    candidates = select_catalog_refresh_candidates(repo, limit=args.limit)
    total = len(candidates)
    chunks = -(-total // args.chunk_size)  # ceil
    estimate = total * SECONDS_PER_CARD
    print(f"{total:,} candidates · {chunks} chunk(s) of {args.chunk_size:,} · "
          f"estimated runtime {_format_duration(estimate)}")

    if not total:
        print("no candidates: every catalog card we do not hold is already "
              "fresh, or the catalog is empty (run scripts/seed_catalog.py).")
        return EXIT_OK
    if not args.execute:
        print(f"\nDry run: nothing was written. Re-run with "
              f"--execute --confirm-table {args.table}")
        return EXIT_OK

    today = date.today()
    done = failures = 0
    with TcgdexClient() as client:
        for index in range(chunks):
            batch = candidates[index * args.chunk_size:(index + 1) * args.chunk_size]
            try:
                summary = refresh_catalog_prices(
                    repo, client, today, card_ids=batch,
                    request_delay_seconds=args.request_delay,
                    max_consecutive_failures=args.max_consecutive_failures,
                )
            except KeyboardInterrupt:
                # The lock is already released: `refresh_catalog_prices` frees it
                # in a `finally`, and KeyboardInterrupt is a BaseException so the
                # per-card `except Exception` never swallowed it. Everything
                # written so far stands — an interrupt is a stop, not a rollback.
                print(f"\nINTERRUPTED after {done:,} of {total:,} cards. The "
                      f"catalog lock is released. Re-run to continue from here; "
                      f"stalest-first ordering means nothing was lost.")
                return EXIT_INTERRUPTED

            if summary["catalog_skipped"]:
                print(f"STOPPING: could not take the catalog lock "
                      f"({summary['catalog_skipped']}) at chunk {index + 1} of "
                      f"{chunks}. {done:,} of {total:,} cards were priced. "
                      f"Re-run once the reseed finishes.")
                return EXIT_LOCKED

            done += summary["catalog_cards_updated"]
            failures += summary["catalog_failures"]
            remaining = (total - (index + 1) * args.chunk_size) * SECONDS_PER_CARD
            print(f"  chunk {index + 1}/{chunks}: {done:,}/{total:,} priced, "
                  f"{summary['catalog_not_found']} not found, {failures} "
                  f"failures, ETA {_format_duration(max(remaining, 0))}")

            if summary["catalog_aborted"]:
                print(f"ABORTED at chunk {index + 1} of {chunks} after "
                      f"{args.max_consecutive_failures} consecutive failures — "
                      f"treat TCGdex as down. Existing prices are untouched and "
                      f"{done:,} cards were priced before the stop; re-run when "
                      f"it recovers.")
                return EXIT_ABORTED

    print(f"\nOK: {done:,} of {total:,} cards repriced, {failures} failures.")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
