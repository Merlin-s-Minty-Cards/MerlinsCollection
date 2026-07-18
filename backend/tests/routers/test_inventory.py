from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from merlins_collection.models.catalog import CardImages, CatalogCard
from merlins_collection.models.inventory import (
    BulkInventoryItem,
    Condition,
    ConsignmentTerms,
    GradedInventoryItem,
    GradingCompany,
    RawInventoryItem,
    SealedInventoryItem,
)

# ---- seed helpers ----

def _catalog(card_id, name, *, set_id="sv1", set_name="Scarlet & Violet", rarity="Common"):
    return CatalogCard(
        card_id=card_id,
        name=name,
        set_id=set_id,
        set_name=set_name,
        number="001",
        rarity=rarity,
        images=CardImages(
            small="https://images.pokemontcg.io/sv1/1_hires.png",
            large="https://images.pokemontcg.io/sv1/1_hires.png",
        ),
        last_synced_at=datetime.now(tz=timezone.utc),
    )


def _raw(card_id, *, condition=Condition.NM, price="10.00", finish="holofoil", **extra):
    return RawInventoryItem(
        card_id=card_id,
        listed_price=Decimal(price),
        cost_basis=Decimal("5.00"),
        acquired_at=date.today(),
        finish=finish,
        condition=condition,
        **extra,
    )


def _graded(card_id, *, grade="9", price="50.00"):
    return GradedInventoryItem(
        card_id=card_id,
        listed_price=Decimal(price),
        cost_basis=Decimal("30.00"),
        acquired_at=date.today(),
        company=GradingCompany.PSA,
        grade=Decimal(grade),
        cert_number="12345678",
    )


# ---- fixture ----

@pytest.fixture
def inv_client(cognito_config, jwks, dynamo_repo):
    """TestClient with auth and repo both overridden."""
    from merlins_collection.dependencies import get_repo, get_verifier
    from merlins_collection.main import app
    from merlins_collection.services.cognito import CognitoJwtVerifier

    verifier = CognitoJwtVerifier(
        region=cognito_config["region"],
        user_pool_id=cognito_config["user_pool_id"],
        client_id=cognito_config["client_id"],
        jwks=jwks,
    )
    app.dependency_overrides[get_verifier] = lambda: verifier
    app.dependency_overrides[get_repo] = lambda: dynamo_repo
    yield TestClient(app), dynamo_repo
    app.dependency_overrides.clear()


# ---- tests ----

def test_search_requires_authentication(inv_client):
    client, _ = inv_client
    resp = client.get("/inventory/search")
    assert resp.status_code == 401


