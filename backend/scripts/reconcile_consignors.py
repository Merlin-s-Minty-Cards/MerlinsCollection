"""One-time cleanup: collapse consignors that the row fork already duplicated.

    cd backend
    ../.venv/Scripts/python.exe scripts/reconcile_consignors.py       # DRY RUN
    ../.venv/Scripts/python.exe scripts/reconcile_consignors.py \
        --execute --confirm-table merlins-cards

Call the venv interpreter explicitly. A bare ``python`` on this machine resolves
to an unrelated environment that cannot import ``merlins_collection``, and this
file has no shebang, so invoking it as ``scripts/reconcile_consignors.py`` hands
it to the shell, which reads this docstring as commands.

**RFC 0010 T2 fixed the CAUSE; this fixes the DAMAGE.** ``put_consignor`` now
sweeps superseded rows, so no new fork can appear. It does not merge the two
Harrys already sitting in the live table, because nothing rewrites a consignor
until somebody edits it — and editing is the thing that hurt.

**A DRY RUN IS THE DEFAULT.** Nothing is written without ``--execute`` AND
naming the target table back via ``--confirm-table``. The dry run prints every
row it would keep and every row it would remove.

**Which row wins is the load-bearing decision, and it is NOT "the highest
generation".** An admin edit runs with no import generation set, so it writes the
*unsuffixed* sort key — which is therefore the most recently written of the pair,
and the one carrying the values the admin typed (the owner's 85% Harry). Keeping
the highest ``#<gen>`` suffix instead would silently discard exactly the edit
that made the fork visible. Only when no admin ever edited — every row carries a
generation — does "newest" mean "highest generation".

**It removes rows by re-writing the winner through ``put_consignor``**, so the
cleanup runs down the same sweep the fix installed rather than a second,
parallel notion of which rows are superseded.

**Do not run this while an import is in flight.** Coexisting generations are
load-then-swap's whole point during the load phase; only after
``finalize_import`` commits is a second row unambiguously a fork.
"""

from __future__ import annotations

import argparse
import sys

from merlins_collection.config import settings
from merlins_collection.models.business import Consignor
from merlins_collection.services.dynamodb import InventoryRepository


def _repository(table: str, region: str):
    """The live repository; patched out in tests so nothing touches real AWS."""
    return InventoryRepository(table, region_name=region)


def _winner(consignor_id: str, rows: list[dict]) -> dict:
    """The row whose values survive — see the module docstring."""
    unsuffixed = f"CONSIGNOR#{consignor_id}"
    for row in rows:
        if row["SK"] == unsuffixed:
            return row
    return max(rows, key=lambda r: r["SK"])


def plan_reconcile(repo) -> list[dict]:
    """One entry per FORKED consignor. Untouched consignors are not listed."""
    groups: dict[str, list[dict]] = {}
    for row in repo.list_consignor_rows():
        consignor_id = row.get("consignor_id")
        if consignor_id:
            groups.setdefault(consignor_id, []).append(row)

    plans = []
    for consignor_id, rows in sorted(groups.items()):
        if len(rows) < 2:
            continue
        keep = _winner(consignor_id, rows)
        plans.append({
            "consignor_id": consignor_id,
            "name": keep.get("name", ""),
            "keep_sk": keep["SK"],
            "remove_sks": sorted(r["SK"] for r in rows if r["SK"] != keep["SK"]),
            "winner": keep,
        })
    return plans


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
    return parser


def main(argv=None) -> dict:
    args = _parser().parse_args(argv)

    if args.execute and args.confirm_table != args.table:
        print(f"refusing to write: --confirm-table={args.confirm_table!r} does "
              f"not match --table {args.table!r}. This table serves /inventory; "
              f"name it explicitly to write to it.", file=sys.stderr)
        return {"forked": 0, "rows_removed": 0, "executed": False, "refused": True}

    repo = _repository(args.table, args.region)
    mode = "EXECUTE" if args.execute else "DRY RUN — nothing will be written"
    print(f"{args.table} ({args.region}) — {mode}")

    plans = plan_reconcile(repo)
    for plan in plans:
        print(f"  {plan['consignor_id']}  {plan['name']}")
        print(f"      keep   {plan['keep_sk']}")
        for sk in plan["remove_sks"]:
            print(f"      remove {sk}")

    removed = 0
    if args.execute:
        for plan in plans:
            # Re-writing the winner runs the sweep put_consignor now performs,
            # rather than deleting rows by a second set of rules that could
            # disagree with it.
            repo.put_consignor(Consignor.model_validate(plan["winner"]))
            removed += len(plan["remove_sks"])

    summary = {"forked": len(plans), "rows_removed": removed,
               "executed": bool(args.execute), "refused": False}
    print(f"\n{summary}")
    if not args.execute and plans:
        print(f"re-run with --execute --confirm-table {args.table} to collapse these.")
    elif not plans:
        print("no forked consignors: every consignor already has exactly one row.")
    return summary


if __name__ == "__main__":
    main()
