"""RED contract tests for RFC 0016's request/response display envelope."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from merlins_collection.models import chat as chat_models


def _model(name: str):
    assert hasattr(chat_models, name), f"RFC 0016 model {name} is not implemented"
    return getattr(chat_models, name)


def _displayed_card(index: int = 1):
    DisplayedCard = _model("DisplayedCard")
    return DisplayedCard(
        item_id=f"item-{index}",
        kind="raw",
        listed_price=Decimal("25.00"),
    )


def test_chat_request_message_only_keeps_backward_compatible_defaults():
    request = chat_models.ChatRequest(message="Show me a card")
    assert request.history == []
    assert request.panel_item_ids == []


def test_chat_request_accepts_history_without_panel_state():
    request = chat_models.ChatRequest(
        message="What about Pikachu?",
        history=[
            {"role": "user", "content": "Show Charizard"},
            {"role": "assistant", "content": "Here it is"},
        ],
    )
    assert len(request.history) == 2
    assert request.panel_item_ids == []


def test_chat_request_accepts_panel_item_ids_without_history():
    request = chat_models.ChatRequest(message="Close it", panel_item_ids=["item-1"])
    assert request.panel_item_ids == ["item-1"]


def test_chat_request_accepts_message_history_and_panel_item_ids():
    request = chat_models.ChatRequest(
        message="Remove Pikachu",
        history=[
            {"role": "user", "content": "Show two cards"},
            {"role": "assistant", "content": "Done"},
        ],
        panel_item_ids=["item-1", "item-2"],
    )
    assert request.panel_item_ids == ["item-1", "item-2"]


def test_chat_request_rejects_more_than_50_panel_item_ids():
    with pytest.raises(ValidationError):
        chat_models.ChatRequest(
            message="Keep these open",
            panel_item_ids=[f"item-{i}" for i in range(51)],
        )


def test_chat_request_rejects_panel_item_id_longer_than_100_chars():
    with pytest.raises(ValidationError):
        chat_models.ChatRequest(message="Keep this open", panel_item_ids=["x" * 101])


def test_chat_request_rejects_client_supplied_card_data_in_panel_item_ids():
    with pytest.raises(ValidationError):
        chat_models.ChatRequest(
            message="Trust this price",
            panel_item_ids=[{"item_id": "item-1", "listed_price": "0.01"}],
        )


def test_chat_response_reply_only_has_empty_display_defaults():
    response = chat_models.ChatResponse(reply="No display needed")
    assert response.artifacts == []
    # Decision 23: open field removed, panel state derived from len(cards)
    assert not hasattr(response.panel, "open"), (
        "DisplayPanel.open removed per decision 23, state derived from len(cards)"
    )
    assert response.panel.cards == []
    assert response.panel.truncated is False


def test_chat_response_accepts_inline_artifacts():
    response = chat_models.ChatResponse(reply="Here it is", artifacts=[_displayed_card()])
    assert [card.item_id for card in response.artifacts] == ["item-1"]


def test_chat_response_accepts_explicit_panel_state():
    DisplayPanel = _model("DisplayPanel")
    response = chat_models.ChatResponse(
        reply="Panel opened",
        panel=DisplayPanel(cards=[_displayed_card()], truncated=False),
    )
    # Decision 23: open derived from len(cards); cards present = open
    assert len(response.panel.cards) > 0, "Panel with cards is considered open"
    assert [card.item_id for card in response.panel.cards] == ["item-1"]


def test_chat_response_accepts_reply_artifacts_and_panel_together():
    DisplayPanel = _model("DisplayPanel")
    response = chat_models.ChatResponse(
        reply="One inline and one docked",
        artifacts=[_displayed_card(1)],
        panel=DisplayPanel(cards=[_displayed_card(2)]),
    )
    assert response.reply == "One inline and one docked"
    assert [card.item_id for card in response.artifacts] == ["item-1"]
    assert [card.item_id for card in response.panel.cards] == ["item-2"]


def test_displayed_card_requires_item_id_kind_and_listed_price():
    DisplayedCard = _model("DisplayedCard")
    for missing in ("item_id", "kind", "listed_price"):
        values = {"item_id": "item-1", "kind": "raw", "listed_price": "12.00"}
        values.pop(missing)
        with pytest.raises(ValidationError):
            DisplayedCard(**values)


def test_displayed_card_allows_missing_catalog_summary():
    card = _displayed_card()
    assert card.card is None


def test_display_panel_rejects_more_than_50_cards():
    DisplayPanel = _model("DisplayPanel")
    with pytest.raises(ValidationError):
        DisplayPanel(cards=[_displayed_card(i) for i in range(51)])


def test_display_panel_truncated_defaults_false():
    DisplayPanel = _model("DisplayPanel")
    assert DisplayPanel().truncated is False


def test_display_panel_open_state_derived_from_cards_not_stored():
    """Decision 23: DisplayPanel.open removed, state derived from len(cards)."""
    DisplayPanel = _model("DisplayPanel")
    
    # Never opened = no cards
    never_opened = DisplayPanel()
    assert never_opened.cards == []
    assert not hasattr(never_opened, "open"), "open field must not exist"
    
    # Closed = explicitly no cards
    closed = DisplayPanel(cards=[])
    assert closed.cards == []
    assert not hasattr(closed, "open"), "open field must not exist"
    
    # Open = has cards
    opened = DisplayPanel(cards=[_displayed_card()])
    assert len(opened.cards) > 0
    assert not hasattr(opened, "open"), "open field must not exist"


def test_display_panel_schema_has_no_model_controlled_fullscreen_field():
    DisplayPanel = _model("DisplayPanel")
    panel = DisplayPanel(cards=[_displayed_card()], fullscreen=True)
    assert "fullscreen" not in panel.model_dump()

