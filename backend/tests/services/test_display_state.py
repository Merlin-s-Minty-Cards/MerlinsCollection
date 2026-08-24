"""RED tests for RFC 0016's per-request display state accumulator."""

from datetime import date
from decimal import Decimal

import pytest

from merlins_collection.models.inventory import Condition, ItemStatus, RawInventoryItem
from merlins_collection.services import bedrock


class FakeRepo:
    def __init__(self, items=()):
        self.items = {item.item_id: item for item in items}

    def get_inventory_item(self, item_id):
        return self.items.get(item_id)

    def get_catalog_card(self, _card_id):
        return None


def _raw(item_id: str, status: ItemStatus = ItemStatus.AVAILABLE):
    return RawInventoryItem(
        item_id=item_id,
        card_id=None,
        status=status,
        listed_price=Decimal("10.00"),
        cost_basis=Decimal("5.00"),
        acquired_at=date.today(),
        finish="normal",
        condition=Condition.NM,
        display_name=f"Card {item_id}",
        # Council item 2: hydration requires a display-ready location. This fixture
        # represents customer-visible stock; withheld cases are explicit elsewhere.
        location="glass",
    )


def _state(repo=None, initial_item_ids=()):
    assert hasattr(bedrock, "_DisplayState"), "RFC 0016 _DisplayState is not implemented"
    return bedrock._DisplayState(repo or FakeRepo(), list(initial_item_ids))


def _card(item_id: str):
    from merlins_collection.models import chat as chat_models

    assert hasattr(chat_models, "DisplayedCard"), "RFC 0016 DisplayedCard is not implemented"
    return chat_models.DisplayedCard(
        item_id=item_id,
        kind="raw",
        display_name=f"Card {item_id}",
        listed_price=Decimal("10.00"),
    )


def test_empty_initial_state_is_never_opened():
    state = _state()
    assert state.panel_cards == []
    assert len(state.panel_cards) == 0  # Closed = empty cards list
    assert state.panel_truncated is False


def test_initial_item_ids_are_rehydrated_and_open_the_panel():
    item = _raw("item-1")
    state = _state(FakeRepo([item]), [item.item_id])
    assert [card.item_id for card in state.panel_cards] == ["item-1"]
    assert len(state.panel_cards) > 0  # Open = non-empty cards list


def test_unavailable_initial_ids_are_dropped_and_do_not_mark_panel_open():
    item = _raw("sold-1", ItemStatus.SOLD)
    state = _state(FakeRepo([item]), [item.item_id])
    assert state.panel_cards == []
    assert len(state.panel_cards) == 0  # Closed = empty cards list


def test_internal_state_defensively_caps_initial_ids_at_50_without_truncation():
    items = [_raw(f"item-{i}") for i in range(52)]
    state = _state(FakeRepo(items), [item.item_id for item in items])
    assert len(state.panel_cards) == 50
    assert state.panel_truncated is False


def test_display_inline_appends_artifact_and_returns_confirmation():
    state = _state()
    result = state.display_inline(_card("item-1"))
    assert [card.item_id for card in state.artifacts] == ["item-1"]
    assert "display" in result.lower()


def test_set_panel_replaces_contents_wholesale():
    """set_panel(ids) replaces all panel contents (decision 23 state machine)."""
    state = _state()
    result = state.set_panel([_card("item-1"), _card("item-2")])
    assert [card.item_id for card in state.panel_cards] == ["item-1", "item-2"]
    assert len(state.panel_cards) > 0  # Open = non-empty cards list
    assert "set" in result.lower() or "panel" in result.lower()


def test_set_panel_empty_list_closes_panel():
    """set_panel([]) closes the panel and clears contents."""
    state = _state()
    state.set_panel([_card("item-1")])
    result = state.set_panel([])
    assert state.panel_cards == []
    assert len(state.panel_cards) == 0  # Closed = empty cards list


def test_set_panel_caps_at_50_and_returns_truncation_notice():
    state = _state()
    cards = [_card(f"item-{i}") for i in range(51)]
    result = state.set_panel(cards)

    assert len(state.panel_cards) == 50
    assert state.panel_truncated is True
    assert "50" in result
    assert "full" in result.lower() or "truncat" in result.lower()


def test_set_panel_deduplicates_by_item_id():
    """set_panel deduplicates before setting (work ceiling requirement)."""
    state = _state()
    cards = [_card("item-1"), _card("item-2"), _card("item-1")]  # duplicate item-1
    state.set_panel(cards)
    assert [card.item_id for card in state.panel_cards] == ["item-1", "item-2"]


def test_set_panel_preserves_order():
    """Panel order is the order in the input list (model-driven reorder)."""
    state = _state()
    cards = [_card("item-3"), _card("item-1"), _card("item-2")]
    state.set_panel(cards)
    assert [card.item_id for card in state.panel_cards] == ["item-3", "item-1", "item-2"]


def test_response_fields_preserve_artifacts_and_panel():
    state = _state()
    state.display_inline(_card("inline"))
    state.set_panel([_card("panel-1"), _card("panel-2")])
    fields = state.to_response_fields()
    assert [card.item_id for card in fields["artifacts"]] == ["inline"]
    assert len(fields["panel"].cards) > 0  # Open = non-empty cards list
    assert [card.item_id for card in fields["panel"].cards] == ["panel-1", "panel-2"]
    assert fields["panel"].truncated is False


def test_display_panel_has_no_open_field():
    """RFC 0016 decision 23: DisplayPanel must not have an 'open' field.
    
    The tri-state open field was removed. Panel open/closed is inferred purely
    from whether cards is non-empty (len(cards) > 0 means open).
    """
    from merlins_collection.models import chat as chat_models
    
    assert hasattr(chat_models, "DisplayPanel"), "RFC 0016 DisplayPanel is not implemented"
    panel_class = chat_models.DisplayPanel
    assert "open" not in panel_class.model_fields, (
        "DisplayPanel must not have an 'open' field (RFC 0016 decision 23). "
        "Open/closed is inferred from len(cards) > 0."
    )
