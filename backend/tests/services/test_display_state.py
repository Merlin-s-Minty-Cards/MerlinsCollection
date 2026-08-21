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
    assert state.panel_open is None
    assert state.panel_truncated is False


def test_initial_item_ids_are_rehydrated_and_open_the_panel():
    item = _raw("item-1")
    state = _state(FakeRepo([item]), [item.item_id])
    assert [card.item_id for card in state.panel_cards] == ["item-1"]
    assert state.panel_open is True


def test_unavailable_initial_ids_are_dropped_and_do_not_mark_panel_open():
    item = _raw("sold-1", ItemStatus.SOLD)
    state = _state(FakeRepo([item]), [item.item_id])
    assert state.panel_cards == []
    assert state.panel_open is None


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


def test_open_panel_distinguishes_first_open_from_already_open():
    state = _state()
    assert "open" in state.open_panel().lower()
    assert state.panel_open is True
    assert "already" in state.open_panel().lower()


def test_close_panel_distinguishes_first_close_from_already_closed():
    state = _state()
    assert "close" in state.close_panel().lower()
    assert state.panel_open is False
    assert "already" in state.close_panel().lower()


def test_add_to_panel_auto_opens_never_opened_panel():
    state = _state()
    state.add_to_panel(_card("item-1"))
    assert state.panel_open is True


def test_add_to_panel_keeps_open_panel_open():
    state = _state()
    state.open_panel()
    state.add_to_panel(_card("item-1"))
    assert state.panel_open is True


def test_add_to_panel_appends_card_under_cap():
    state = _state()
    result = state.add_to_panel(_card("item-1"))
    assert [card.item_id for card in state.panel_cards] == ["item-1"]
    assert "added" in result.lower()


def test_add_to_panel_caps_at_50_and_returns_truncation_notice():
    state = _state()
    for i in range(50):
        state.add_to_panel(_card(f"item-{i}"))

    result = state.add_to_panel(_card("overflow"))

    assert len(state.panel_cards) == 50
    assert state.panel_truncated is True
    assert "50" in result
    assert "full" in result.lower()


def test_add_to_panel_deduplicates_by_item_id():
    state = _state()
    state.add_to_panel(_card("item-1"))
    result = state.add_to_panel(_card("item-1"))
    assert [card.item_id for card in state.panel_cards] == ["item-1"]
    assert "already" in result.lower()


def test_remove_from_panel_removes_existing_card():
    state = _state()
    state.add_to_panel(_card("item-1"))
    result = state.remove_from_panel("item-1")
    assert state.panel_cards == []
    assert "removed" in result.lower()


def test_remove_from_panel_reports_unknown_id():
    state = _state()
    assert "not found" in state.remove_from_panel("missing").lower()


def test_removing_last_card_leaves_panel_open_and_empty():
    state = _state()
    state.add_to_panel(_card("item-1"))
    state.remove_from_panel("item-1")
    assert state.panel_cards == []
    assert state.panel_open is True


def test_reorder_panel_accepts_exact_permutation():
    state = _state()
    for item_id in ("item-1", "item-2", "item-3"):
        state.add_to_panel(_card(item_id))
    result = state.reorder_panel(["item-3", "item-1", "item-2"])
    assert [card.item_id for card in state.panel_cards] == ["item-3", "item-1", "item-2"]
    assert "reordered" in result.lower()


@pytest.mark.parametrize(
    "item_ids",
    [
        ["item-1"],
        ["item-1", "item-2", "extra"],
        ["item-1", "item-1", "item-2"],
    ],
    ids=["missing", "extra", "duplicate"],
)
def test_reorder_panel_rejects_non_exact_contents(item_ids):
    state = _state()
    state.add_to_panel(_card("item-1"))
    state.add_to_panel(_card("item-2"))
    original = [card.item_id for card in state.panel_cards]
    result = state.reorder_panel(item_ids)
    assert [card.item_id for card in state.panel_cards] == original
    assert "failed" in result.lower()


def test_response_fields_preserve_artifacts_and_three_state_panel():
    state = _state()
    state.display_inline(_card("inline"))
    state.open_panel()
    state.add_to_panel(_card("panel"))
    fields = state.to_response_fields()
    assert [card.item_id for card in fields["artifacts"]] == ["inline"]
    assert fields["panel"].open is True
    assert [card.item_id for card in fields["panel"].cards] == ["panel"]
    assert fields["panel"].truncated is False
