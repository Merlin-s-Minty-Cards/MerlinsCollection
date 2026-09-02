"""RED tests for Council item 3: price derivation in _hydrate_item.

_hydrate_item must go through CardSummary.from_catalog + apply_condition_adjustment
+ _display_price, not a local re-derivation. This is the FOURTH price derivation
(the other three: _display_price in routers/inventory.py, CardTile.tsx, and the
admin picker), and it already disagrees with the others.

Currently _hydrate_item renders current_market_value (nightly-denormalized, stale)
where _display_price renders the live catalog price with condition adjustment.
A DMG card's chat price would ship the NM figure once anything reads
CardSummary.market_price, because apply_condition_adjustment is never called.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from merlins_collection.models.catalog import CatalogCard, FinishPrice
from merlins_collection.models.inventory import Condition, ItemStatus, RawInventoryItem
from merlins_collection.services import bedrock


class FakeRepo:
    def __init__(self, items=(), cards=()):
        self.items = {item.item_id: item for item in items}
        self.cards = {card.card_id: card for card in cards}

    def get_inventory_item(self, item_id):
        return self.items.get(item_id)

    def get_catalog_card(self, card_id):
        return self.cards.get(card_id)


def _hydrate(repo, item_id: str):
    assert hasattr(bedrock, "_hydrate_item"), "RFC 0016 _hydrate_item is not implemented"
    return bedrock._hydrate_item(repo, item_id)


def _raw(
    item_id: str,
    card_id: str | None,
    condition: Condition,
    listed_price: str,
    market_value: str,
):
    return RawInventoryItem(
        item_id=item_id,
        card_id=card_id,
        status=ItemStatus.AVAILABLE,
        listed_price=Decimal(listed_price),
        current_market_value=Decimal(market_value),
        cost_basis=Decimal("10.00"),
        acquired_at=date.today(),
        finish="normal",
        condition=condition,
        location="glass",
    )


def _catalog_card(card_id: str, nm_price: str):
    # RawInventoryItem's finish defaults to "normal" in this file's _raw()
    # helper, so the price band must be keyed "normal" for
    # market_price_and_finish to find it.
    return CatalogCard(
        card_id=card_id,
        name="Test Card",
        set_id="test-set",
        set_name="Test Set",
        number="1",
        rarity="common",
        prices={"normal": FinishPrice(market=Decimal(nm_price))},
        last_synced_at=datetime.now(tz=timezone.utc),
    )


def test_hydrate_dmg_card_applies_condition_adjustment_to_catalog_price():
    """RED for Council item 3: _hydrate_item must apply condition adjustment.
    
    A DMG-condition card must NOT ship the NM catalog price. Currently FAILS
    because _hydrate_item renders current_market_value (stale, denormalized)
    or listed_price, never calling apply_condition_adjustment.
    
    Fix: hydrate through CardSummary.from_catalog + apply_condition_adjustment
    + _display_price (from routers/inventory.py), matching the filter mode path.
    """
    item = _raw(
        item_id="dmg-card",
        card_id="en:test-1",
        condition=Condition.DMG,
        listed_price="5.00",
        market_value="100.00",  # Stale NM value from last catalog sync
    )
    catalog = _catalog_card("en:test-1", nm_price="100.00")
    repo = FakeRepo([item], [catalog])

    result = _hydrate(repo, item.item_id)
    assert result is not None, "Hydration must succeed for catalogued item"

    # DMG condition applies a ~0.30 multiplier in apply_condition_adjustment
    # 100.00 * 0.30 = 30.00 (or thereabouts, exact value from condition_pricing.py)
    # It must NOT be 100.00 (the NM catalog price) or 5.00 (listed_price fallback)
    
    # The displayed price is in DisplayedCard.listed_price (confusing name, but
    # that's the wire field per RFC 0016 ChatResponse schema)
    assert result.listed_price is not None
    assert result.listed_price < Decimal("50.00"), (
        f"DMG card must show condition-adjusted price, got {result.listed_price}. "
        "Expected ~30% of NM catalog price (100.00 * 0.30 ≈ 30.00), not the NM figure."
    )
    assert result.listed_price != Decimal("5.00"), (
        "Must use catalog price with adjustment, not raw listed_price fallback"
    )


def test_hydrate_uses_live_catalog_price_not_denormalized_market_value():
    """_hydrate_item must render the LIVE catalog price (_display_price), not
    the stale current_market_value denormalized by nightly catalog_sync.
    
    Scenario: catalog price updated to 200.00, but last sync left 150.00 in
    current_market_value. Hydration must show 200.00 (live), not 150.00 (stale).
    """
    item = _raw(
        item_id="live-price",
        card_id="en:test-2",
        condition=Condition.NM,
        listed_price="180.00",
        market_value="150.00",  # Stale from yesterday's sync
    )
    catalog = _catalog_card("en:test-2", nm_price="200.00")  # Updated today
    repo = FakeRepo([item], [catalog])

    result = _hydrate(repo, item.item_id)
    assert result is not None
    
    # For NM raw cards, _display_price returns live catalog.market_price
    # (from CardSummary.from_catalog), which is 200.00, NOT the stale 150.00
    assert result.listed_price == Decimal("200.00"), (
        f"Must use live catalog price (200.00), got {result.listed_price}. "
        "Denormalized current_market_value (150.00) is stale and must not reach customers."
    )


def test_hydrate_graded_item_uses_listed_price_not_catalog():
    """Graded slabs skip catalog price deliberately (it's an ungraded figure).
    
    This is _display_price's second branch: for kind=graded, market_price is
    skipped and listed_price is authoritative. _hydrate_item must match.
    """
    from merlins_collection.models.inventory import GradedInventoryItem, GradingCompany

    graded = GradedInventoryItem(
        item_id="graded-slab",
        card_id="en:test-3",
        status=ItemStatus.AVAILABLE,
        listed_price=Decimal("1500.00"),  # Grade premium
        cost_basis=Decimal("1000.00"),
        acquired_at=date.today(),
        cert_number="12345678",
        company=GradingCompany.PSA,
        grade=Decimal("10"),
        location="glass",
    )
    catalog = _catalog_card("en:test-3", nm_price="500.00")  # Ungraded NM
    repo = FakeRepo([graded], [catalog])

    result = _hydrate(repo, graded.item_id)
    assert result is not None
    
    # Graded items use listed_price, NOT catalog market_price
    assert result.listed_price == Decimal("1500.00"), (
        f"Graded slab must use listed_price (1500.00), got {result.listed_price}. "
        "Catalog price (500.00) is for ungraded and must be skipped."
    )


def test_hydrate_uncatalogued_item_falls_back_to_listed_price():
    """An uncatalogued raw card (card_id=None) has no catalog to adjust from.
    
    _display_price returns listed_price when no catalog exists. Same for hydration.
    """
    item = _raw(
        item_id="uncatalogued",
        card_id=None,
        condition=Condition.LP,
        listed_price="12.50",
        market_value="0.00",
    )
    repo = FakeRepo([item], [])

    result = _hydrate(repo, item.item_id)
    assert result is not None
    assert result.listed_price == Decimal("12.50")
