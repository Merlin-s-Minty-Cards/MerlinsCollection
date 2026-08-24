"""Pins the Bedrock tool schemas to the shared contract file.

shared/tool-contract.json is the single source of truth for the tool contract
between the backend (what the model sees) and the MCP server (what executes).
The mcp-server test suite pins its side against the same file.
"""

import json
from pathlib import Path

CONTRACT_PATH = Path(__file__).resolve().parents[2] / "shared" / "tool-contract.json"


def _contract_tools() -> list[dict]:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))["tools"]


def test_bedrock_tools_match_shared_contract():
    from merlins_collection.services.bedrock import _TOOLS

    specs = {t["toolSpec"]["name"]: t["toolSpec"] for t in _TOOLS}
    contract = {t["name"]: t for t in _contract_tools()}

    assert set(specs) == set(contract), "tool names diverge from shared/tool-contract.json"
    for name, tool in contract.items():
        schema = specs[name]["inputSchema"]["json"]
        assert sorted(schema.get("properties", {})) == sorted(tool["properties"]), name
        assert sorted(schema.get("required", [])) == sorted(tool["required"]), name


def test_shared_contract_has_seven_tools_after_decision_23():
    """Contract sync: decision 23 collapsed display tools to 7 total.
    
    Five query tools (MCP-registered) + two display tools (backend-only):
    display_card and set_display. The five incremental panel-mutation tools
    (open/close/add/remove/reorder) are removed.
    """
    tools = _contract_tools()
    names = [tool["name"] for tool in tools]

    assert len(names) == 7, (
        f"Contract must have 7 tools (5 query + 2 display), got {len(names)}. "
        f"Decision 23 collapsed display tools. See council/r1/verdict.md."
    )
    assert names[:5] == [
        "search_inventory",
        "get_inventory_summary",
        "get_card_price_history",
        "calculate_inventory_value",
        "flag_underpriced_cards",
    ], "First 5 tools must be the query tools (unchanged)"
    
    assert names[5:] == [
        "display_card",
        "set_display",
    ], (
        f"Last 2 tools must be display_card and set_display, got {names[5:]}. "
        f"open/close/add/remove/reorder are removed per decision 23."
    )
