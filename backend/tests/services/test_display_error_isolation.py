"""RED tests for Council item 4: hydration/restore error isolation.

Unhandled ClientError and ValidationError during hydration crash a route
documented as fail-closed (503). _hydrate_item and the initial panel_item_ids
restore loop catch neither; both escape as an untyped 500.

A throttle on card 37 of 50 aborts a request that already paid for earlier reads
and, if mid-conversation, earlier converse() calls. Fix: bound and isolate
restore failures — catch repository errors per item, report partial restoration
rather than failing the whole request.
"""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

from botocore.exceptions import ClientError
from pydantic import ValidationError

from merlins_collection.models.inventory import Condition, ItemStatus, RawInventoryItem
from merlins_collection.services import bedrock


def _raw(item_id: str):
    return RawInventoryItem(
        item_id=item_id,
        card_id=None,
        status=ItemStatus.AVAILABLE,
        listed_price=Decimal("10.00"),
        cost_basis=Decimal("5.00"),
        acquired_at=date.today(),
        finish="normal",
        condition=Condition.NM,
        location="glass",
    )


class ThrottlingRepo:
    """Repo that throws ClientError after a few successful reads."""
    
    def __init__(self, items, fail_after=2):
        self.items = {item.item_id: item for item in items}
        self.call_count = 0
        self.fail_after = fail_after

    def get_inventory_item(self, item_id):
        self.call_count += 1
        if self.call_count > self.fail_after:
            # DynamoDB throttling exception
            raise ClientError(
                {
                    "Error": {
                        "Code": "ProvisionedThroughputExceededException",
                        "Message": "Rate exceeded",
                    }
                },
                "GetItem",
            )
        return self.items.get(item_id)

    def get_catalog_card(self, _card_id):
        return None


class CorruptRepo:
    """Repo that returns data causing ValidationError during hydration."""
    
    def __init__(self):
        self.items = {}

    def get_inventory_item(self, item_id):
        # Return a dict that will fail pydantic validation
        return {"item_id": item_id, "invalid_field_causes_validation_error": True}

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


def test_throttled_panel_restore_reports_partial_success_not_500():
    """RED for Council item 4: ClientError during initial panel restore must
    be caught per item and report partial restoration, not crash the request.
    
    Scenario: user has 5 cards in panel, DynamoDB throttles after reading 2.
    Currently FAILS: unhandled ClientError escapes as 500.
    Must: catch the error, restore the 2 that succeeded, and return a response
    with partial panel state.
    """
    items = [_raw(f"item-{i}") for i in range(5)]
    repo = ThrottlingRepo(items, fail_after=2)
    
    client = MagicMock()
    client.converse.return_value = _end_turn("Hello")
    
    # User sends panel_item_ids with 5 items; only 2 hydrate before throttle
    service = _service(client, repo)
    
    # This must NOT raise an exception
    response = service.chat(
        "What's in the panel?",
        panel_item_ids=[item.item_id for item in items]
    )
    
    # Response must succeed with partial restoration
    assert "reply" in response, "Request must not crash with 500"
    assert len(response["panel"].cards) == 2, (
        "Must restore the 2 cards that succeeded before throttle"
    )
    # Panel should indicate partial restoration (e.g., truncated flag or a notice)
    # The exact mechanism is implementation-defined, but the request must NOT crash


def test_validation_error_during_hydration_does_not_crash_request():
    """ValidationError during _hydrate_item (corrupt data) must be caught and
    treated as a failed hydration for that item, not abort the entire request.
    """
    repo = CorruptRepo()
    
    client = MagicMock()
    client.converse.return_value = _end_turn("Hello")
    
    service = _service(client, repo)
    
    # This must NOT raise ValidationError
    response = service.chat(
        "What's up?",
        panel_item_ids=["corrupt-1", "corrupt-2"]
    )
    
    assert "reply" in response, "Validation errors must not crash the request"
    # Both items fail validation, so panel should be empty or report errors
    assert len(response["panel"].cards) == 0


def test_display_card_tool_catches_client_error_and_returns_tool_error():
    """ClientError during display_card tool execution must be caught and returned
    as a tool error result, not escape as 500.
    """
    repo = ThrottlingRepo([], fail_after=0)  # Fail immediately
    
    client = MagicMock()
    client.converse.side_effect = [
        {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "toolUse": {
                                "name": "display_card",
                                "input": {"item_id": "throttled"},
                                "toolUseId": "tool-1",
                            }
                        }
                    ],
                }
            },
            "stopReason": "tool_use",
        },
        _end_turn("That item is unavailable."),
    ]
    
    service = _service(client, repo)
    response = service.chat("Show me a card")
    
    # Request must succeed with an error tool result, not crash
    assert "reply" in response
    assert response["artifacts"] == []
    
    # Tool result must indicate an error
    tool_result_call = client.converse.call_args_list[1]
    tool_result = tool_result_call.kwargs["messages"][2]["content"][0]
    assert "toolResult" in tool_result
    # Should contain an error message about throttling or unavailability


def test_set_display_with_50_cards_throttled_on_hydration_does_not_crash():
    """Hydration error during set_display must not crash the request.
    
    This is a boundary case for error isolation: set_display([50 items]) where
    some fail to hydrate mid-list.
    """
    items = [_raw(f"item-{i}") for i in range(50)]
    repo = ThrottlingRepo(items, fail_after=30)
    
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
        _end_turn("Panel set with partial results."),
    ]
    
    service = _service(client, repo)
    response = service.chat("Set 50 cards")
    
    assert "reply" in response
    # Must have hydrated the first 30 that succeeded before throttle
    assert len(response["panel"].cards) <= 30
