"""RED tests for set_display state machine (Council decision 23).

The five panel-mutation tools (open/close/add/remove/reorder) are collapsed into
one set_display(item_ids) tool:
- Empty list closes the panel
- Non-empty list replaces panel contents wholesale (in the order given)
- List >50 truncates with a notice the model must relay
- No incremental state (no more tri-state open, no more add-then-remove bugs)

This is decision 23, which dissolved Council items 7 and 8, reduced item 9, and
resolved item 10 (the 12-turn ceiling vs 30s Lambda timeout).
"""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

from merlins_collection.models.inventory import Condition, ItemStatus, RawInventoryItem
from merlins_collection.services import bedrock


def _raw(item_id: str, name: str):
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


def test_set_display_empty_list_closes_panel():
    """set_display([]) closes the panel, replacing all contents with empty."""
    items = [_raw("item-1", "Charizard"), _raw("item-2", "Pikachu")]
    repo = FakeRepo(items)
    
    client = MagicMock()
    client.converse.side_effect = [
        _tool_use("set_display", {"item_ids": []}),
        _end_turn("Panel closed."),
    ]
    
    service = _service(client, repo)
    # Start with a panel
    response = service.chat("Close the panel", panel_item_ids=["item-1", "item-2"])
    
    assert len(response["panel"].cards) == 0, "set_display([]) must clear all cards"
    # Closed = empty cards list (len == 0)


def test_set_display_replaces_panel_contents_wholesale():
    """set_display([A, B, C]) replaces the panel with exactly A, B, C in that order."""
    items = [
        _raw("item-1", "Charizard"),
        _raw("item-2", "Pikachu"),
        _raw("item-3", "Squirtle"),
        _raw("item-4", "Bulbasaur"),
    ]
    repo = FakeRepo(items)
    
    client = MagicMock()
    client.converse.side_effect = [
        _tool_use("set_display", {"item_ids": ["item-3", "item-1"]}),
        _end_turn("Panel updated."),
    ]
    
    service = _service(client, repo)
    # Start with item-1, item-2 in panel; replace with item-3, item-1
    response = service.chat("Replace panel", panel_item_ids=["item-1", "item-2"])
    
    assert len(response["panel"].cards) == 2
    assert [c.item_id for c in response["panel"].cards] == ["item-3", "item-1"]
    assert len(response["panel"].cards) > 0  # Open = non-empty cards list


def test_set_display_preserves_order():
    """The order in item_ids is the panel order (model-driven reorder)."""
    items = [_raw(f"item-{i}", f"Card {i}") for i in range(5)]
    repo = FakeRepo(items)
    
    client = MagicMock()
    client.converse.side_effect = [
        _tool_use("set_display", {"item_ids": ["item-4", "item-2", "item-0", "item-3", "item-1"]}),
        _end_turn("Reordered."),
    ]
    
    service = _service(client, repo)
    response = service.chat("Reorder cards")
    
    assert [c.item_id for c in response["panel"].cards] == [
        "item-4", "item-2", "item-0", "item-3", "item-1"
    ]


def test_set_display_truncates_at_50_and_returns_notice():
    """set_display with >50 items truncates to first 50 and returns a notice."""
    items = [_raw(f"item-{i}", f"Card {i}") for i in range(60)]
    repo = FakeRepo(items)
    
    client = MagicMock()
    client.converse.side_effect = [
        _tool_use("set_display", {"item_ids": [item.item_id for item in items]}),
        _end_turn("Panel set with 50 cards; 10 were truncated."),
    ]
    
    service = _service(client, repo)
    response = service.chat("Set 60 cards")
    
    assert len(response["panel"].cards) == 50, "Panel must cap at 50"
    assert response["panel"].truncated is True, "truncated flag must be set"
    
    # Tool result must contain a truncation notice the model can relay
    tool_result_call = client.converse.call_args_list[1]
    tool_result = tool_result_call.kwargs["messages"][2]["content"][0]
    result_text = tool_result["toolResult"]["content"][0]["text"].lower()
    
    assert "50" in result_text, "Tool result must mention the 50-card cap"
    assert "truncat" in result_text or "full" in result_text, (
        "Tool result must notify truncation so model can tell the user"
    )


def test_set_display_with_unavailable_item_skips_it():
    """set_display filters out unavailable items during hydration."""
    available = _raw("available", "Charizard")
    sold = RawInventoryItem(
        item_id="sold",
        card_id=None,
        status=ItemStatus.SOLD,
        listed_price=Decimal("10.00"),
        cost_basis=Decimal("5.00"),
        acquired_at=date.today(),
        finish="normal",
        condition=Condition.NM,
        location="glass",
    )
    repo = FakeRepo([available, sold])
    
    client = MagicMock()
    client.converse.side_effect = [
        _tool_use("set_display", {"item_ids": ["available", "sold"]}),
        _end_turn("One card is unavailable."),
    ]
    
    service = _service(client, repo)
    response = service.chat("Set panel with sold item")
    
    # Only the available item should be in the panel
    assert len(response["panel"].cards) == 1
    assert response["panel"].cards[0].item_id == "available"


def test_set_display_from_empty_opens_panel():
    """set_display with non-empty list on an initially empty panel opens it."""
    items = [_raw("item-1", "Charizard")]
    repo = FakeRepo(items)
    
    client = MagicMock()
    client.converse.side_effect = [
        _tool_use("set_display", {"item_ids": ["item-1"]}),
        _end_turn("Panel opened."),
    ]
    
    service = _service(client, repo)
    # Start with no panel (panel_item_ids not provided)
    response = service.chat("Open panel with one card")
    
    assert len(response["panel"].cards) == 1
    assert len(response["panel"].cards) > 0  # Open = non-empty cards list


def test_set_display_composes_remove_operation():
    """"Remove the Charizard" composes as set_display(current - {charizard}).
    
    This is the key use case for item 9: the model must know current panel
    contents to compose the removal as a set_display call.
    """
    items = [_raw("item-1", "Charizard"), _raw("item-2", "Pikachu"), _raw("item-3", "Squirtle")]
    repo = FakeRepo(items)
    
    client = MagicMock()
    client.converse.side_effect = [
        # Model composes: current = [item-1, item-2, item-3], remove item-1
        # -> set_display([item-2, item-3])
        _tool_use("set_display", {"item_ids": ["item-2", "item-3"]}),
        _end_turn("Removed Charizard."),
    ]
    
    service = _service(client, repo)
    response = service.chat(
        "Remove the Charizard",
        panel_item_ids=["item-1", "item-2", "item-3"]
    )
    
    assert len(response["panel"].cards) == 2
    assert [c.item_id for c in response["panel"].cards] == ["item-2", "item-3"]
    assert "item-1" not in [c.item_id for c in response["panel"].cards]


def test_max_tool_turns_stays_at_5():
    """Decision 23 resolved the turn ceiling: _MAX_TOOL_TURNS stays at 5.
    
    The tool collapse removes the need to raise it to 12. This test documents
    the reversion (Phase 1 raised it to 12, Council r1 verdict dissolved that).
    """
    assert bedrock._MAX_TOOL_TURNS == 5, (
        "_MAX_TOOL_TURNS must stay at 5 after decision 23 collapses tools. "
        "The 12-turn raise was dissolved by the Council verdict."
    )
