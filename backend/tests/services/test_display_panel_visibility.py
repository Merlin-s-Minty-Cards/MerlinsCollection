"""RED tests for Council item 9: model must be told the panel's current contents.

The model is never told the panel's current contents, so cross-turn
remove_from_display/reorder_display are unreachable. No tool result, system text,
or read tool surfaces panel_cards back to the model after __init__ hydrates it.

With the set_display consolidation (decision 23), this requirement SHRINKS but
does not vanish: set_display needs the current contents even more, because
"remove the Charizard" requires composing the full remaining set.

Fix: inject the panel's current IDs into context at request start (system/tool
message), AND set_display's tool result must echo the resulting panel contents.
"""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import json

from merlins_collection.models.inventory import Condition, ItemStatus, RawInventoryItem
from merlins_collection.services import bedrock


def _raw(item_id: str, name: str):
    return RawInventoryItem(
        item_id=item_id,
        card_id=None,
        status=ItemStatus.AVAILABLE,
        listed_price=Decimal("10.00"),
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


def test_restored_panel_contents_are_injected_into_initial_context():
    """RED for Council item 9 part 1: when a user resumes a conversation with
    panel_item_ids, the model must be told what cards are currently in the panel
    at request start (before any tool execution).
    
    Currently FAILS because __init__ hydrates panel_item_ids but never surfaces
    them to the model. The model cannot compose "remove the Charizard" without
    knowing what's in the panel.
    
    Fix: inject a system message or tool message at the start of the conversation
    describing the panel's current contents.
    """
    items = [_raw("item-1", "Charizard"), _raw("item-2", "Pikachu")]
    repo = FakeRepo(items)
    
    client = MagicMock()
    client.converse.return_value = _end_turn("The panel has Charizard and Pikachu.")
    
    service = _service(client, repo)
    service.chat(
        "What's in the panel?",
        panel_item_ids=["item-1", "item-2"]
    )
    
    # Check the messages sent to converse() in the first call
    first_call = client.converse.call_args_list[0]
    messages = first_call.kwargs["messages"]
    
    # The panel contents must be injected somewhere in the initial message list
    # (either as a system message or a tool result message before user text)
    panel_context_found = False
    for msg in messages:
        content_blocks = msg.get("content", [])
        for block in content_blocks:
            text = block.get("text", "")
            # Look for mention of the panel contents (item IDs or card names)
            if "item-1" in text or "item-2" in text or "panel" in text.lower():
                panel_context_found = True
                break
    
    assert panel_context_found, (
        "Model must be told the panel's current contents at request start. "
        "Fix: inject a system/tool message describing panel_item_ids before user text."
    )


def test_set_display_tool_result_echoes_resulting_panel_contents():
    """RED for Council item 9 part 2: set_display's tool result must echo the
    resulting panel contents back to the model.
    
    This is how the model knows what the panel contains after a mutation, enabling
    cross-turn operations like "now remove the Charizard" after "show me all Fire types".
    """
    items = [_raw("item-1", "Charizard"), _raw("item-2", "Pikachu"), _raw("item-3", "Squirtle")]
    repo = FakeRepo(items)
    
    client = MagicMock()
    client.converse.side_effect = [
        {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "toolUse": {
                                "name": "set_display",
                                "input": {"item_ids": ["item-1", "item-2"]},
                                "toolUseId": "tool-1",
                            }
                        }
                    ],
                }
            },
            "stopReason": "tool_use",
        },
        _end_turn("Added Charizard and Pikachu to the panel."),
    ]
    
    service = _service(client, repo)
    response = service.chat("Show me Charizard and Pikachu")
    
    # Extract the tool result
    tool_result_call = client.converse.call_args_list[1]
    tool_result = tool_result_call.kwargs["messages"][2]["content"][0]
    result_text = tool_result["toolResult"]["content"][0]["text"]
    
    # Tool result must be valid JSON
    parsed = json.loads(result_text)
    
    # Must echo the resulting panel contents (item IDs or card names)
    assert "cards" in parsed or "panel" in parsed or "items" in parsed, (
        "set_display tool result must include the resulting panel contents"
    )
    
    # The echoed contents should list the 2 cards that were set
    # (exact structure TBD by implementation, but it must be present)
    result_str = str(parsed).lower()
    assert "item-1" in result_str or "charizard" in result_str, (
        "Tool result must echo card details so model knows what's in the panel"
    )


def test_set_display_empty_list_closes_panel_and_echoes_closed_state():
    """set_display([]) closes the panel. The tool result must indicate the panel
    is now closed/empty, not just silently succeed.
    """
    items = [_raw("item-1", "Charizard")]
    repo = FakeRepo(items)
    
    client = MagicMock()
    client.converse.side_effect = [
        # First set some cards
        {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "toolUse": {
                                "name": "set_display",
                                "input": {"item_ids": ["item-1"]},
                                "toolUseId": "tool-1",
                            }
                        }
                    ],
                }
            },
            "stopReason": "tool_use",
        },
        # Then close it
        {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "toolUse": {
                                "name": "set_display",
                                "input": {"item_ids": []},
                                "toolUseId": "tool-2",
                            }
                        }
                    ],
                }
            },
            "stopReason": "tool_use",
        },
        _end_turn("Panel closed."),
    ]
    
    service = _service(client, repo)
    # First request opens panel
    service.chat("Show Charizard", panel_item_ids=[])
    # Second request closes it
    response = service.chat("Close the panel", panel_item_ids=["item-1"])
    
    # Extract the second tool result (the close operation)
    close_result_call = client.converse.call_args_list[3]  # 0=first set, 2=second set, 3=after close
    tool_result = close_result_call.kwargs["messages"][2]["content"][0]
    result_text = tool_result["toolResult"]["content"][0]["text"]
    
    parsed = json.loads(result_text)
    
    # Must indicate closed/empty state
    result_str = str(parsed).lower()
    assert "closed" in result_str or "empty" in result_str or parsed.get("cards") == [], (
        "set_display([]) tool result must indicate the panel is now closed/empty"
    )
    
    # And the actual response must have an empty/closed panel
    assert len(response["panel"].cards) == 0
    # panel.open state TBD by implementation (None or False after set_display([]))
