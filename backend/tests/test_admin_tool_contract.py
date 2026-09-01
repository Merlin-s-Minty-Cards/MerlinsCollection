"""Pins the admin MCP server to the packaged admin-tool-contract.json (RFC 0018).

Mirrors test_tool_contract.py's role for the customer surface. Two properties
matter here and neither is cosmetic:

1. the server implements EXACTLY the contract — no more (a tool nobody
   declared), no fewer (a contract advertising something that does not run);
2. every tool is read-only, which is owner decision 1 and the reason this
   server has no write path to mis-fire.
"""

import asyncio
import json
from datetime import date
from pathlib import Path

from merlins_collection.mcp_admin.server import build_server

CONTRACT_PATH = (
    Path(__file__).resolve().parents[1] / "src" / "merlins_collection"
    / "admin-tool-contract.json"
)


def _contract_tools() -> list[dict]:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))["tools"]


def _server_tools(dynamo_repo):
    return asyncio.run(build_server(dynamo_repo).list_tools())


def test_the_server_implements_exactly_the_contract(dynamo_repo):
    declared = {t["name"] for t in _contract_tools()}
    implemented = {t.name for t in _server_tools(dynamo_repo)}
    assert implemented == declared, (
        "admin server and the packaged admin-tool-contract.json disagree; "
        f"only in contract={declared - implemented}, "
        f"only in server={implemented - declared}"
    )


def test_each_tool_takes_exactly_the_arguments_the_contract_declares(dynamo_repo):
    contract = {t["name"]: t for t in _contract_tools()}
    for tool in _server_tools(dynamo_repo):
        schema = tool.inputSchema
        assert sorted(schema.get("properties", {})) == sorted(
            contract[tool.name]["properties"]
        ), tool.name
        assert sorted(schema.get("required", [])) == sorted(
            contract[tool.name]["required"]
        ), tool.name


def test_every_admin_tool_is_read_only(dynamo_repo):
    """Owner decision 1. Asserted, not merely intended.

    A read-only server cannot be talked into a write by a prompt-injected card
    name, which is why the RFC's prompt-injection risk row can say the worst
    case is disclosure to an already-authorised admin rather than mutation.
    """
    for tool in _server_tools(dynamo_repo):
        assert tool.annotations is not None, f"{tool.name} declares no annotations"
        assert tool.annotations.readOnlyHint is True, f"{tool.name} is not read-only"


def test_get_profit_summary_accepts_no_arguments_at_all_for_all_time(dynamo_repo):
    """The wired-up tool, called the way the model calls it for "all time".

    A schema-level test (`test_admin_tool_schemas.py`) pins that the model is
    TOLD `start`/`end` are optional; this proves the actual tool the server
    executes does not crash when they are left out, all the way through
    `date.fromisoformat(None)` (which would raise `TypeError`).
    """
    server = build_server(dynamo_repo)
    content, extra = asyncio.run(server.call_tool("get_profit_summary", {}))
    payload = json.loads(extra["result"])
    assert "gross_sales" in payload


def test_list_shows_accepts_no_arguments_and_returns_the_wired_up_shape(dynamo_repo):
    """The wired-up list_shows tool, called with no arguments at all."""
    from merlins_collection.models.business import Show

    dynamo_repo.put_show(Show(show_id="s1", name="Test Show", date=date(2026, 3, 14)))

    server = build_server(dynamo_repo)
    content, extra = asyncio.run(server.call_tool("list_shows", {}))
    payload = json.loads(extra["result"])

    assert payload == [{
        "show_id": "s1", "name": "Test Show", "date": "2026-03-14",
        "venue": None, "city": None, "archived": False,
        "has_analytics": False, "stale": False,
        "gross_sales": None, "total_purchases": None, "net_sales": None,
        "items_sold_count": None, "items_bought_count": None, "trades_count": None,
    }]


def test_list_transactions_accepts_no_arguments_and_returns_the_wired_up_shape(
    dynamo_repo,
):
    """The wired-up list_transactions tool, called with no arguments at all —
    proves the whole ISO-string-to-date, default-window and sort-validation
    path runs end to end through the actual MCP tool boundary, not just the
    service function directly.
    """
    from decimal import Decimal

    from merlins_collection.models.business import (
        ItemCategory,
        Transaction,
        TransactionType,
    )

    dynamo_repo.put_transaction(
        Transaction(
            txn_id="t1",
            type=TransactionType.SALE,
            item_id="item-1",
            category=ItemCategory.RAW,
            date=date(2026, 3, 14),
            amount=Decimal("45.00"),
            payment_method="cash",
        )
    )

    server = build_server(dynamo_repo)
    content, extra = asyncio.run(server.call_tool("list_transactions", {}))
    payload = json.loads(extra["result"])

    assert payload["total_matched"] == 1
    [row] = payload["items"]
    assert row["txn_id"] == "t1"
    assert row["amount"] == "45.00"
    assert row["is_countable"] is True
    assert row["is_trade_cash_leg"] is False


def test_list_inventory_accepts_no_arguments_and_returns_the_wired_up_shape(
    dynamo_repo,
):
    """The wired-up list_inventory tool, called with no arguments at all —
    proves the filter/sort validation and the model_dump-plus-name shape run
    end to end through the actual MCP tool boundary, not just the service
    function directly.
    """
    from decimal import Decimal

    from merlins_collection.models.inventory import Condition, RawInventoryItem

    dynamo_repo.put_inventory_item(
        RawInventoryItem(
            item_id="i1",
            card_id="en:base1-4",
            display_name="Charizard",
            cost_basis=Decimal("120.00"),
            acquired_at=date(2026, 3, 14),
            finish="normal",
            condition=Condition.NM,
        )
    )

    server = build_server(dynamo_repo)
    content, extra = asyncio.run(server.call_tool("list_inventory", {}))
    payload = json.loads(extra["result"])

    assert payload["total_matched"] == 1
    [row] = payload["items"]
    assert row["item_id"] == "i1"
    assert row["cost_basis"] == "120.00"
    assert row["name"] == "Charizard"


def test_list_consignors_accepts_no_arguments_and_returns_the_wired_up_shape(
    dynamo_repo,
):
    """The wired-up list_consignors tool, called with no arguments at all."""
    from merlins_collection.models.business import Consignor

    dynamo_repo.put_consignor(Consignor(consignor_id="c1", name="Alice"))

    server = build_server(dynamo_repo)
    content, extra = asyncio.run(server.call_tool("list_consignors", {}))
    payload = json.loads(extra["result"])

    assert payload == [{
        "consignor_id": "c1", "name": "Alice", "contact": None,
        "email": None, "phone": None, "payout_percent": "50",
        "archived": False, "notes": None,
    }]


def test_the_customer_server_is_never_handed_an_admin_tool():
    """The structural half of decision 6, pinned.

    The customer contract and the admin contract must not overlap. If a name
    ever appears in both, the customer Bedrock loop can name it — and the whole
    reason this is a separate process rather than an `isAdmin` branch is that
    the boundary should not depend on a runtime check.
    """
    # The CUSTOMER contract stays in shared/: `mcp-server/` (TypeScript)
    # reads it, which is what shared/ is for. Only the admin contract moved
    # into the package, because nothing outside the backend reads it.
    customer_path = (
        Path(__file__).resolve().parents[2] / "shared" / "tool-contract.json"
    )
    customer = {
        t["name"] for t in json.loads(customer_path.read_text(encoding="utf-8"))["tools"]
    }
    admin = {t["name"] for t in _contract_tools()}
    assert customer.isdisjoint(admin), f"tool names on both surfaces: {customer & admin}"
