"""RED tests for Council item 6 and item 9: JSON-safe tool results.

Item 6: Tool results must use json.dumps, not f-string interpolation.
        An item_id containing a quote must yield well-formed JSON on both
        error paths and success paths.

Item 9 (reduced): set_display's tool result echoes the resulting panel contents,
        enabling cross-turn remove/reorder composition.
"""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock
import json

from merlins_collection.models.inventory import Condition, ItemStatus, RawInventoryItem
from merlins_collection.services import bedrock


def _raw(item_id: str, name: str = "Card"):
    return RawInventoryItem(
        item_id=item_id,
        card_id=None,
        status=ItemStatus.AVAILABLE,
        listed_price=Decimal("10.00"),
        sticker_price=Decimal("10.00"),
        cost_basis=Decimal("5.00"),
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


def _service(client, repo, executor=None):
    return bedrock.BedrockChatService(
        client=client,
        model_id="test-model",
        tool_executor=executor or MagicMock(return_value='{"results": []}'),
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


def test_display_card_error_escapes_quoted_item_id():
    """Item 6: display_card error with quoted item_id must produce valid JSON."""
    repo = FakeRepo([])
    
    client = MagicMock()
    malicious_id = 'item"with"quotes'
    client.converse.side_effect = [
        _tool_use("display_card", {"item_id": malicious_id}),
        _end_turn("That item is unavailable."),
    ]
    
    service = _service(client, repo)
    service.chat("Show malicious item")
    
    tool_result_call = client.converse.call_args_list[1]
    tool_result = tool_result_call.kwargs["messages"][2]["content"][0]
    result_text = tool_result["toolResult"]["content"][0]["text"]
    
    # Must parse as valid JSON
    parsed = json.loads(result_text)
    assert "error" in parsed or "status" in parsed


def test_set_display_success_escapes_quoted_item_ids_in_echo():
    """Item 6 + 9: set_display result echoes panel contents with proper JSON escaping."""
    item = _raw('item"123', "Charizard")
    repo = FakeRepo([item])
    
    client = MagicMock()
    client.converse.side_effect = [
        _tool_use("set_display", {"item_ids": [item.item_id]}),
        _end_turn("Panel updated."),
    ]
    
    service = _service(client, repo)
    service.chat("Set the panel")
    
    tool_result_call = client.converse.call_args_list[1]
    tool_result = tool_result_call.kwargs["messages"][2]["content"][0]
    result_text = tool_result["toolResult"]["content"][0]["text"]
    
    # Must parse as valid JSON
    parsed = json.loads(result_text)
    
    # Item 9: must echo the resulting panel contents
    assert "cards" in parsed or "panel" in parsed, (
        "set_display result must echo panel contents so model knows current state"
    )


def test_set_display_echoes_all_card_ids_for_remove_composition():
    """Item 9: model must receive current panel item_ids to compose removals.
    
    "Remove the Charizard" → set_display(current - {charizard_id})
    requires knowing current item_ids, not just card names.
    """
    items = [
        _raw("item-1", "Charizard"),
        _raw("item-2", "Pikachu"),
        _raw("item-3", "Squirtle"),
    ]
    repo = FakeRepo(items)
    
    client = MagicMock()
    client.converse.side_effect = [
        _tool_use("set_display", {"item_ids": [i.item_id for i in items]}),
        _end_turn("Panel set."),
    ]
    
    service = _service(client, repo)
    service.chat("Set panel")
    
    tool_result_call = client.converse.call_args_list[1]
    tool_result = tool_result_call.kwargs["messages"][2]["content"][0]
    result_text = tool_result["toolResult"]["content"][0]["text"]
    
    parsed = json.loads(result_text)
    
    # Must contain item_ids, not just names, so model can compose exact removals
    result_str = json.dumps(parsed)
    assert "item-1" in result_str and "item-2" in result_str and "item-3" in result_str, (
        "Tool result must include item_ids for all cards so model can compose remove/reorder"
    )


def test_set_display_empty_list_echoes_closed_state():
    """Item 9: set_display([]) must echo closed/empty state."""
    repo = FakeRepo([_raw("item-1", "Charizard")])
    
    client = MagicMock()
    client.converse.side_effect = [
        _tool_use("set_display", {"item_ids": []}),
        _end_turn("Panel closed."),
    ]
    
    service = _service(client, repo)
    service.chat("Close panel", panel_item_ids=["item-1"])
    
    tool_result_call = client.converse.call_args_list[1]
    tool_result = tool_result_call.kwargs["messages"][2]["content"][0]
    result_text = tool_result["toolResult"]["content"][0]["text"]
    
    parsed = json.loads(result_text)
    
    # Must indicate closed/empty
    result_lower = json.dumps(parsed).lower()
    assert "closed" in result_lower or "empty" in result_lower or parsed.get("cards") == [], (
        "set_display([]) result must indicate closed state"
    )


def test_display_card_with_backslash_in_name_produces_valid_json():
    """Edge case: display_name with backslash must also be JSON-safe."""
    item = _raw("item-1", r"Card\with\backslashes")
    repo = FakeRepo([item])
    
    client = MagicMock()
    client.converse.side_effect = [
        _tool_use("display_card", {"item_id": "item-1"}),
        _end_turn("Here it is."),
    ]
    
    service = _service(client, repo)
    service.chat("Show card")
    
    tool_result_call = client.converse.call_args_list[1]
    tool_result = tool_result_call.kwargs["messages"][2]["content"][0]
    result_text = tool_result["toolResult"]["content"][0]["text"]
    
    # Must parse without JSONDecodeError
    parsed = json.loads(result_text)
    assert parsed is not None
