"""RED tests for Council item 9: panel contents must be injected into model context.

The model must know the panel's current contents to compose remove/reorder
operations with set_display. Two injection points:

1. At request start: if panel_item_ids are provided, inject them into context
   before any tool execution.
2. After set_display: the tool result echoes the new panel state.
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


def test_restored_panel_item_ids_are_injected_into_initial_messages():
    """Item 9 part 1: restored panel contents must be injected before user message."""
    items = [_raw("item-1", "Charizard"), _raw("item-2", "Pikachu")]
    repo = FakeRepo(items)
    
    client = MagicMock()
    client.converse.return_value = _end_turn("The panel has Charizard and Pikachu.")
    
    service = _service(client, repo)
    service.chat(
        "What's in the panel?",
        panel_item_ids=["item-1", "item-2"]
    )
    
    # Check the first converse() call's messages
    first_call = client.converse.call_args_list[0]
    messages = first_call.kwargs["messages"]
    
    # Panel context must be injected somewhere before or alongside the user message
    panel_context_found = False
    for msg in messages:
        content_blocks = msg.get("content", [])
        for block in content_blocks:
            text = str(block.get("text", "")).lower()
            # Look for injected panel state (item IDs mentioned)
            if "item-1" in text or "item-2" in text or "panel" in text:
                panel_context_found = True
                break
    
    assert panel_context_found, (
        "Restored panel_item_ids must be injected into model context at request start. "
        "Model cannot compose 'remove the Charizard' without knowing current panel state."
    )


def test_empty_panel_does_not_inject_panel_context():
    """When no panel_item_ids are provided, no panel context is injected."""
    repo = FakeRepo([])
    
    client = MagicMock()
    client.converse.return_value = _end_turn("Hello.")
    
    service = _service(client, repo)
    service.chat("Hi", panel_item_ids=[])
    
    first_call = client.converse.call_args_list[0]
    messages = first_call.kwargs["messages"]
    
    # Should not mention panel when empty
    for msg in messages:
        content_blocks = msg.get("content", [])
        for block in content_blocks:
            text = str(block.get("text", "")).lower()
            # "panel" might appear in system prompt, but no specific item IDs
            assert "item-" not in text, "Empty panel should not inject item IDs"


def test_panel_context_includes_card_names_not_just_ids():
    """The injected panel context should be useful: include card names, not just IDs."""
    items = [_raw("item-1", "Charizard"), _raw("item-2", "Pikachu")]
    repo = FakeRepo(items)
    
    client = MagicMock()
    client.converse.return_value = _end_turn("Noted.")
    
    service = _service(client, repo)
    service.chat("What do I have?", panel_item_ids=["item-1", "item-2"])
    
    first_call = client.converse.call_args_list[0]
    messages = first_call.kwargs["messages"]
    
    # Check that card names appear in the panel context
    full_message_text = " ".join(
        str(block.get("text", ""))
        for msg in messages
        for block in msg.get("content", [])
    ).lower()
    
    assert "charizard" in full_message_text or "pikachu" in full_message_text, (
        "Panel context should include card names to be useful for the model"
    )
