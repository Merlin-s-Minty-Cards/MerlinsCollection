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
