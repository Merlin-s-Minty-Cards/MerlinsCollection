from datetime import datetime
from decimal import Decimal

from merlins_collection.models.catalog import CatalogCard, FinishPrice, PricePoint
from merlins_collection.models.inventory import Language


def test_catalog_card_defaults_and_decimal_prices():
    card = CatalogCard(
        card_id="swsh1-1",
        name="Celebi V",
        set_id="swsh1",
        set_name="Sword & Shield",
        number="1",
        images={"small": "s.png", "large": "l.png"},
        prices={"holofoil": {"market": Decimal("12.50")}},
        last_synced_at=datetime(2026, 6, 22, 12, 0, 0),
    )
    assert card.rarity is None
    assert card.types == []
    assert card.prices["holofoil"].market == Decimal("12.50")
    assert isinstance(card.prices["holofoil"], FinishPrice)


def test_price_point_graded_shape():
    p = PricePoint(
        card_id="swsh1-1", date="2026-06-22", source="manual",
        kind="graded", company="PSA", grade=Decimal("10"), market=Decimal("500"),
    )
    assert p.kind == "graded"
    assert p.grade == Decimal("10")
    assert p.finish is None


def _card(**overrides):
    kwargs = dict(
        card_id="en:base1-4", name="Charizard", set_id="en:base1", set_name="Base Set",
        number="4", last_synced_at=datetime(2026, 7, 26, 12, 0, 0),
    )
    kwargs.update(overrides)
    return CatalogCard(**kwargs)


def test_catalog_card_language_defaults_to_english_for_pre_existing_rows():
    """Rows written before the field existed must still validate (RFC 0003 §4)."""
    assert _card().language is Language.EN
    assert _card(language="JP").language is Language.JP


def test_catalog_card_images_default_to_empty_strings():
    """JP rows frequently carry no image at all; absence is not an error."""
    card = _card()
    assert card.images.small == ""
    assert card.images.large == ""


def test_catalog_card_detail_defaults_to_brief():
    assert _card().detail == "brief"
    assert _card(detail="full").detail == "full"


def test_finish_price_is_usd_and_records_its_provenance():
    band = FinishPrice(
        market=Decimal("13.50"), low=Decimal("10.80"), source="cardmarket",
        source_currency="EUR", value_note="converted from EUR 12.50",
    )
    assert band.currency == "USD"
    assert band.source == "cardmarket"
    assert band.source_currency == "EUR"
    assert band.high is None
    # a band written before provenance existed still validates
    assert FinishPrice(market=Decimal("1")).source is None


def test_price_point_records_currency_and_conversion_note():
    p = PricePoint(
        card_id="ja:M5-001", date="2026-07-26", source="cardmarket", kind="raw",
        finish="normal", market=Decimal("0.03"), source_currency="EUR",
        value_note="converted from EUR 0.03 (cardmarket trend) at EUR_USD_RATE=1.08",
    )
    assert p.currency == "USD"
    assert p.source_currency == "EUR"
    assert "EUR_USD_RATE" in p.value_note
    # graded points keep their existing shape, defaulting to USD
    assert PricePoint(card_id="c", date="2026-07-26", source="manual",
                      kind="graded", company="PSA", grade=Decimal("10")).currency == "USD"
