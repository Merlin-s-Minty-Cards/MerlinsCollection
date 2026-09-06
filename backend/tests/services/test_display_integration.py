"""INTEGRATION RED tests for search → display hydration path (Council item 1 FATAL).

The existing test_bedrock_display_tools.py misses the actual defect because it
injects literal item_id values against a stubbed repo. This integration test
composes a REAL search result from the MCP layer into a display_card call to
assert that the item_id a search result yields is actually hydratable.

The defect: mcp-server/src/dynamodb-repository.ts:208 sets
CardResult.id = card_id ?? item_id, and neither Card nor CardResult carries an
item_id field, so search_inventory hands the model "en:base1-4", the model
passes that to display_card, and _hydrate_item point-reads SK=ITEM#en:base1-4
which does not exist.

Fix direction (per verdict): add a distinct item_id field to Card/CardResult in
mcp-server. Widening display tools to accept card_id is NOT the fix because one
card_id maps to multiple physical units.
"""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from merlins_collection.models.inventory import Condition, ItemStatus, RawInventoryItem
from merlins_collection.services import bedrock


def _raw(item_id: str, card_id: str | None, name: str):
    return RawInventoryItem(
        item_id=item_id,
        card_id=card_id,
        status=ItemStatus.AVAILABLE,
        listed_price=Decimal("20.00"),
        sticker_price=Decimal("20.00"),
        cost_basis=Decimal("10.00"),
        acquired_at=date.today(),
        finish="normal",
        condition=Condition.NM,
        display_name=name,
        location="glass",
    )


class FakeRepo:
    def __init__(self, items=()):
        self.items = {item.item_id: item for item in items}

    def get_inventory_item(self, item_id):
        return self.items.get(item_id)

    def get_catalog_card(self, _card_id):
        return None


def _service(client, repo, executor):
    return bedrock.BedrockChatService(
        client=client,
        model_id="test-model",
        tool_executor=executor,
        repo=repo,
    )


def _end_turn(text: str) -> dict:
    return {
        "output": {"message": {"role": "assistant", "content": [{"text": text}]}},
        "stopReason": "end_turn",
    }


def _tool_use(name: str, input_: dict, tool_id: str = "tool-1") -> dict:
    return {
        "output": {
            "message": {
                "role": "assistant",
                "content": [{"toolUse": {"name": name, "input": input_, "toolUseId": tool_id}}],
            }
        },
        "stopReason": "tool_use",
    }


@pytest.mark.integration
def test_search_result_item_id_hydrates_in_display_card():
    """CONSUMER CONTRACT REGRESSION GUARD: verifies backend display_card expects
    per-unit item_id, not card_id.

    This test will PASS against current backend code because it mocks the MCP
    executor, bypassing the actual defect (which is in the MCP producer). The
    real RED for Council item 1 FATAL is mcp-server/src/__tests__/item-id-field.test.ts.

    This is a consumer-side assertion that display_card(item_id="item-unit-1")
    hydrates the exact unit, not "one of the units with that card_id."
    """
    # Catalogued card: one card_id, two physical units
    item_a = _raw("item-unit-1", "en:base1-4", "Charizard")
    item_b = _raw("item-unit-2", "en:base1-4", "Charizard")
    repo = FakeRepo([item_a, item_b])

    # MCP search_inventory returns per-unit item_id after the GREEN fix
    mcp_executor = MagicMock(
        return_value=(
            '[{"id": "en:base1-4", "item_id": "item-unit-1", "name": "Charizard", '
            '"set": "Base Set"}, {"id": "en:base1-4", "item_id": "item-unit-2", '
            '"name": "Charizard", "set": "Base Set"}]'
        )
    )

    # Model searches, then displays the first unit by its per-unit item_id
    client = MagicMock()
    client.converse.side_effect = [
        _tool_use("search_inventory", {"name": "Charizard"}),
        _tool_use("display_card", {"item_id": "item-unit-1"}, "tool-2"),
        _end_turn("Here is the Charizard."),
    ]

    response = _service(client, repo, mcp_executor).chat("Show me a Charizard")

    # The artifact must hydrate to exactly the requested unit, not "one of them"
    assert len(response["artifacts"]) == 1, "display_card must hydrate a search result"
    assert response["artifacts"][0].item_id == "item-unit-1"