def test_search_returns_all_items_when_no_filters(inv_client, mint_token):
    client, repo = inv_client
    repo.put_inventory_item(_raw("sv1-1"))
    repo.put_inventory_item(_graded("sv1-2"))

    resp = client.get(
        "/inventory/search",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2


def test_search_filters_by_condition_keeps_only_matching_raw_items(inv_client, mint_token):
    client, repo = inv_client
    repo.put_inventory_item(_raw("sv1-1", condition=Condition.NM))
    repo.put_inventory_item(_raw("sv1-2", condition=Condition.LP))
    repo.put_inventory_item(_graded("sv1-3"))  # graded — excluded when condition filter is set

    resp = client.get(
        "/inventory/search?condition=NM",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["card_id"] == "sv1-1"


def test_search_filters_by_min_price(inv_client, mint_token):
    client, repo = inv_client
    repo.put_inventory_item(_raw("sv1-cheap", price="5.00"))
    repo.put_inventory_item(_raw("sv1-pricey", price="20.00"))

    resp = client.get(
        "/inventory/search?min_price=10.00",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["card_id"] == "sv1-pricey"


def test_search_filters_by_max_price(inv_client, mint_token):
    client, repo = inv_client
    repo.put_inventory_item(_raw("sv1-cheap", price="5.00"))
    repo.put_inventory_item(_raw("sv1-pricey", price="20.00"))

    resp = client.get(
        "/inventory/search?max_price=10.00",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["card_id"] == "sv1-cheap"


def test_search_rejects_inverted_price_range(inv_client, mint_token):
    client, _ = inv_client
    resp = client.get(
        "/inventory/search?min_price=100.00&max_price=10.00",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 422


def test_search_filters_by_set_id(inv_client, mint_token):
    client, repo = inv_client
    repo.batch_upsert_catalog_cards([
        _catalog("sv1-1", "Sprigatito", set_id="sv1"),
        _catalog("sv2-1", "Fuecoco", set_id="sv2"),
    ])
    repo.put_inventory_item(_raw("sv1-1"))
    repo.put_inventory_item(_raw("sv2-1"))

    resp = client.get(
        "/inventory/search?set_id=sv1",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["card_id"] == "sv1-1"


def test_search_filters_by_name_case_insensitive_substring(inv_client, mint_token):
    client, repo = inv_client
    repo.batch_upsert_catalog_cards([
        _catalog("sv1-1", "Sprigatito"),
        _catalog("sv1-2", "Floragato"),
    ])
    repo.put_inventory_item(_raw("sv1-1"))
    repo.put_inventory_item(_raw("sv1-2"))

    resp = client.get(
        "/inventory/search?name=sprig",  # lowercase — must match "Sprigatito"
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["card_id"] == "sv1-1"


def test_search_filters_by_rarity(inv_client, mint_token):
    client, repo = inv_client
    repo.batch_upsert_catalog_cards([
        _catalog("sv1-1", "Sprigatito", rarity="Common"),
        _catalog("sv1-2", "Mewtwo ex", rarity="Double Rare"),
    ])
    repo.put_inventory_item(_raw("sv1-1"))
    repo.put_inventory_item(_raw("sv1-2"))

    resp = client.get(
        "/inventory/search?rarity=Common",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["card_id"] == "sv1-1"


def test_search_excludes_orphaned_items_when_name_filter_is_active(inv_client, mint_token):
    """An inventory item with no matching catalog card is excluded when a name filter is applied."""
    client, repo = inv_client
    repo.put_inventory_item(_raw("sv1-orphan"))  # no catalog entry

    resp = client.get(
        "/inventory/search?name=sprig",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    body = resp.json()
    assert body["total"] == 0


def test_search_price_range_boundary_min_equals_max(inv_client, mint_token):
    """min_price == max_price is valid and returns items at exactly that price."""
    client, repo = inv_client
    repo.put_inventory_item(_raw("sv1-exact", price="10.00"))
    repo.put_inventory_item(_raw("sv1-other", price="9.99"))

    resp = client.get(
        "/inventory/search?min_price=10.00&max_price=10.00",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["card_id"] == "sv1-exact"


def test_search_combined_name_and_rarity_both_must_match(inv_client, mint_token):
    """Both name and rarity filters must match; a card satisfying only one is excluded."""
    client, repo = inv_client
    repo.batch_upsert_catalog_cards([
        _catalog("sv1-1", "Sprigatito", rarity="Common"),
        _catalog("sv1-2", "Sprigatito ex", rarity="Double Rare"),  # name matches, rarity does not
        _catalog("sv1-3", "Mewtwo ex", rarity="Common"),           # rarity matches, name does not
    ])
    repo.put_inventory_item(_raw("sv1-1"))
    repo.put_inventory_item(_raw("sv1-2"))
    repo.put_inventory_item(_raw("sv1-3"))

    resp = client.get(
        "/inventory/search?name=sprigatito&rarity=Common",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["card_id"] == "sv1-1"


def test_search_set_id_with_no_matching_inventory_returns_empty(inv_client, mint_token):
    """A set that has catalog cards but no inventory items returns an empty result."""
    client, repo = inv_client
    repo.batch_upsert_catalog_cards([_catalog("sv1-1", "Sprigatito", set_id="sv1")])
    # no inventory items seeded

    resp = client.get(
        "/inventory/search?set_id=sv1",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    body = resp.json()
    assert body["total"] == 0
    assert body["items"] == []


def test_search_condition_excludes_graded_items_even_when_price_matches(inv_client, mint_token):
    """A graded item matching the price range is still excluded when a condition filter is set."""
    client, repo = inv_client
    repo.put_inventory_item(_raw("sv1-raw", condition=Condition.NM, price="50.00"))
    repo.put_inventory_item(_graded("sv1-graded", price="50.00"))  # same price, but graded

    resp = client.get(
        "/inventory/search?condition=NM&min_price=40.00&max_price=60.00",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["card_id"] == "sv1-raw"


def test_search_items_include_card_catalog_summary(inv_client, mint_token):
    """Items are enriched with the catalog data the UI needs (name, set, image)."""
    client, repo = inv_client
    repo.batch_upsert_catalog_cards([
        _catalog("sv1-1", "Sprigatito", set_id="sv1", set_name="Scarlet & Violet",
                 rarity="Common"),
    ])
    repo.put_inventory_item(_raw("sv1-1"))

    resp = client.get(
        "/inventory/search",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200
    card = resp.json()["items"][0]["card"]
    assert card["name"] == "Sprigatito"
    assert card["set_id"] == "sv1"
    assert card["set_name"] == "Scarlet & Violet"
    assert card["number"] == "001"
    assert card["rarity"] == "Common"
    assert card["image_small"] == "https://images.pokemontcg.io/sv1/1_hires.png"


def test_search_item_card_is_null_when_catalog_missing(inv_client, mint_token):
    """An inventory item with no synced catalog row still returns, with card=null."""
    client, repo = inv_client
    repo.put_inventory_item(_raw("sv1-orphan"))

    resp = client.get(
        "/inventory/search",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["card"] is None


def test_search_enriches_items_when_name_filter_already_loaded_catalog(inv_client, mint_token):
    """Enrichment also works on the filter path that fetches catalog rows itself."""
    client, repo = inv_client
    repo.batch_upsert_catalog_cards([_catalog("sv1-1", "Sprigatito")])
    repo.put_inventory_item(_raw("sv1-1"))

    resp = client.get(
        "/inventory/search?name=sprig",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["card"]["name"] == "Sprigatito"


def test_search_response_serializes_decimals_as_strings(inv_client, mint_token):
    """Pins the wire format the frontend relies on: Decimal fields are JSON strings."""
    client, repo = inv_client
    item = _raw("sv1-1", price="10.00")
    item.current_market_value = Decimal("12.50")
    repo.put_inventory_item(item)
    repo.put_inventory_item(_graded("sv1-2", grade="9.5", price="50.00"))

    resp = client.get(
        "/inventory/search",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    by_id = {i["card_id"]: i for i in resp.json()["items"]}
    assert by_id["sv1-1"]["listed_price"] == "10.00"
    assert by_id["sv1-1"]["current_market_value"] == "12.50"
    assert by_id["sv1-2"]["grade"] == "9.5"


def test_search_excludes_bulk_and_non_available_items(inv_client, mint_token):
    client, repo = inv_client
    repo.put_inventory_item(_raw("sv1-sold", status="sold"))
    repo.put_inventory_item(_raw("sv1-hold", status="on_hold"))
    repo.put_inventory_item(BulkInventoryItem(
        description="lot", cost_basis=Decimal("5"), acquired_at=date(2026, 1, 1)))
    available = _raw("sv1-ok")
    repo.put_inventory_item(available)

    body = client.get(
        "/inventory/search",
        headers={"Authorization": f"Bearer {mint_token()}"},
    ).json()
    assert [i["item_id"] for i in body["items"]] == [available.item_id]


def test_search_returns_sealed_products_with_null_card(inv_client, mint_token):
    client, repo = inv_client
    sealed = SealedInventoryItem(product_name="ES Booster Box", product_type="booster_box",
                                 cost_basis=Decimal("400"), listed_price=Decimal("550"),
                                 acquired_at=date(2026, 1, 1))
    repo.put_inventory_item(sealed)

    body = client.get(
        "/inventory/search",
        headers={"Authorization": f"Bearer {mint_token()}"},
    ).json()
    match = next(i for i in body["items"] if i["kind"] == "sealed")
    assert match["product_name"] == "ES Booster Box"
    assert match["card"] is None


def test_condition_filter_matches_modifier_variants(inv_client, mint_token):
    client, repo = inv_client
    repo.put_inventory_item(_raw("sv1-1", condition=Condition.LP, condition_modifier="+"))
    repo.put_inventory_item(_raw("sv1-2", condition=Condition.LP, condition_modifier="-"))
    repo.put_inventory_item(_raw("sv1-3", condition=Condition.NM))

    body = client.get(
        "/inventory/search?condition=LP",
        headers={"Authorization": f"Bearer {mint_token()}"},
    ).json()
    assert body["total"] == 2


def test_price_filter_falls_back_to_market_value(inv_client, mint_token):
    client, repo = inv_client
    repo.put_inventory_item(_raw("sv1-1", price="30"))
    no_sticker = _raw("sv1-2")
    no_sticker.listed_price = None
    no_sticker.current_market_value = Decimal("80")
    repo.put_inventory_item(no_sticker)
    no_price = _raw("sv1-3")
    no_price.listed_price = None
    repo.put_inventory_item(no_price)

    body = client.get(
        "/inventory/search?min_price=50",
        headers={"Authorization": f"Bearer {mint_token()}"},
    ).json()
    assert body["total"] == 1


def test_response_strips_internal_fields(inv_client, mint_token):
    client, repo = inv_client
    terms = ConsignmentTerms(consignor_id="c-1", split_percent=Decimal("20"))
    repo.put_inventory_item(_raw("sv1-1", consignment=terms, needs_review=True))

    item = client.get(
        "/inventory/search",
        headers={"Authorization": f"Bearer {mint_token()}"},
    ).json()["items"][0]
    assert "cost_basis" not in item
    assert "consignment" not in item
    assert "needs_review" not in item


def test_search_response_does_not_expose_cost_basis(inv_client, mint_token):
    """cost_basis (purchase price) is internal data and must not appear in search results."""
    client, repo = inv_client
    repo.put_inventory_item(_raw("sv1-1"))

    resp = client.get(
        "/inventory/search",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    body = resp.json()
    assert body["total"] == 1
    assert "cost_basis" not in body["items"][0]
