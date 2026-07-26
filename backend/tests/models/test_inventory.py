from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from merlins_collection.models.inventory import (
    BulkInventoryItem,
    Condition,
    ConditionModifier,
    ConsignmentTerms,
    GradedInventoryItem,
    GradingCompany,
    InventoryItemAdapter,
    ItemStatus,
    Language,
    RawInventoryItem,
    SealedInventoryItem,
    SealedProductType,
)


def _base(**over):
    kw = dict(cost_basis=Decimal("10.00"), acquired_at=date(2026, 1, 5))
    kw.update(over)
    return kw


def test_raw_item_defaults_and_new_fields():
    item = RawInventoryItem(**_base(finish="holofoil", condition="LP",
                                    condition_modifier="+", factory_sealed=True))
    assert item.kind == "raw"
    assert item.card_id is None
    assert item.status is ItemStatus.AVAILABLE
    assert item.condition_modifier is ConditionModifier.PLUS
    assert item.factory_sealed is True
    assert item.listed_price is None
    assert item.consignment is None
    assert item.needs_review is False
    assert len(item.item_id) == 26  # ULID


def test_item_ids_are_unique():
    a = RawInventoryItem(**_base(finish="normal", condition="NM"))
    b = RawInventoryItem(**_base(finish="normal", condition="NM"))
    assert a.item_id != b.item_id


def test_raw_item_parses_via_adapter():
    item = InventoryItemAdapter.validate_python(
        {
            "kind": "raw",
            "card_id": "swsh1-1",
            "listed_price": Decimal("10"),
            "cost_basis": Decimal("4"),
            "acquired_at": date(2026, 1, 1),
            "finish": "holofoil",
            "condition": "NM",
        }
    )
    assert isinstance(item, RawInventoryItem)
    assert item.condition is Condition.NM
    assert item.current_market_value is None


def test_graded_item_parses_via_adapter():
    item = InventoryItemAdapter.validate_python(
        {
            "kind": "graded",
            "card_id": "swsh1-1",
            "listed_price": Decimal("600"),
            "cost_basis": Decimal("300"),
            "acquired_at": date(2026, 1, 1),
            "company": "PSA",
            "grade": Decimal("10"),
            "cert_number": "12345678",
        }
    )
    assert isinstance(item, GradedInventoryItem)
    assert item.grade == Decimal("10")
    assert item.company is GradingCompany.PSA


def test_sealed_and_bulk_kinds_round_trip_through_adapter():
    sealed = SealedInventoryItem(**_base(product_name="Evolving Skies Booster Box",
                                         product_type="booster_box"))
    bulk = BulkInventoryItem(**_base(description="5k common/uncommon lot"))
    assert sealed.product_type is SealedProductType.BOOSTER_BOX
    for item in (sealed, bulk):
        again = InventoryItemAdapter.validate_python(item.model_dump(mode="python"))
        assert again == item


def test_consignment_terms_attach_to_any_kind():
    terms = ConsignmentTerms(consignor_id="c-1", split_percent=Decimal("20"),
                             minimum_price=Decimal("50.00"))
    item = GradedInventoryItem(**_base(company="PSA", grade=Decimal("10"),
                                       cert_number="123", consignment=terms))
    assert item.consignment.paid_out is False
    assert item.consignment.split_percent == Decimal("20")


def test_quantity_field_is_gone():
    item = RawInventoryItem(**_base(finish="normal", condition="NM"))
    assert not hasattr(item, "quantity")


def test_invalid_condition_modifier_rejected():
    with pytest.raises(ValidationError):
        RawInventoryItem(**_base(finish="normal", condition="NM",
                                 condition_modifier="++"))


# ---- print language (part of a card's identity, not a label) ----

def test_language_defaults_to_english():
    item = RawInventoryItem(**_base(finish="normal", condition="NM"))
    assert item.language is Language.EN


