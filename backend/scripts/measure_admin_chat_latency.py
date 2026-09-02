"""Measure the TOOL-SIDE latency of the admin analyst chat (RFC 0018, item 8b.3).

**Why this exists.** `infra/lib/backend-stack.ts` gives the backend Lambda a
**30 second** timeout, and `services/bedrock.py` records that RFC-0016's council
already cut `_MAX_TOOL_TURNS` from 12 to 5 to fit inside it. RFC-0018 then adds
four analyst tools whose cheapest implementation walks the WHOLE inventory
(`repo.list_inventory()` fans out across every shard partition) and, for profit,
a month-partition transaction walk. Nobody had measured what that costs against
real data, so "does an analyst question fit in 30s" was an assumption.

This script measures the half that is deterministic and that RFC-0018 actually
adds: subprocess spawn, MCP handshake, and each tool's own DynamoDB work,
through the REAL `McpToolExecutor` against the REAL table. It deliberately does
**not** call Bedrock — that half is unchanged from the shipped customer chat,
it costs money per run, and a latency figure that bills the owner every time it
is re-checked is a figure nobody re-checks.

READ-ONLY. Every tool on the admin server is `readOnlyHint=True` and this script
calls nothing else, so it is safe against production.

    cd backend && .venv/bin/python scripts/measure_admin_chat_latency.py
"""

from __future__ import annotations

import pathlib
import statistics
import sys
import time
from datetime import date, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from merlins_collection.config import settings  # noqa: E402
from merlins_collection.services.dynamodb import InventoryRepository  # noqa: E402
from merlins_collection.services.mcp_client import McpToolExecutor  # noqa: E402

REPEATS = 3


def _timed(fn):
    start = time.perf_counter()
    result = fn()
    return time.perf_counter() - start, result


def _stat(samples: list[float]) -> str:
    return (
        f"min {min(samples):6.3f}s  median {statistics.median(samples):6.3f}s  "
        f"max {max(samples):6.3f}s"
    )


