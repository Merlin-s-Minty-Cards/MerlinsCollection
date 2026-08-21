"""RED tests for trusted repository hydration of model-supplied item IDs."""

from datetime import date, datetime, timezone
from decimal import Decimal

from merlins_collection.models.catalog import CardImages, CatalogCard, FinishPrice
from merlins_collection.models.inventory import (
    Condition,
    ConditionModifier,
    GradedInventoryItem,
    GradingCompany,
    ItemStatus,
    RawInventoryItem,
    SealedInventoryItem,
    SealedProductType,
)
from merlins_collection.services import bedrock


def _hydrate(repo, item_id: str):
    assert hasattr(bedrock, "_hydrate_item"), "RFC 0016 _hydrate_item is not implemented"
    return bedrock._hydrate_item(repo, item_id)


def _catalog(card_id: str = "en:base1-4", *, prices=None) -> CatalogCard:
    return CatalogCard(
        card_id=card_id,
        name="Charizard",
        set_id="base1",
        set_name="Base Set",
        number="4",
        rarity="Rare Holo",
        images=CardImages(
            small="https://assets.tcgdex.net/en/base/base1/4/low.webp",
            large="https://assets.tcgdex.net/en/base/base1/4/high.webp",
        ),
        prices=prices or {},
        last_synced_at=datetime.now(tz=timezone.utc),
    )


def _raw(
    *,
    item_id: str = "raw-1",
    card_id: str | None = "en:base1-4",
    status: ItemStatus = ItemStatus.AVAILABLE,
    finish: str = "holofoil",
) -> RawInventoryItem:
    return RawInventoryItem(
        item_id=item_id,
        card_id=card_id,
        status=status,
        listed_price=Decimal("275.00"),
        current_market_value=Decimal("450.00"),
        cost_basis=Decimal("100.00"),
        acquired_at=date.today(),
        finish=finish,
        condition=Condition.NM,
        condition_modifier=ConditionModifier.PLUS,
        display_name="Charizard #4",
    )


def _graded(*, item_id: str = "graded-1") -> GradedInventoryItem:
    return GradedInventoryItem(
        item_id=item_id,
        card_id="en:base1-4",
        listed_price=Decimal("900.00"),
        current_market_value=Decimal("850.00"),
        cost_basis=Decimal("500.00"),
        acquired_at=date.today(),
        company=GradingCompany.PSA,
        grade=Decimal("9.5"),
        grade_label="MINT 9.5",
        cert_number="12345678",
        cert_image_url="https://example.com/cert.jpg",
    )


def test_hydrates_available_raw_item_from_repository(dynamo_repo):
    item = _raw()
    dynamo_repo.put_inventory_item(item)

    displayed = _hydrate(dynamo_repo, item.item_id)

    assert displayed.item_id == item.item_id
    assert displayed.kind == "raw"
    assert displayed.listed_price == Decimal("275.00")
    assert displayed.current_market_value == Decimal("450.00")
    assert displayed.finish == "holofoil"


def test_hydrates_available_graded_item_from_repository(dynamo_repo):
    item = _graded()
    dynamo_repo.put_inventory_item(item)

    displayed = _hydrate(dynamo_repo, item.item_id)

    assert displayed.kind == "graded"
    assert displayed.company == "PSA"
    assert displayed.grade == Decimal("9.5")
    assert displayed.grade_label == "MINT 9.5"
    assert displayed.cert_number == "12345678"
    assert displayed.cert_image_url == "https://example.com/cert.jpg"


def test_hydration_returns_none_for_unknown_item_id(dynamo_repo):
    assert _hydrate(dynamo_repo, "missing-item") is None


def test_hydration_returns_none_for_sold_item(dynamo_repo):
    sold = _raw(item_id="sold-1", status=ItemStatus.SOLD)
    dynamo_repo.put_inventory_item(sold)

    assert _hydrate(dynamo_repo, sold.item_id) is None


def test_hydration_populates_catalog_projection_when_card_id_resolves(dynamo_repo):
    catalog = _catalog()
    item = _raw()
    dynamo_repo.batch_upsert_catalog_cards([catalog])
    dynamo_repo.put_inventory_item(item)

    displayed = _hydrate(dynamo_repo, item.item_id)

    assert displayed.card.model_dump() == {
        "card_id": "en:base1-4",
        "name": "Charizard",
        "set_id": "base1",
        "set_name": "Base Set",
        "number": "4",
        "rarity": "Rare Holo",
        "image_small": "https://assets.tcgdex.net/en/base/base1/4/low.webp",
        "image_large": "https://assets.tcgdex.net/en/base/base1/4/high.webp",
        "market_price": None,
    }


def test_hydration_has_no_catalog_projection_for_sealed_item(dynamo_repo):
    sealed = SealedInventoryItem(
        item_id="sealed-1",
        product_name="Base Set Booster Box",
        product_type=SealedProductType.BOOSTER_BOX,
        listed_price=Decimal("12000.00"),
        cost_basis=Decimal("5000.00"),
        acquired_at=date.today(),
    )
    dynamo_repo.put_inventory_item(sealed)

    assert _hydrate(dynamo_repo, sealed.item_id).card is None


def test_hydration_has_no_catalog_projection_for_orphaned_card_id(dynamo_repo):
    orphan = _raw(item_id="orphan-1", card_id="en:missing-1")
    dynamo_repo.put_inventory_item(orphan)

    assert _hydrate(dynamo_repo, orphan.item_id).card is None


def test_hydration_combines_raw_condition_and_modifier(dynamo_repo):
    item = _raw()
    dynamo_repo.put_inventory_item(item)

    assert _hydrate(dynamo_repo, item.item_id).condition == "NM+"


def test_hydration_uses_exact_finish_market_price(dynamo_repo):
    dynamo_repo.batch_upsert_catalog_cards([
        _catalog(prices={
            "normal": FinishPrice(market=Decimal("300.00")),
            "holofoil": FinishPrice(market=Decimal("450.00")),
        })
    ])
    item = _raw(finish="holofoil")
    dynamo_repo.put_inventory_item(item)

    assert _hydrate(dynamo_repo, item.item_id).card.market_price == Decimal("450.00")


def test_hydration_falls_back_to_an_available_finish_market_price(dynamo_repo):
    dynamo_repo.batch_upsert_catalog_cards([
        _catalog(prices={"reverseHolofoil": FinishPrice(market=Decimal("325.00"))})
    ])
    item = _raw(finish="holofoil")
    dynamo_repo.put_inventory_item(item)

    assert _hydrate(dynamo_repo, item.item_id).card.market_price == Decimal("325.00")