def test_language_is_shared_by_every_item_kind():
    """A Japanese slab is as real as a Japanese single, so ``language`` lives on
    the shared base rather than only on raw cards."""
    kinds = [
        RawInventoryItem(**_base(finish="normal", condition="NM", language="JP")),
        GradedInventoryItem(**_base(company="PSA", grade=Decimal("10"),
                                    cert_number="123", language="JP")),
        SealedInventoryItem(**_base(product_name="Booster Box",
                                    product_type="booster_box", language="JP")),
        BulkInventoryItem(**_base(description="5k lot", language="JP")),
    ]
    assert [item.language for item in kinds] == [Language.JP] * 4


def test_records_written_before_the_language_field_read_as_english():
    """The 1489 live records carry no ``language`` attribute; they must validate
    as English rather than blow up (this is what makes the field migration-free)."""
    item = InventoryItemAdapter.validate_python(
        {"kind": "raw", "cost_basis": Decimal("4"), "acquired_at": date(2026, 1, 1),
         "finish": "normal", "condition": "NM"}
    )
    assert item.language is Language.EN


def test_language_round_trips_through_the_adapter():
    item = InventoryItemAdapter.validate_python(
        {"kind": "raw", "cost_basis": Decimal("4"), "acquired_at": date(2026, 1, 1),
         "finish": "normal", "condition": "NM", "language": "JP"}
    )
    assert item.language is Language.JP
    assert item.model_dump(mode="python")["language"] is Language.JP


def test_unknown_language_is_rejected():
    with pytest.raises(ValidationError):
        RawInventoryItem(**_base(finish="normal", condition="NM", language="KLINGON"))


def test_adapter_rejects_raw_missing_fields():
    with pytest.raises(ValidationError):
        InventoryItemAdapter.validate_python(
            {"kind": "raw", "card_id": "x",
             "listed_price": Decimal("1"), "cost_basis": Decimal("1"),
             "acquired_at": "2026-01-01"}
        )


# --- A: market price surfaced on the tile via CardSummary ----------------------

def _catalog_with_prices(prices):
    from datetime import datetime, timezone
    from merlins_collection.models.catalog import CardImages, CatalogCard, FinishPrice
    return CatalogCard(
        card_id="sv1-1", name="Sprigatito", set_id="sv1", set_name="Scarlet & Violet",
        number="1", images=CardImages(small="s", large="l"),
        prices={k: FinishPrice(market=Decimal(v)) for k, v in prices.items()},
        last_synced_at=datetime.now(timezone.utc),
    )


def test_card_summary_market_price_prefers_the_items_finish():
    from merlins_collection.models.inventory import CardSummary
    card = _catalog_with_prices({"normal": "3.50", "holofoil": "40.00"})
    assert CardSummary.from_catalog(card, finish="holofoil").market_price == Decimal("40.00")
    assert CardSummary.from_catalog(card, finish="normal").market_price == Decimal("3.50")


def test_card_summary_market_price_falls_back_when_the_finish_has_no_price():
    from merlins_collection.models.inventory import CardSummary
    # Holo-only card: the item's finish is "normal" but only a holo price exists.
    card = _catalog_with_prices({"holofoil": "40.00"})
    assert CardSummary.from_catalog(card, finish="normal").market_price == Decimal("40.00")


def test_card_summary_market_price_is_none_when_catalog_has_no_prices():
    from merlins_collection.models.inventory import CardSummary
    assert CardSummary.from_catalog(_catalog_with_prices({}), finish="normal").market_price is None


def test_card_summary_market_price_absent_without_a_finish_is_none_for_graded():
    """The catalog price is an UNGRADED figure, so a graded slab (no finish)
    gets no market price and the caller keeps the slab's own value (A)."""
    from merlins_collection.models.inventory import CardSummary
    card = _catalog_with_prices({"normal": "3.50"})
    assert CardSummary.from_catalog(card, finish=None).market_price is None
