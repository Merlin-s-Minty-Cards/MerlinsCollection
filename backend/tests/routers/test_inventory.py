from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from merlins_collection.models.catalog import CardImages, CatalogCard
from merlins_collection.models.inventory import (
    Condition,
    GradedInventoryItem,
    GradingCompany,
    RawInventoryItem,
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


def _raw(card_id, *, condition=Condition.NM, price="10.00", finish="holofoil"):
    return RawInventoryItem(
        card_id=card_id,
        quantity=1,
        listed_price=Decimal(price),
        cost_basis=Decimal("5.00"),
        acquired_at=date.today(),
        finish=finish,
        condition=condition,
    )


def _graded(card_id, *, grade="9", price="50.00"):
    return GradedInventoryItem(
        card_id=card_id,
        quantity=1,
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
