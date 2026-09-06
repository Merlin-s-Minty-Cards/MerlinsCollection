"""RFC 0025 T4 — `_hydrate_item`'s customer-facing price is the STICKER.

This file used to pin the OLD derivation (`_display_price`'s pre-RFC-0025
form: live catalog price, condition-adjusted, falling back to
`current_market_value` then `listed_price`) — Council item 3's fix for a
chat/search price divergence. RFC 0025 T2/T4 replaced that whole mechanism:
`_display_price` (routers/inventory.py) is now `item.sticker_price`, no
fallback, no condition adjustment (a sticker is already condition-inclusive,
set by a human holding the card). `_hydrate_item` is the SAME shared
hydrator for both the customer chat and the admin analyst chat ("ONE
hydrator... never a second admin copy") and mirrors that change for both —
neither surface has its own reason to keep the old catalog-derived figure,
and RFC 0025's admin-surface exclusion list (services/condition_pricing.py
stays wired into routers/admin/inventory.py and the MCP admin path) does not
name this shared hydrator, so nothing exempts it.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

from merlins_collection.models.catalog import CardImages, CatalogCard, FinishPrice
from merlins_collection.models.inventory import (
    Condition,
    GradedInventoryItem,
    GradingCompany,
    ItemStatus,
    RawInventoryItem,
)
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
    return bedrock._hydrate_item(repo, item_id)


def _catalog_card(card_id: str, nm_price: str) -> CatalogCard:
    return CatalogCard(
        card_id=card_id,
        name="Test Card",
        set_id="test-set",
        set_name="Test Set",
        number="1",
        rarity="common",
        images=CardImages(small="https://example.com/s.png", large="https://example.com/l.png"),
        prices={"normal": FinishPrice(market=Decimal(nm_price))},
        last_synced_at=datetime.now(tz=timezone.utc),
    )


def _raw(item_id: str, card_id: str | None, condition: Condition, *, sticker: str) -> RawInventoryItem:
    return RawInventoryItem(
        item_id=item_id,
        card_id=card_id,
        status=ItemStatus.AVAILABLE,
        listed_price=Decimal("999.00"),  # a decoy — must never be what renders
        current_market_value=Decimal("999.00"),  # likewise a decoy
        sticker_price=Decimal(sticker),
        cost_basis=Decimal("10.00"),
        acquired_at=date.today(),
        finish="normal",
        condition=condition,
        location="glass",
    )


def test_hydrate_renders_the_sticker_price_unadjusted_even_for_a_dmg_card():
    """A DMG card's sticker is already condition-inclusive — hydration must
    NOT scale it a second time, unlike the old catalog-derived figure."""
    item = _raw("dmg-card", "en:test-1", Condition.DMG, sticker="30.00")
    catalog = _catalog_card("en:test-1", nm_price="100.00")
    repo = FakeRepo([item], [catalog])

    result = _hydrate(repo, item.item_id)

    assert result is not None
    assert result.listed_price == Decimal("30.00")


def test_hydrate_ignores_the_live_catalog_price_entirely():
    """The catalog price (however current) is never what renders — only the
    sticker is, matching `_display_price`'s new single authority."""
    item = _raw("live-price", "en:test-2", Condition.NM, sticker="180.00")
    catalog = _catalog_card("en:test-2", nm_price="200.00")
    repo = FakeRepo([item], [catalog])

    result = _hydrate(repo, item.item_id)

    assert result is not None
    assert result.listed_price == Decimal("180.00")


def test_hydrate_graded_item_uses_the_sticker_too():
    """Graded slabs never had a catalog price to begin with (an ungraded
    figure) — this pins that the sticker, not `listed_price`, is what
    renders for them as well."""
    graded = GradedInventoryItem(
        item_id="graded-slab",
        card_id="en:test-3",
        status=ItemStatus.AVAILABLE,
        listed_price=Decimal("999.00"),  # decoy
        sticker_price=Decimal("1500.00"),
        cost_basis=Decimal("1000.00"),
        acquired_at=date.today(),
        cert_number="12345678",
        company=GradingCompany.PSA,
        grade=Decimal("10"),
        location="glass",
    )
    catalog = _catalog_card("en:test-3", nm_price="500.00")
    repo = FakeRepo([graded], [catalog])

    result = _hydrate(repo, graded.item_id)

    assert result is not None
    assert result.listed_price == Decimal("1500.00")


def test_hydrate_uncatalogued_item_still_uses_the_sticker():
    """No catalog card at all — the sticker still renders; there is nothing
    left to fall back to or through."""
    item = _raw("uncatalogued", None, Condition.LP, sticker="12.50")
    repo = FakeRepo([item], [])

    result = _hydrate(repo, item.item_id)

    assert result is not None
    assert result.listed_price == Decimal("12.50")
