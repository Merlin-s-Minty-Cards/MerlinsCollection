"""RED tests for backend-only display tool execution inside the Bedrock loop."""

import inspect
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

from merlins_collection.models.inventory import Condition, ItemStatus, RawInventoryItem
from merlins_collection.services import bedrock


def _end_turn(text: str) -> dict:
    return {
        "output": {"message": {"role": "assistant", "content": [{"text": text}]}},
        "stopReason": "end_turn",
    }


def _tool_use(name: str, input_: dict, tool_id: str = "tool-1") -> dict:
    return _tool_use_many([(name, input_, tool_id)])


def _tool_use_many(calls: list[tuple[str, dict, str]]) -> dict:
    return {
        "output": {
            "message": {
                "role": "assistant",
                "content": [
                    {"toolUse": {"name": name, "input": input_, "toolUseId": tool_id}}
                    for name, input_, tool_id in calls
                ],
            }
        },
        "stopReason": "tool_use",
    }


class FakeRepo:
    def __init__(self, items=()):
        self.items = {item.item_id: item for item in items}

    def get_inventory_item(self, item_id):
        return self.items.get(item_id)

    def get_catalog_card(self, _card_id):
        return None


def _raw(item_id: str, *, status=ItemStatus.AVAILABLE, value="25.00"):
    return RawInventoryItem(
        item_id=item_id,
        card_id=None,
        status=status,
        listed_price=Decimal("20.00"),
        current_market_value=Decimal(value),
        sticker_price=Decimal("20.00"),
        cost_basis=Decimal("10.00"),
        acquired_at=date.today(),
        finish="normal",
        condition=Condition.NM,
        display_name=f"Card {item_id}",
        # Council item 2: hydration requires a display-ready location. These
        # fixtures represent customer-visible stock; withheld cases are explicit.
        location="glass",
    )


def _service(client, repo, executor=None):
    assert "repo" in inspect.signature(bedrock.BedrockChatService).parameters, (
        "RFC 0016 repository injection is not implemented"
    )
    return bedrock.BedrockChatService(
        client=client,
        model_id="test-model",
        tool_executor=executor or MagicMock(return_value='{"results": []}'),
        repo=repo,
    )


def test_display_card_hydrates_item_into_inline_artifacts():
    item = _raw("item-1")
    client = MagicMock()
    client.converse.side_effect = [
        _tool_use("display_card", {"item_id": item.item_id}),
        _end_turn("Here it is."),
    ]
    response = _service(client, FakeRepo([item])).chat("Show one card")
    assert response["reply"] == "Here it is."
    assert [card.item_id for card in response["artifacts"]] == ["item-1"]
    # Inline display must not populate the panel. Closed = empty cards (decision 23
    # removed the tri-state `open` field; open/closed is inferred from len(cards)).
    assert response["panel"].cards == []


def test_display_card_unknown_item_returns_error_without_calling_mcp():
    executor = MagicMock()
    client = MagicMock()
    client.converse.side_effect = [
        _tool_use("display_card", {"item_id": "missing"}),
        _end_turn("That item is unavailable."),
    ]
    _service(client, FakeRepo(), executor).chat("Show it")
    executor.assert_not_called()
    result = client.converse.call_args_list[1].kwargs["messages"][2]["content"][0]
    assert "not found" in result["toolResult"]["content"][0]["text"].lower()


def test_display_card_sold_item_returns_error_without_crashing():
    sold = _raw("sold-1", status=ItemStatus.SOLD)
    client = MagicMock()
    client.converse.side_effect = [
        _tool_use("display_card", {"item_id": sold.item_id}),
        _end_turn("It is no longer available."),
    ]
    response = _service(client, FakeRepo([sold])).chat("Show sold card")
    assert response["artifacts"] == []
    result = client.converse.call_args_list[1].kwargs["messages"][2]["content"][0]
    assert "unavailable" in result["toolResult"]["content"][0]["text"].lower()


