"""RED tests for Council items 5 and 6: security issues in display hydration.

Item 5: cert_image_url (admin-scoped, provider-supplied, scheme-validated only)
        is shipped on the customer-facing /chat wire. Must be dropped.

Item 6: Unescaped string interpolation builds hand-rolled "JSON" tool results
        from model/client-influenced text. f-string interpolation of item_id into
        a literal that re-enters the model's context framed as JSON; an item_id
        containing a quote produces malformed structured input.
"""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from merlins_collection.models.inventory import GradedInventoryItem, ItemStatus
from merlins_collection.services import bedrock


def _graded(item_id: str, cert_image_url: str | None = None):
    return GradedInventoryItem(
        item_id=item_id,
        card_id="en:test-1",
        status=ItemStatus.AVAILABLE,
        listed_price=Decimal("500.00"),
        cost_basis=Decimal("300.00"),
        acquired_at=date.today(),
        cert_number="12345678",
        grader="PSA",
        grade="10",
        location="glass",
        cert_image_url=cert_image_url,
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


# ---- Council item 5: cert_image_url must not reach /chat wire ----


def test_cert_image_url_is_not_included_in_displayed_card():
    """RED for Council item 5: cert_image_url is admin-scoped and provider-supplied
    (scheme-validated only, not content-validated). It must NOT appear on the
    customer-facing DisplayedCard wire schema.
    
    Currently FAILS because the same projection code is used for admin and customer,
    and cert_image_url is not explicitly filtered out.
    """
    item = _graded("graded-1", cert_image_url="https://provider.example/cert/12345678.jpg")
    repo = FakeRepo([item])
    
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
                                "input": {"item_id": item.item_id},
                                "toolUseId": "tool-1",
                            }
                        }
                    ],
                }
            },
            "stopReason": "tool_use",
        },
        _end_turn("Here it is."),
    ]
    
    service = _service(client, repo)
    response = service.chat("Show me the graded card")
    
    assert len(response["artifacts"]) == 1
    displayed = response["artifacts"][0]
    
    # cert_image_url must NOT be present on the DisplayedCard model
    assert not hasattr(displayed, "cert_image_url"), (
        "cert_image_url is admin-only and must not reach customer /chat wire. "
        "Fix: drop the field in _hydrate_item projection until a customer-facing "
        "render need exists."
    )


def test_cert_image_url_not_in_panel_cards_either():
    """Panel cards go through the same hydration path and must also exclude
    cert_image_url.
    """
    item = _graded("graded-2", cert_image_url="https://provider.example/cert/87654321.jpg")
    repo = FakeRepo([item])
    
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
                                "input": {"item_ids": [item.item_id]},
                                "toolUseId": "tool-1",
                            }
                        }
                    ],
                }
            },
            "stopReason": "tool_use",
        },
        _end_turn("Panel set."),
    ]
    
    service = _service(client, repo)
    response = service.chat("Set the panel")
    
    assert len(response["panel"].cards) == 1
    panel_card = response["panel"].cards[0]
    
    assert not hasattr(panel_card, "cert_image_url"), (
        "cert_image_url must not appear in panel cards either"
    )


# ---- Council item 6: tool results must use json.dumps, not f-strings ----


def test_display_card_error_with_quoted_item_id_produces_valid_json():
    """RED for Council item 6: tool result JSON must be built with json.dumps,
    not f-string interpolation.
    
    An item_id containing a quote (client-influenced via panel_item_ids or
    model-influenced via tool calls) must not produce malformed JSON when
    returned as a tool error result.
    
    Currently FAILS because _run_display_tool's error path does:
        f'{{"error": "Item {item_id} not found"}}'
    
    If item_id = 'item"123', the result is malformed JSON.
    """
    # No item exists, so display_card returns an error
    repo = FakeRepo([])
    
    client = MagicMock()
    malicious_id = 'item"with"quotes'
    client.converse.side_effect = [
        {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "toolUse": {
                                "name": "display_card",
                                "input": {"item_id": malicious_id},
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
    response = service.chat("Show malicious item")
    
    # Extract the tool result text sent back to the model
    tool_result_call = client.converse.call_args_list[1]
    tool_result = tool_result_call.kwargs["messages"][2]["content"][0]
    result_text = tool_result["toolResult"]["content"][0]["text"]
    
    # This must be valid, parseable JSON
    import json
    try:
        parsed = json.loads(result_text)
        assert "error" in parsed or "status" in parsed, "Tool error must be structured JSON"
    except json.JSONDecodeError as e:
        pytest.fail(
            f"Tool result is malformed JSON when item_id contains quotes. "
            f"Got: {result_text!r}. Error: {e}. "
            f"Fix: use json.dumps() in _run_display_tool, not f-string interpolation."
        )


def test_set_display_result_with_quoted_item_id_produces_valid_json():
    """The set_display tool result must also use json.dumps when echoing the
    resulting panel contents back to the model.
    
    Currently the remove_from_panel path does f-string interpolation of item_id.
    Must use json.dumps for all tool results.
    """
    from merlins_collection.models.inventory import RawInventoryItem, Condition
    
    item = RawInventoryItem(
        item_id='item"123',  # Quote in ID
        card_id=None,
        status=ItemStatus.AVAILABLE,
        listed_price=Decimal("10.00"),
        cost_basis=Decimal("5.00"),
        acquired_at=date.today(),
        finish="normal",
        condition=Condition.NM,
        location="glass",
    )
    repo = FakeRepo([item])
    
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
                                "input": {"item_ids": [item.item_id]},
                                "toolUseId": "tool-1",
                            }
                        }
                    ],
                }
            },
            "stopReason": "tool_use",
        },
        _end_turn("Panel updated."),
    ]
    
    service = _service(client, repo)
    response = service.chat("Set the panel")
    
    # Tool result must be valid JSON
    tool_result_call = client.converse.call_args_list[1]
    tool_result = tool_result_call.kwargs["messages"][2]["content"][0]
    result_text = tool_result["toolResult"]["content"][0]["text"]
    
    import json
    try:
        parsed = json.loads(result_text)
        # set_display result should echo the panel contents
        assert "panel" in parsed or "cards" in parsed or "status" in parsed
    except json.JSONDecodeError as e:
        pytest.fail(
            f"set_display tool result is malformed JSON when item_id contains quotes. "
            f"Got: {result_text!r}. Error: {e}. "
            f"Fix: use json.dumps() for all tool results."
        )
