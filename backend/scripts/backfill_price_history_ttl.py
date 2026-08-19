"""One-off backfill: stamp a `ttl` attribute onto every existing price-history
row (RFC 0015).

The write path (`services/dynamodb.py`'s `_price_point_item` and
`append_item_price_point`) now stamps every NEW `price_point`/`item_price_point`
row with a `ttl` attribute so DynamoDB's native TTL can expire it after
`settings.price_history_retention_days` (default 730 days / 2 years). Rows
written before that change carry no `ttl` and would never auto-expire on
their own. This script closes that gap for the rows that already exist.

    cd backend
    ../.venv/Scripts/python.exe scripts/backfill_price_history_ttl.py            # DRY RUN
    ../.venv/Scripts/python.exe scripts/backfill_price_history_ttl.py --execute

Call the venv interpreter explicitly. A bare ``python`` on this machine resolves
to an unrelated environment that cannot import ``merlins_collection``, and the
file has no shebang, so invoking it as ``scripts/backfill_price_history_ttl.py``
hands it to the shell, which reads this docstring as commands.

**A DRY RUN IS THE DEFAULT.** Nothing is written without ``--execute``.

**This is additive only** — it touches nothing but a `ttl` attribute on rows
that don't already have one, via a targeted `update_item` per row (never a
full-item replace, which could revert a concurrent nightly-sync write to the
same row mid-backfill). No card, inventory, or catalog-identity row is read
for mutation. That's why this takes the lighter `backfill_catalog_sets.py`
rail (`--execute` only) rather than `seed_catalog.py`/`wipe_catalog.py`'s
`--confirm-table`, which exists for genuinely destructive operations.

Requires DynamoDB's native TTL to actually be enabled on the table's `ttl`
attribute (a separate, one-time `aws dynamodb update-time-to-live` call —
see the RFC) for the stamp this script writes to do anything; running this
script without that enabled is harmless, just inert.

**Progress is printed per chunk, not just at the end.** The first version of
this script called the repository once and printed nothing until it returned.
Run for real against ~70,000 existing rows, that scan-then-serially-update
loop took roughly 90 minutes with ZERO output in between — indistinguishable
from a hang, and reported as exactly that. Candidates are now selected once
(fast — read-only), then applied in bounded chunks (`--chunk-size`, default
2,000) with a line printed after each one, the same shape
`reprice_catalog.py` uses over `refresh_catalog_prices`. There is no lock to
worry about here (unlike that script) — chunking exists purely so a human
watching the terminal sees it moving.
"""

from __future__ import annotations

import argparse
import time

from merlins_collection.config import settings
from merlins_collection.services.dynamodb import InventoryRepository

DEFAULT_CHUNK_SIZE = 2000


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--table", default=settings.dynamodb_table_name,
                        help="DynamoDB table to read/write (default: %(default)s)")
    parser.add_argument("--region", default=settings.aws_region,
                        help="AWS region (default: %(default)s)")
    parser.add_argument("--execute", action="store_true",
                        help="actually write. WITHOUT THIS FLAG NOTHING IS WRITTEN.")
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE,
                        help="rows written between progress lines "
                             "(default: %(default)s)")
    return parser


def _format_duration(seconds: float) -> str:
    hours, remainder = divmod(int(max(seconds, 0)), 3600)
    minutes = remainder // 60
    return f"{hours}h{minutes:02d}m" if hours else f"{minutes}m"


def main(argv=None) -> dict:
    args = _parser().parse_args(argv)
    repo = InventoryRepository(args.table, region_name=args.region)

    mode = "EXECUTE" if args.execute else "DRY RUN — nothing will be written"
    print(f"{args.table} ({args.region}) — {mode}")
    print("scanning price-history rows for ones missing a ttl…")

    candidates = repo.list_price_history_ttl_candidates()
    total = len(candidates)
    print(f"{total:,} candidate row(s) found.")

    if not total:
        print("no candidates: every price-history row already carries a ttl.")
        return {"candidates": 0, "written": 0, "executed": bool(args.execute),
                "interrupted": False}

    if not args.execute:
        print("\nDry run: nothing was written. "
              "Re-run with --execute to write these rows.")
        return {"candidates": total, "written": 0, "executed": False,
                "interrupted": False}

    chunks = -(-total // args.chunk_size)  # ceil
    written = 0
    interrupted = False
    start = time.monotonic()
    for index in range(chunks):
        batch = candidates[index * args.chunk_size:(index + 1) * args.chunk_size]
        try:
            written += repo.apply_price_history_ttl(batch)
        except KeyboardInterrupt:
            elapsed = time.monotonic() - start
            print(f"\nINTERRUPTED after {written:,} of {total:,} rows "
                  f"({_format_duration(elapsed)} elapsed). Safe to re-run — "
                  f"already-stamped rows are skipped automatically, so nothing "
                  f"already written gets redone.")
            interrupted = True
            break
        elapsed = time.monotonic() - start
        rate = written / elapsed if elapsed > 0 else 0
        eta = (total - written) / rate if rate > 0 else 0
        print(f"  chunk {index + 1}/{chunks}: {written:,}/{total:,} written, "
              f"ETA {_format_duration(eta)}")

    if not interrupted:
        print(f"\nOK: {written:,} of {total:,} rows stamped with ttl.")

    return {"candidates": total, "written": written, "executed": True,
            "interrupted": interrupted}


if __name__ == "__main__":
    main()