def main() -> None:
    today = date.today()
    month_start = today.replace(day=1)
    year_start = today - timedelta(days=365)

    print(f"table={settings.dynamodb_table_name} region={settings.aws_region}")
    print()

    # ---- raw repository cost, no MCP transport in the way -------------------
    print("== raw repository reads (no MCP, in-process) ==")
    repo = InventoryRepository(
        settings.dynamodb_table_name, region_name=settings.aws_region
    )
    inv_samples = []
    for _ in range(REPEATS):
        elapsed, items = _timed(repo.list_inventory)
        inv_samples.append(elapsed)
    print(f"list_inventory()      {_stat(inv_samples)}   ({len(items)} items)")

    txn_month, month_rows = _timed(lambda: repo.list_transactions(month_start, today))
    txn_year, year_rows = _timed(lambda: repo.list_transactions(year_start, today))
    print(f"list_transactions 1mo {txn_month:6.3f}s   ({len(month_rows)} rows)")
    print(f"list_transactions 1yr {txn_year:6.3f}s   ({len(year_rows)} rows)")
    print()

    # ---- through the real executor -----------------------------------------
    executor = McpToolExecutor(
        [sys.executable, "-m", "merlins_collection.mcp_admin"],
        env={
            "AWS_REGION": settings.aws_region,
            "DYNAMODB_TABLE_NAME": settings.dynamodb_table_name,
        },
    )

    calls = {
        "get_profit_summary (1 month)": (
            "get_profit_summary",
            {"start": month_start.isoformat(), "end": today.isoformat()},
        ),
        "get_profit_summary (1 year)": (
            "get_profit_summary",
            {"start": year_start.isoformat(), "end": today.isoformat()},
        ),
        "find_aging_stock": ("find_aging_stock", {"min_days": 90}),
        "get_consignor_position": ("get_consignor_position", {}),
        "find_pricing_outliers": (
            "find_pricing_outliers",
            {"direction": "under", "threshold_pct": 20},
        ),
        # RFC 0020 items 2-5: the four "librarian" raw-listing tools. These
        # are the ones that actually changed the arithmetic — list_inventory
        # walks the LARGEST table in the system, so it's the one to watch.
        "list_shows": ("list_shows", {}),
        "list_transactions (1 year)": (
            "list_transactions",
            {"start": year_start.isoformat(), "end": today.isoformat()},
        ),
        "list_inventory": ("list_inventory", {}),
        "list_consignors": ("list_consignors", {}),
    }

    try:
        print("== cold path: spawn + MCP handshake + first tool call ==")
        name, (tool, args) = next(iter(calls.items()))
        cold, payload = _timed(lambda: executor(tool, args))
        print(f"cold {name:32s} {cold:6.3f}s   ({len(payload)} bytes)")
        print()

        print(f"== warm per-tool ({REPEATS} runs each) ==")
        warm: dict[str, list[float]] = {}
        for label, (tool, args) in calls.items():
            samples = []
            for _ in range(REPEATS):
                elapsed, payload = _timed(lambda: executor(tool, args))
                samples.append(elapsed)
            warm[label] = samples
            print(f"{label:32s} {_stat(samples)}   ({len(payload)} bytes)")
        print()

        # ---- the shape an analyst question actually takes -------------------
        # `_MAX_TOOL_TURNS = 5` is the ceiling, and a comparison question
        # ("how did July compare to June, and what's sitting unsold?") reaches
        # it. This is the worst case the ceiling permits, not a typical one.
        print("== worst case the OLD ceiling permits: 5 tool calls, one request ==")
        sequence = [
            ("get_profit_summary", {"start": month_start.isoformat(),
                                    "end": today.isoformat()}),
            ("get_profit_summary", {"start": year_start.isoformat(),
                                    "end": today.isoformat()}),
            ("find_aging_stock", {"min_days": 90}),
            ("find_pricing_outliers", {"direction": "under", "threshold_pct": 20}),
            ("get_consignor_position", {}),
        ]
        total, _ = _timed(
            lambda: [executor(tool, args) for tool, args in sequence]
        )
        print(f"5 sequential tool calls (warm)  {total:6.3f}s")
        print(f"  + cold spawn on the first     {cold - statistics.median(warm[name]):6.3f}s")
        print()

        # RFC 0020 item 6: the revised starting hypothesis for the ADMIN-only
        # ceilings is admin_max_tool_turns=6, admin_max_query_tool_calls=14 —
        # sized so 14 x ~1.0s (the measured worst per-tool case) leaves
        # comparable headroom to the original 5/10/3.6s design. This is the
        # arithmetic that hypothesis rests on, measured rather than assumed:
        # a 14-call sequence mixing all 8 admin MCP tools (list_inventory, the
        # largest-table walk, included twice).
        for n in (14, 12, 10):
            print(f"== candidate NEW ceiling: {n} tool calls, one request ==")
            big_sequence = [
                ("get_profit_summary", {"start": month_start.isoformat(),
                                        "end": today.isoformat()}),
                ("get_profit_summary", {"start": year_start.isoformat(),
                                        "end": today.isoformat()}),
                ("find_aging_stock", {"min_days": 90}),
                ("find_pricing_outliers", {"direction": "under", "threshold_pct": 20}),
                ("get_consignor_position", {}),
                ("list_shows", {}),
                ("list_transactions", {"start": year_start.isoformat(),
                                       "end": today.isoformat()}),
                ("list_inventory", {}),
                ("list_inventory", {"filters": ["status:eq:available"]}),
                ("list_consignors", {}),
                ("list_shows", {"include_archived": False}),
                ("find_aging_stock", {"min_days": 30}),
                ("get_profit_summary", {}),
                ("list_transactions", {"type": "sale"}),
            ][:n]
            big_total, _ = _timed(
                lambda seq=big_sequence: [executor(tool, args) for tool, args in seq]
            )
            print(f"{n} sequential tool calls (warm) {big_total:6.3f}s"
                  f"   ({big_total / 30.0:5.1%} of 30s budget)")
        print()

        # Payload size matters as much as latency: every byte returned is fed
        # back into the next Bedrock turn as tokens.
        biggest = max(
            (len(executor(tool, args)), label)
            for label, (tool, args) in calls.items()
        )
        print(f"largest tool reply: {biggest[1]} at {biggest[0]:,} bytes")
        print()
    finally:
        executor.close()

    # ---- the CONTROL: the customer server, measured identically ------------
    # The admin numbers above mean nothing on their own. The customer chat
    # already runs in production against the same 30s Lambda timeout, the same
    # model and the same `_MAX_TOOL_TURNS = 5`, so its Bedrock half is already
    # validated by having shipped. What matters is the DELTA: how much more of
    # the budget the admin tools consume than the tools that already fit.
    #
    # CLAUDE.md's own lesson from the frontend-build hang applies here — "when
    # two runs differ, the recorded cause must be a variable you actually held
    # everything else constant against". Same machine, same network, same
    # transport, same repeat count; only the server changes.
    mcp_path = (pathlib.Path(__file__).resolve().parents[2]
                / "mcp-server" / "dist" / "index.js")
    if not mcp_path.exists():
        print(f"(skipping customer control: {mcp_path} not built)")
        return

    control = McpToolExecutor(
        ["node", str(mcp_path)],
        env={
            "AWS_REGION": settings.aws_region,
            "DYNAMODB_TABLE_NAME": settings.dynamodb_table_name,
        },
    )
    customer_calls = {
        "get_inventory_summary": ("get_inventory_summary", {}),
        "search_inventory (broad)": ("search_inventory", {}),
        "calculate_inventory_value": ("calculate_inventory_value", {}),
        "flag_underpriced_cards": ("flag_underpriced_cards", {"threshold": 20}),
    }
    try:
        print("== CONTROL: customer MCP server, same machine, same method ==")
        label, (tool, args) = next(iter(customer_calls.items()))
        c_cold, payload = _timed(lambda: control(tool, args))
        print(f"cold {label:30s} {c_cold:6.3f}s   ({len(payload)} bytes)")
        c_warm: dict[str, list[float]] = {}
        for label, (tool, args) in customer_calls.items():
            samples = []
            for _ in range(REPEATS):
                elapsed, payload = _timed(lambda: control(tool, args))
                samples.append(elapsed)
            c_warm[label] = samples
            print(f"{label:32s} {_stat(samples)}   ({len(payload)} bytes)")
        worst = max(statistics.median(s) for s in c_warm.values())
        print(f"5x the slowest customer tool (warm)  {worst * 5:6.3f}s")
    finally:
        control.close()


if __name__ == "__main__":
    main()