def test_set_display_hydrates_items_and_opens_panel():
    """set_display replaces the five removed tools (add/remove/reorder/open/close)."""
    items = [_raw("item-1"), _raw("item-2")]
    client = MagicMock()
    client.converse.side_effect = [
        _tool_use("set_display", {"item_ids": [item.item_id for item in items]}),
        _end_turn("Panel set with 2 cards."),
    ]
    response = _service(client, FakeRepo(items)).chat("Set the panel")
    assert len(response["panel"].cards) > 0  # Open = non-empty cards list
    assert [card.item_id for card in response["panel"].cards] == ["item-1", "item-2"]


def test_set_display_unknown_item_filters_out():
    """set_display with unknown items filters them out during hydration."""
    item = _raw("item-1")
    client = MagicMock()
    client.converse.side_effect = [
        _tool_use("set_display", {"item_ids": ["item-1", "missing"]}),
        _end_turn("One item was unavailable."),
    ]
    response = _service(client, FakeRepo([item])).chat("Set panel")
    assert [card.item_id for card in response["panel"].cards] == ["item-1"]


def test_panel_caps_at_50_and_tool_result_contains_truncation_notice():
    items = [_raw(f"item-{i}") for i in range(51)]
    client = MagicMock()
    client.converse.side_effect = [
        _tool_use("set_display", {"item_ids": [item.item_id for item in items]}),
        _end_turn("The panel is limited to 50 cards; one result was not shown."),
    ]
    response = _service(client, FakeRepo(items)).chat("Show all 51")
    assert len(response["panel"].cards) == 50
    assert response["panel"].truncated is True
    assert "50" in response["reply"]
    tool_results = client.converse.call_args_list[1].kwargs["messages"][2]["content"]
    assert "full" in tool_results[0]["toolResult"]["content"][0]["text"].lower() or \
           "truncat" in tool_results[0]["toolResult"]["content"][0]["text"].lower()


def test_query_tools_still_delegate_to_mcp_executor():
    executor = MagicMock(return_value='[{"item_id": "item-1"}]')
    client = MagicMock()
    client.converse.side_effect = [
        _tool_use("search_inventory", {"name": "Charizard"}),
        _end_turn("Found one."),
    ]
    _service(client, FakeRepo(), executor).chat("Find Charizard")
    executor.assert_called_once_with("search_inventory", {"name": "Charizard"})


def test_display_tool_result_keeps_bedrock_tool_result_envelope():
    item = _raw("item-1")
    client = MagicMock()
    client.converse.side_effect = [
        _tool_use("display_card", {"item_id": item.item_id}, "display-123"),
        _end_turn("Done."),
    ]
    _service(client, FakeRepo([item])).chat("Show it")
    block = client.converse.call_args_list[1].kwargs["messages"][2]["content"][0]
    assert block["toolResult"]["toolUseId"] == "display-123"
    assert isinstance(block["toolResult"]["content"][0]["text"], str)


def test_round_tripped_panel_ids_are_rehydrated_live_each_request():
    item = _raw("item-1", value="25.00")
    repo = FakeRepo([item])
    first_client = MagicMock()
    first_client.converse.return_value = _end_turn("First turn")
    first = _service(first_client, repo).chat("What is open?", panel_item_ids=[item.item_id])
    assert first["panel"].cards[0].current_market_value == Decimal("25.00")

    repo.items[item.item_id] = item.model_copy(
        update={"current_market_value": Decimal("40.00")}
    )
    second_client = MagicMock()
    second_client.converse.return_value = _end_turn("Second turn")
    second = _service(second_client, repo).chat("What about now?", panel_item_ids=[item.item_id])
    assert second["panel"].cards[0].current_market_value == Decimal("40.00")


def test_model_tool_schema_cannot_request_fullscreen():
    names_and_properties = {
        tool["toolSpec"]["name"]: set(
            tool["toolSpec"]["inputSchema"]["json"].get("properties", {})
        )
        for tool in bedrock._TOOLS
    }
    display_names = {"display_card", "set_display"}
    assert display_names <= names_and_properties.keys()
    assert all("fullscreen" not in names_and_properties[name] for name in display_names)


def test_display_sequences_stay_at_five_tool_turn_budget():
    """Decision 23 resolved the turn ceiling: stays at 5 (Phase 1 raised to 12)."""
    assert bedrock._MAX_TOOL_TURNS == 5
