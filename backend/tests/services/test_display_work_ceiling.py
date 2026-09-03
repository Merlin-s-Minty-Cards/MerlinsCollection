"""RED tests for Council item 11: display work ceiling and deduplication.

Admitted requests have no ceiling on internal hydration work:
- _DisplayState.__init__ does not dedupe panel_item_ids before issuing reads
  (though add_to_panel dedupes on the trusted path)
- full/duplicate check on add_to_display happens AFTER hydration reads, not before
- Single admitted request can drive up to 100 restore reads + up to 2 reads per
  tool-use block with no per-request cap

Fix: dedupe initial IDs before I/O, check full/duplicate before hydrating on add,
and cap total display-tool blocks executed per request. Extend the cap to the
artifacts array as well (currently unbounded, unlike panel.cards).
"""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from merlins_collection.models.inventory import Condition, ItemStatus, RawInventoryItem
from merlins_collection.services import bedrock


def _raw(item_id: str):
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
        location="glass",
    )


class CountingRepo:
    """Repo that counts get_inventory_item calls."""
    
    def __init__(self, items=()):
        self.items = {item.item_id: item for item in items}
        self.get_call_count = 0

    def get_inventory_item(self, item_id):
        self.get_call_count += 1
        return self.items.get(item_id)

    def get_catalog_card(self, _card_id):
        return None


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


def test_duplicate_panel_item_ids_are_deduped_before_initial_restore():
    """RED for Council item 11 part 1: _DisplayState.__init__ must dedupe
    panel_item_ids BEFORE issuing reads.
    
    Currently FAILS: 50 duplicate IDs cause 100 reads (50 on init, 50 on
    subsequent tool calls that check the panel state).
    
    A malicious or buggy client can send panel_item_ids=["item-1"]*50 and drive
    50 DynamoDB reads for the same item.
    """
    items = [_raw("item-1")]
    repo = CountingRepo(items)
    
    client = MagicMock()
    client.converse.return_value = _end_turn("Hello")
    
    service = _service(client, repo)
    
    # Send 50 duplicate IDs
    duplicate_ids = ["item-1"] * 50
    service.chat("What's up?", panel_item_ids=duplicate_ids)
    
    # Must issue only 1 read, not 50
    assert repo.get_call_count == 1, (
        f"Duplicate panel_item_ids must be deduped before reads. "
        f"Expected 1 read, got {repo.get_call_count}. "
        f"Fix: dedupe initial IDs in _DisplayState.__init__ before hydrating."
    )


def test_set_display_dedupes_input_before_hydration():
    """set_display must also dedupe its item_ids input before hydrating."""
    items = [_raw("item-1")]
    repo = CountingRepo(items)
    
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
                                "input": {"item_ids": ["item-1"] * 20},
                                "toolUseId": "tool-1",
                            }
                        }
                    ],
                }
            },
            "stopReason": "tool_use",
        },
        _end_turn("Done."),
    ]
    
    service = _service(client, repo)
    service.chat("Set panel with duplicates")
    
    # Must hydrate item-1 only once, not 20 times
    assert repo.get_call_count == 1, (
        f"set_display must dedupe item_ids before hydration. "
        f"Expected 1 read, got {repo.get_call_count}."
    )


def test_set_display_checks_cap_before_hydrating():
    """set_display must check the 50-card cap BEFORE hydrating all items.
    
    Currently the full/duplicate check happens AFTER hydration. A client can send
    100 item_ids and drive 100 reads even though only 50 can be added.
    
    Fix: check length and dedupe first, then hydrate only up to the cap.
    """
    items = [_raw(f"item-{i}") for i in range(100)]
    repo = CountingRepo(items)
    
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
                                "input": {"item_ids": [item.item_id for item in items]},
                                "toolUseId": "tool-1",
                            }
                        }
                    ],
                }
            },
            "stopReason": "tool_use",
        },
        _end_turn("Panel set with 50 cards, 50 truncated."),
    ]
    
    service = _service(client, repo)
    response = service.chat("Set panel with 100 cards")
    
    # Must hydrate at most 50 items, not all 100
    assert repo.get_call_count <= 50, (
        f"set_display must cap hydration to 50 items. "
        f"Expected ≤50 reads, got {repo.get_call_count}. "
        f"Fix: truncate to 50 BEFORE hydrating."
    )
    
    assert len(response["panel"].cards) == 50
    assert response["panel"].truncated is True


def test_artifacts_array_is_bounded():
    """Inline artifacts (display_card) must also have a cap, not just panel.cards.
    
    Currently artifacts is unbounded. A model that calls display_card 100 times
    in one conversation produces a 100-card artifacts array.
    
    Fix: cap artifacts at some reasonable limit (50? 100?) and truncate with a flag.
    """
    items = [_raw(f"item-{i}") for i in range(100)]
    repo = FakeRepo(items)
    
    client = MagicMock()
    tool_calls = [
        {
            "toolUse": {
                "name": "display_card",
                "input": {"item_id": item.item_id},
                "toolUseId": f"tool-{i}",
            }
        }
        for i, item in enumerate(items)
    ]
    client.converse.side_effect = [
        {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": tool_calls,
                }
            },
            "stopReason": "tool_use",
        },
        _end_turn("Displayed 100 cards inline."),
    ]
    
    service = _service(client, repo)
    response = service.chat("Show me 100 cards inline")
    
    # artifacts must be bounded to prevent unbounded response growth
    max_artifacts = 50  # or 100, implementation-defined
    assert len(response["artifacts"]) <= max_artifacts, (
        f"artifacts array must be capped to prevent unbounded growth. "
        f"Expected ≤{max_artifacts}, got {len(response['artifacts'])}. "
        f"Fix: cap artifacts and add a truncation flag."
    )


def test_total_display_tool_blocks_per_request_is_capped():
    """A single request must cap the total number of display-tool blocks executed.
    
    Currently there is no per-request ceiling. A model that does:
    - search_inventory (1 MCP call)
    - display_card × 10 (10 hydrations)
    - set_display with 50 IDs (50 hydrations)
    
    drives 61 operations in one request, with no bound.
    
    Fix: count display-tool invocations and stop at some ceiling (e.g., 20 total
    display blocks per request). This is separate from _MAX_TOOL_TURNS.
    """
    items = [_raw(f"item-{i}") for i in range(60)]
    repo = CountingRepo(items)
    
    client = MagicMock()
    
    # Model does 60 display_card calls in one turn
    tool_calls = [
        {
            "toolUse": {
                "name": "display_card",
                "input": {"item_id": item.item_id},
                "toolUseId": f"tool-{i}",
            }
        }
        for i, item in enumerate(items)
    ]
    client.converse.side_effect = [
        {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": tool_calls,
                }
            },
            "stopReason": "tool_use",
        },
        _end_turn("Displayed many cards."),
    ]
    
    service = _service(client, repo)
    response = service.chat("Show me 60 cards")
    
    # The request must not hydrate all 60; it should stop at some ceiling
    max_display_blocks = 20  # or some other reasonable limit
    assert repo.get_call_count <= max_display_blocks, (
        f"Total display-tool blocks per request must be capped. "
        f"Expected ≤{max_display_blocks} hydrations, got {repo.get_call_count}. "
        f"Fix: count display-tool invocations and stop at ceiling."
    )
    
    # The response should indicate that some blocks were not executed
    # (exact mechanism TBD: maybe last tool result says "too many display operations")
