from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from merlins_collection.models.catalog import CardImages, CatalogCard, FinishPrice
from merlins_collection.models.inventory import (
    BulkInventoryItem,
    Condition,
    ConsignmentTerms,
    GradedInventoryItem,
    GradingCompany,
    ItemStatus,
    Language,
    RawInventoryItem,
    SealedInventoryItem,
)

# ---- seed helpers ----

def _catalog(card_id, name, *, set_id="sv1", set_name="Scarlet & Violet", rarity="Common",
             prices=None):
    return CatalogCard(
        card_id=card_id,
        name=name,
        set_id=set_id,
        set_name=set_name,
        number="001",
        rarity=rarity,
        images=CardImages(
            small="https://assets.tcgdex.net/en/sv/sv01/1/high.webp",
            large="https://assets.tcgdex.net/en/sv/sv01/1/high.webp",
        ),
        last_synced_at=datetime.now(tz=timezone.utc),
        # `prices` is keyed by internal finish name (Phase 12: exercises the
        # finish-aware fallback chain, models/inventory.py:199-233).
        prices=prices or {},
    )


def _raw(card_id, *, condition=Condition.NM, price="10.00", finish="holofoil", location="glass", **extra):
    return RawInventoryItem(
        card_id=card_id,
        listed_price=Decimal(price),
        cost_basis=Decimal("5.00"),
        acquired_at=date.today(),
        finish=finish,
        condition=condition,
        location=location,
        **extra,
    )


def _graded(card_id, *, grade="9", price="50.00", location="glass"):
    return GradedInventoryItem(
        card_id=card_id,
        listed_price=Decimal(price),
        cost_basis=Decimal("30.00"),
        acquired_at=date.today(),
        company=GradingCompany.PSA,
        grade=Decimal(grade),
        cert_number="12345678",
        location=location,
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
    # PHASE 12 (D3): the price predicate reads `current_market_value`, not the
    # permanently-dead `listed_price` (null on every live item by owner
    # decision), so a price fixture has to seed the field the filter reads.
    repo.put_inventory_item(_raw("sv1-cheap", price="5.00", current_market_value=Decimal("5.00")))
    repo.put_inventory_item(_raw("sv1-pricey", price="20.00", current_market_value=Decimal("20.00")))

    resp = client.get(
        "/inventory/search?min_price=10.00",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["card_id"] == "sv1-pricey"


def test_search_filters_by_max_price(inv_client, mint_token):
    client, repo = inv_client
    # See the Phase 12 (D3) note on test_search_filters_by_min_price above.
    repo.put_inventory_item(_raw("sv1-cheap", price="5.00", current_market_value=Decimal("5.00")))
    repo.put_inventory_item(_raw("sv1-pricey", price="20.00", current_market_value=Decimal("20.00")))

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
    # See the Phase 12 (D3) note on test_search_filters_by_min_price above.
    repo.put_inventory_item(_raw("sv1-exact", price="10.00", current_market_value=Decimal("10.00")))
    repo.put_inventory_item(_raw("sv1-other", price="9.99", current_market_value=Decimal("9.99")))

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
    # See the Phase 12 (D3) note on test_search_filters_by_min_price above: both
    # items carry the market value the price predicate actually reads, so the
    # graded item is proven excluded by the CONDITION filter and not merely by
    # having no price the bound could match.
    repo.put_inventory_item(_raw(
        "sv1-raw", condition=Condition.NM, price="50.00",
        current_market_value=Decimal("50.00"),
    ))
    slab = _graded("sv1-graded", price="50.00")  # same price, but graded
    slab.current_market_value = Decimal("50.00")
    repo.put_inventory_item(slab)

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
    assert card["image_small"] == "https://assets.tcgdex.net/en/sv/sv01/1/high.webp"


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


# ---- GET /inventory/summary (authenticated dashboard stats) ----

def test_summary_requires_authentication(inv_client):
    client, _ = inv_client
    resp = client.get("/inventory/summary")
    assert resp.status_code == 401


def test_summary_empty_inventory_returns_zeroes(inv_client, mint_token):
    client, _ = inv_client
    resp = client.get(
        "/inventory/summary",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"cards_in_vault": 0, "est_value": "0", "sets_tracked": 0}


def test_summary_counts_only_available_customer_items(inv_client, mint_token):
    client, repo = inv_client
    repo.put_inventory_item(_raw("sv1-1"))                                   # available raw
    repo.put_inventory_item(_graded("sv1-2"))                               # available graded
    sold = _raw("sv1-3")
    sold.status = ItemStatus.SOLD
    repo.put_inventory_item(sold)                                            # sold — excluded
    held = _raw("sv1-4")
    held.status = ItemStatus.ON_HOLD
    repo.put_inventory_item(held)                                            # on_hold — excluded
    repo.put_inventory_item(SealedInventoryItem(
        product_name="Booster Box", product_type="booster_box",
        cost_basis=Decimal("50.00"), acquired_at=date.today(),
    ))                                                                       # sealed — excluded
    repo.put_inventory_item(BulkInventoryItem(
        description="Bulk lot", cost_basis=Decimal("5.00"), acquired_at=date.today(),
    ))                                                                       # bulk — excluded

    resp = client.get(
        "/inventory/summary",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.json()["cards_in_vault"] == 2


def test_summary_est_value_prefers_market_over_listed(inv_client, mint_token):
    client, repo = inv_client
    # both prices set -> uses current_market_value (market-first, opposite of _price)
    both = _raw("sv1-1", price="10.00")
    both.current_market_value = Decimal("12.50")
    repo.put_inventory_item(both)
    # only listed_price -> uses listed_price
    repo.put_inventory_item(_raw("sv1-2", price="20.00"))
    # neither price -> skipped from the sum
    neither = RawInventoryItem(
        card_id="sv1-3", listed_price=None, current_market_value=None,
        cost_basis=Decimal("5.00"), acquired_at=date.today(),
        finish="holofoil", condition=Condition.NM, location="glass",
    )
    repo.put_inventory_item(neither)

    resp = client.get(
        "/inventory/summary",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    body = resp.json()
    assert body["cards_in_vault"] == 3
    assert body["est_value"] == "32.50"  # 12.50 (market) + 20.00 (listed) + 0 (skipped)


def test_summary_sets_tracked_counts_distinct_catalog_sets(inv_client, mint_token):
    client, repo = inv_client
    repo.batch_upsert_catalog_cards([
        _catalog("sv1-1", "Sprigatito", set_id="sv1"),
        _catalog("sv1-2", "Floragato", set_id="sv1"),   # same set
        _catalog("sv2-1", "Fuecoco", set_id="sv2"),     # different set
    ])
    repo.put_inventory_item(_raw("sv1-1"))
    repo.put_inventory_item(_raw("sv1-2"))
    repo.put_inventory_item(_raw("sv2-1"))
    # A NULL-card_id item contributes no set.
    orphan = RawInventoryItem(
        card_id=None, listed_price=Decimal("5.00"),
        cost_basis=Decimal("2.00"), acquired_at=date.today(),
        finish="holofoil", condition=Condition.NM, location="glass",
    )
    repo.put_inventory_item(orphan)

    resp = client.get(
        "/inventory/summary",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    body = resp.json()
    assert body["cards_in_vault"] == 4
    assert body["sets_tracked"] == 2


def test_summary_serializes_est_value_as_string(inv_client, mint_token):
    """Pins the wire contract: est_value is a Decimal serialized as a string."""
    client, repo = inv_client
    item = _raw("sv1-1", price="10.00")
    item.current_market_value = Decimal("100.00")
    repo.put_inventory_item(item)

    resp = client.get(
        "/inventory/summary",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.json()["est_value"] == "100.00"


def test_summary_carries_a_rate_cap(inv_client, mint_token):
    """The summary is as heavy as search, so it must be throttled too (Council item 5)."""
    from merlins_collection.main import app
    from merlins_collection.rate_limit import RateLimitResult, get_rate_limiter

    class _AlwaysLimited:
        def check(self, tiers, *, now=None):
            return RateLimitResult(limited=True, retry_after=30)

    client, _ = inv_client
    app.dependency_overrides[get_rate_limiter] = lambda: _AlwaysLimited()
    try:
        resp = client.get(
            "/inventory/summary",
            headers={"Authorization": f"Bearer {mint_token()}"},
        )
        assert resp.status_code == 429
    finally:
        app.dependency_overrides.pop(get_rate_limiter, None)


# ---- customer_visible_items shared cohort helper (Council item 6) ----

def test_customer_visible_items_filters_to_available_raw_and_graded(dynamo_repo):
    """One shared predicate for the security boundary used by search, summary, and
    the public featured endpoint."""
    from merlins_collection.routers.inventory import customer_visible_items

    dynamo_repo.put_inventory_item(_raw("sv1-1"))                       # available raw ✓
    dynamo_repo.put_inventory_item(_graded("sv1-2"))                    # available graded ✓
    sold = _raw("sv1-3")
    sold.status = ItemStatus.SOLD
    dynamo_repo.put_inventory_item(sold)                               # sold ✗
    dynamo_repo.put_inventory_item(SealedInventoryItem(
        product_name="Booster Box", product_type="booster_box",
        cost_basis=Decimal("50.00"), acquired_at=date.today(),
    ))                                                                 # sealed ✗
    dynamo_repo.put_inventory_item(BulkInventoryItem(
        description="Bulk", cost_basis=Decimal("5.00"), acquired_at=date.today(),
    ))                                                                 # bulk ✗

    items = customer_visible_items(dynamo_repo)

    assert len(items) == 2
    assert all(i.kind in {"raw", "graded"} and i.status is ItemStatus.AVAILABLE for i in items)


def test_customer_visible_items_excludes_items_without_visible_location(dynamo_repo):
    """Phase 5 (D3, display scoping): an available raw item with no visible
    location (location=None, factory_sealed=False) must NOT be customer-visible,
    even though it passes the kind+status gate. An item stored with a
    customer-visible location ("glass") still appears."""
    from merlins_collection.routers.inventory import customer_visible_items

    no_location = _raw("sv1-none")
    no_location.location = None
    no_location.factory_sealed = False
    dynamo_repo.put_inventory_item(no_location)                        # ✗ no visible location

    in_glass = _raw("sv1-glass")
    in_glass.location = "glass"
    dynamo_repo.put_inventory_item(in_glass)                           # ✓ visible location

    items = customer_visible_items(dynamo_repo)

    assert [i.card_id for i in items] == ["sv1-glass"]


def test_customer_visible_items_includes_all_visible_locations(dynamo_repo):
    """glass, toploader, and factory_sealed=True (location=None) are all
    visible; a non-visible location string (e.g. "storage") is excluded."""
    from merlins_collection.routers.inventory import customer_visible_items

    glass = _raw("sv1-glass")
    glass.location = "glass"
    dynamo_repo.put_inventory_item(glass)                               # ✓

    toploader = _raw("sv1-toploader")
    toploader.location = "toploader"
    dynamo_repo.put_inventory_item(toploader)                           # ✓

    sealed = _raw("sv1-sealed")
    sealed.location = None
    sealed.factory_sealed = True
    dynamo_repo.put_inventory_item(sealed)                              # ✓

    storage = _raw("sv1-storage")
    storage.location = "storage"
    dynamo_repo.put_inventory_item(storage)                             # ✗ not a visible location

    items = customer_visible_items(dynamo_repo)

    assert {i.card_id for i in items} == {"sv1-glass", "sv1-toploader", "sv1-sealed"}


def test_customer_visible_items_factory_sealed_is_visible(dynamo_repo):
    """The Sealed special case (D3): the importer stores factory_sealed=True with
    location=None for sheet rows whose location was "Sealed" — it's a condition
    premium, not a physical place — and such items must still be visible."""
    from merlins_collection.routers.inventory import customer_visible_items

    item = _raw("sv1-1")
    item.location = None
    item.factory_sealed = True
    dynamo_repo.put_inventory_item(item)

    items = customer_visible_items(dynamo_repo)

    assert [i.card_id for i in items] == ["sv1-1"]


def test_search_excludes_items_without_visible_location(inv_client, mint_token):
    """End-to-end: /inventory/search returns 0 results for an AVAILABLE raw item
    with no visible location and no factory_sealed flag."""
    client, repo = inv_client
    item = _raw("sv1-1")
    item.location = None
    item.factory_sealed = False
    repo.put_inventory_item(item)

    resp = client.get(
        "/inventory/search",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


def test_summary_counts_only_location_visible_items(inv_client, mint_token):
    """/inventory/summary's cards_in_vault reflects the location gate too: an
    available raw item with no visible location does not count."""
    client, repo = inv_client
    visible = _raw("sv1-glass")
    visible.location = "glass"
    repo.put_inventory_item(visible)

    hidden = _raw("sv1-hidden")
    hidden.location = None
    hidden.factory_sealed = False
    repo.put_inventory_item(hidden)

    resp = client.get(
        "/inventory/summary",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.json()["cards_in_vault"] == 1


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


def test_search_excludes_sealed_items_from_customer_results(inv_client, mint_token):
    """RFC 0001 owner decision (binding, overrides the earlier "keep sealed
    visible" recommendation): sealed products (kind=sealed, e.g. booster
    packs) are hidden from the customer-facing search entirely — cards-only
    surface. "sealed" must be removed from `_CUSTOMER_KINDS`
    (backend inventory.py:35). (fails now: sealed items are still returned)"""
    client, repo = inv_client
    sealed = SealedInventoryItem(product_name="ES Booster Box", product_type="booster_box",
                                 cost_basis=Decimal("400"), listed_price=Decimal("550"),
                                 acquired_at=date(2026, 1, 1))
    repo.put_inventory_item(sealed)
    repo.put_inventory_item(_raw("sv1-1"))  # control: a card-kind item still returns

    body = client.get(
        "/inventory/search",
        headers={"Authorization": f"Bearer {mint_token()}"},
    ).json()
    assert body["total"] == 1
    assert all(i["kind"] != "sealed" for i in body["items"])


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


def test_price_filter_matches_on_the_live_catalog_price(inv_client, mint_token):
    """RE-REASONED TWICE, and the second reversal is the one that matters.

    Phase 12 retitled this from ``..._falls_back_to_market_value`` to pin
    ``current_market_value`` as the price predicate outright. RFC 0008 §A/T1
    took that authority away again: the denormalized field is rewritten only by
    the nightly sync and therefore disagrees with the price the tile renders
    between runs, which is precisely how a $517 card passed ``max_price=500``.
    The predicate is now ``_display_price`` — the live catalog figure.

    Three items, ``min_price=50``. Only the one the CUSTOMER sees above the bound
    survives, and its stale $10 is ignored rather than hiding it."""
    client, repo = inv_client
    repo.batch_upsert_catalog_cards([
        _catalog("sv1-2", "Sprigatito",
                 prices={"holofoil": FinishPrice(market=Decimal("80"))}),
    ])
    repo.put_inventory_item(_raw("sv1-1", price="30"))  # displays $30 — under the bound
    live_priced = _raw("sv1-2")
    live_priced.listed_price = None
    live_priced.current_market_value = Decimal("10")  # stale, and deliberately wrong
    repo.put_inventory_item(live_priced)
    no_price = _raw("sv1-3")
    no_price.listed_price = None
    repo.put_inventory_item(no_price)

    body = client.get(
        "/inventory/search?min_price=50",
        headers={"Authorization": f"Bearer {mint_token()}"},
    ).json()
    assert body["total"] == 1
    assert body["items"][0]["card_id"] == "sv1-2"


# Two narrower projection tests used to sit here — ``test_response_strips_
# internal_fields`` (3 keys) and ``test_search_response_does_not_expose_cost_
# basis`` (1 key). Both are subsumed by ``test_B9_search_response_omits_internal_
# fields`` below, which asserts an 8-key allowlist is disjoint from the response.
# B9 now seeds ``consignment``/``needs_review``/``tcg_url`` explicitly, which is
# the one thing it was missing when those two were folded into it.


# ---- language (EN/JP) support ----

def test_search_response_includes_language_defaulting_to_en(inv_client, mint_token):
    """Every result carries a ``language`` field; an item with no stored
    language surfaces as EN (the model default)."""
    client, repo = inv_client
    repo.put_inventory_item(_raw("sv1-1"))  # no language set → defaults to EN

    resp = client.get(
        "/inventory/search",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert item["language"] == "EN"


def test_search_filters_by_language_jp_returns_only_jp(inv_client, mint_token):
    """language=JP returns only JP items, even though a JP item has no card_id
    (card_id is None by design — no English catalog match is possible)."""
    client, repo = inv_client
    repo.put_inventory_item(_raw("sv1-en"))  # EN (default)
    jp = _raw(None, language=Language.JP)     # JP, card_id=None by design
    repo.put_inventory_item(jp)

    resp = client.get(
        "/inventory/search?language=JP",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["item_id"] == jp.item_id
    assert body["items"][0]["language"] == "JP"


def test_search_filters_by_language_en_includes_items_without_stored_language(
    inv_client, mint_token,
):
    """language=EN returns EN items — including items with no stored language,
    which default to EN — and excludes JP items."""
    client, repo = inv_client
    repo.put_inventory_item(_raw("sv1-en"))            # no stored language → EN
    repo.put_inventory_item(_raw(None, language=Language.JP))

    resp = client.get(
        "/inventory/search?language=EN",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["card_id"] == "sv1-en"
    assert body["items"][0]["language"] == "EN"


def test_search_omitting_language_returns_both_languages(inv_client, mint_token):
    """An omitted language filter returns items of every language."""
    client, repo = inv_client
    repo.put_inventory_item(_raw("sv1-en"))
    repo.put_inventory_item(_raw(None, language=Language.JP))

    resp = client.get(
        "/inventory/search",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    body = resp.json()
    assert body["total"] == 2
    assert {i["language"] for i in body["items"]} == {"EN", "JP"}


def test_search_language_jp_returns_jp_item_despite_other_unmatched_filters(
    inv_client, mint_token,
):
    """A language filter alone still returns JP items even though they have
    card_id=None and cannot match name/set/rarity filters."""
    client, repo = inv_client
    jp = _raw(None, language=Language.JP)
    repo.put_inventory_item(jp)

    resp = client.get(
        "/inventory/search?language=JP",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["item_id"] == jp.item_id


def test_search_rejects_invalid_language(inv_client, mint_token):
    """Only the Language enum values (EN/JP) are accepted."""
    client, _ = inv_client
    resp = client.get(
        "/inventory/search?language=fr",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 422


def test_B9_search_response_omits_internal_fields(inv_client, mint_token):
    """The search projection is an allowlist: no internal per-item field ships.

    Every field in ``internal`` below is POPULATED on the seeded item on purpose.
    A field left at its default would make the disjointness assertion pass
    vacuously — it proves nothing about a field the projection would only leak
    once something put a value in it. ``consignment`` and ``needs_review``
    specifically are here because they used to be probed by a separate, weaker
    test that asserted three absent keys and nothing else.
    """
    client, repo = inv_client
    repo.put_inventory_item(_raw(
        "sv1-secret", location="glass",
        market_value_at_purchase=Decimal("40.00"),
        acquired_show_id="show-1", notes="bought cheap from Dave",
        consignment=ConsignmentTerms(
            consignor_id="c-1", split_percent=Decimal("20")),
        needs_review=True,
        tcg_url="https://www.tcgplayer.com/product/1/pokemon-sv-pikachu",
    ))
    resp = client.get(
        "/inventory/search",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    internal = {"location", "market_value_at_purchase", "acquired_show_id",
                "notes", "cost_basis", "consignment", "needs_review", "tcg_url"}
    assert internal.isdisjoint(item.keys()), internal & set(item.keys())
    # customer-facing fields still present
    assert item["kind"] == "raw" and item["listed_price"] == "10.00"


# ==== RFC 0001: display_name materialized at import, read verbatim (MUST-FIX A/C) ==
# docs/rfcs/0001-inventory-catalog-relink-and-display-fallback.md, section C.
# `notes` is internal-only and off the customer wire (cost/price range, a location
# like "For David"). The sanitized `display_name` is composed ONCE at import from
# the structured Name + Card # columns and stored on the item; the router reads
# that stored field verbatim — it does NOT re-parse notes — so an unmatched item
# reads as a card name instead of the raw item_id ULID, with no free-text path in.

def test_search_result_exposes_materialized_display_name_when_unmatched(
    inv_client, mint_token,
):
    """An available raw item with card_id=None exposes the display_name stored on
    the item at import time; the router reads the field, it does not parse notes."""
    client, repo = inv_client
    repo.put_inventory_item(
        _raw(None, display_name="Dragonair #181", notes="Dragonair #181.0 — 30-32"))

    resp = client.get(
        "/inventory/search",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["display_name"] == "Dragonair #181"


def test_search_result_does_not_leak_notes_cost_or_location(inv_client, mint_token):
    """Privacy guard: notes/cost/location/tcg_url are off the allowlist entirely,
    and the exposed display_name carries only the materialized name+number — never
    a cost/price range or a storage location."""
    client, repo = inv_client
    repo.put_inventory_item(
        _raw(None, display_name="Dragonair #181",
             notes="Dragonair #181.0 — 30-32 — For David", location="glass"))

    resp = client.get(
        "/inventory/search",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    result = resp.json()["items"][0]
    for leaked in ("notes", "cost_basis", "location", "tcg_url"):
        assert leaked not in result
    assert result["display_name"] == "Dragonair #181"
    blob = " ".join(str(v) for v in result.values())
    assert "30-32" not in blob
    assert "For David" not in blob
    assert "glass" not in blob


def test_search_result_display_name_is_none_when_item_stored_none(
    inv_client, mint_token,
):
    """Council MUST-FIX A: a row imported with a blank Name has display_name=None
    stored (the importer never derives it from Notes). The wire exposes None even
    though the internal notes carry free-text, so cost/consignor/location text
    never reaches the customer wire or the LLM context."""
    client, repo = inv_client
    repo.put_inventory_item(_raw(None, display_name=None, notes="cost 40, sold to David"))
    repo.put_inventory_item(_raw(None, display_name=None, notes="For David"))

    resp = client.get(
        "/inventory/search",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    body = resp.json()
    assert body["total"] == 2
    for result in body["items"]:
        assert result["display_name"] is None
        assert "notes" not in result
        # nothing internal leaked into any exposed string value
        blob = " ".join(str(v) for v in result.values())
        assert "David" not in blob
        assert "cost 40" not in blob


def test_matched_item_prefers_catalog_name_over_display_name(inv_client, mint_token):
    """When `card` is present, display_name is present-but-None on the wire even if
    the item stored one — the catalog name is authoritative for a matched item."""
    client, repo = inv_client
    repo.batch_upsert_catalog_cards([_catalog("sv1-1", "Sprigatito")])
    repo.put_inventory_item(_raw("sv1-1", display_name="Sprigatito #001"))

    resp = client.get(
        "/inventory/search",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    result = resp.json()["items"][0]
    assert result["card"]["name"] == "Sprigatito"
    assert "display_name" in result
    assert result["display_name"] is None


# ==== T10: display_name_override reaches the customer wire ====================
# docs/plans/rfc-0008/t10-jp-english-names.md. _CUSTOMER_ITEM_FIELDS is an
# ALLOWLIST, so a field added to the model is hidden until it is named there —
# without these tests the override would be storable, editable, and silently
# invisible to the customer it exists for.

def test_search_result_exposes_display_name_override(inv_client, mint_token):
    """The whole point of the field: a JP card whose catalog row is in Japanese
    script carries an English name the customer can actually read."""
    client, repo = inv_client
    repo.batch_upsert_catalog_cards([_catalog("ja:M4-084", "ハルクジラ")])
    repo.put_inventory_item(_raw("ja:M4-084", display_name_override="Chespin",
                                 language=Language.JP))

    resp = client.get(
        "/inventory/search",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    result = resp.json()["items"][0]
    assert result["display_name_override"] == "Chespin"
    # The JP marker must survive alongside the English name — a customer seeing
    # "Chespin" must still be able to tell it is a Japanese print (pricing-relevant).
    assert result["language"] == "JP"
    # Re-pointing the catalog link is a separate, deliberate action (T11).
    assert result["card_id"] == "ja:M4-084"


def test_search_result_display_name_override_is_none_when_unset(inv_client, mint_token):
    """The field is present-but-None for the 249 items that need no correction,
    so the frontend falls straight through to the catalog name."""
    client, repo = inv_client
    repo.batch_upsert_catalog_cards([_catalog("sv1-1", "Sprigatito")])
    repo.put_inventory_item(_raw("sv1-1"))

    resp = client.get(
        "/inventory/search",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    result = resp.json()["items"][0]
    assert result["display_name_override"] is None
    assert result["card"]["name"] == "Sprigatito"


# ---------------------------------------------------------------------------
# PHASE 12 — inventory price correctness (RED phase)
#
# Phase 12 absorbs Phase 10. Three symptoms, one root cause plus two more bugs
# in the same neighborhood:
#   D1 (Finding 1): the write-path denormalizer (`refresh_inventory_market_
#       values`, services/catalog_sync.py) does a bare exact-match finish
#       lookup instead of the read path's `_MARKET_FINISH_FALLBACK` chain.
#   D2 (Finding 6): `inventory_summary`'s `est_value` sums the raw stored
#       `current_market_value` field directly instead of routing through the
#       finish-aware helper the search path already uses.
#   D3 (Finding 2): `_price()` prefers the permanently-dead `listed_price`
#       field over `current_market_value`, so a price bound silently drops
#       nearly every item once `listed_price` is null everywhere by design.
#
# These tests exercise D2 and D3 through the real FastAPI TestClient. D1 (the
# denormalizer itself) and the write/read anti-drift matrix are pinned in
# backend/tests/services/test_catalog_sync.py, matching that suite's existing
# `refresh_inventory_market_values` conventions.
# ---------------------------------------------------------------------------


def test_summary_est_value_resolves_through_fallback_finish_chain(inv_client, mint_token):
    """Phase 12 Finding 6: `est_value` must reflect the finish-aware price, not
    the raw stored `current_market_value` field. A customer-visible item whose
    price is resolvable ONLY via the fallback chain (a `normal`-finish item
    against a card priced solely under `holofoil` — the exact D1 shape,
    174/213 live nulls) must contribute its resolved market price to
    `est_value`. A second, genuinely priceless card (no catalog price under
    any finish) must contribute zero without breaking the sum. Today this
    fails: `inventory_summary` sums `current_market_value` directly, which was
    never denormalized for either item, so `est_value` stays "0"."""
    client, repo = inv_client
    repo.batch_upsert_catalog_cards([
        _catalog("sv1-1", "Sprigatito", set_id="sv1",
                 prices={"holofoil": FinishPrice(market=Decimal("42.00"))}),
        _catalog("sv1-2", "Floragato", set_id="sv1"),  # no prices at all
    ])

    priced_via_fallback = _raw("sv1-1", finish="normal")
    priced_via_fallback.listed_price = None
    priced_via_fallback.current_market_value = None  # never denormalized (D1)
    repo.put_inventory_item(priced_via_fallback)

    priceless = _raw("sv1-2", finish="normal")
    priceless.listed_price = None
    priceless.current_market_value = None
    repo.put_inventory_item(priceless)

    resp = client.get(
        "/inventory/summary",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["cards_in_vault"] == 2
    assert body["est_value"] == "42.00"


def _seed_fallback_priced_item(repo, *, card_id="sv1-1"):
    """A customer-visible `normal`-finish item whose card is priced only under
    `holofoil`, run through the REAL (currently buggy) denormalizer — exactly
    the pipeline a production search request sees. Returns the item.

    Deliberately calls the production `refresh_inventory_market_values` rather
    than hand-setting `current_market_value`, so these tests reproduce the
    owner's actual complaint (batch job -> search UI), not a synthetic stand-in
    for it. Today the call leaves `current_market_value` at `None` (D1); once
    Phase 12 lands it correctly denormalizes to 42.00 via the fallback chain.
    """
    from merlins_collection.services.catalog_sync import refresh_inventory_market_values

    repo.batch_upsert_catalog_cards([
        _catalog(card_id, "Sprigatito", set_id="sv1",
                 prices={"holofoil": FinishPrice(market=Decimal("42.00"))}),
    ])
    item = _raw(card_id, finish="normal")
    item.listed_price = None
    item.current_market_value = None
    repo.put_inventory_item(item)
    refresh_inventory_market_values(repo)
    return item


def test_search_max_price_alone_no_longer_wipes_inventory(inv_client, mint_token):
    """Phase 12 Finding 2, reproduced exactly as the owner reported it:
    `GET /inventory/search?max_price=500` with NO `min_price` must not wipe
    the inventory. Today it returns an empty list for an item priced only via
    the fallback chain, because `_price()` prefers the dead `listed_price`
    field and the denormalizer never populated `current_market_value`."""
    client, repo = inv_client
    _seed_fallback_priced_item(repo)

    resp = client.get(
        "/inventory/search?max_price=500",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["card_id"] == "sv1-1"


def test_search_min_price_alone_no_longer_wipes_inventory(inv_client, mint_token):
    """Same reproduction as the `max_price`-alone case, for `min_price` alone."""
    client, repo = inv_client
    _seed_fallback_priced_item(repo)

    resp = client.get(
        "/inventory/search?min_price=1",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["card_id"] == "sv1-1"


def test_search_min_and_max_price_together_no_longer_wipes_inventory(inv_client, mint_token):
    """Same reproduction with both bounds supplied together."""
    client, repo = inv_client
    _seed_fallback_priced_item(repo)

    resp = client.get(
        "/inventory/search?min_price=1&max_price=500",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["card_id"] == "sv1-1"


def test_price_filter_falls_back_to_listed_price_with_no_catalog_row(
    inv_client, mint_token,
):
    """REVERSED BY RFC 0008 §A/T1. This test previously asserted the OPPOSITE —
    that `listed_price` alone must never satisfy a bound, on the Phase 12 / D3
    reasoning that the field is null on every live item and so pure dead weight.

    That reasoning is about the DATA, not the contract, and T1 makes the contract
    binding: the filter compares whatever the tile renders, and the tile renders
    `card.market_price ?? listed_price` (`CardTile.tsx:19`). An unmatched item
    carrying a sticker price displays that number, so a customer filtering to
    "$50 and up" must be shown it. Hiding a card the grid would price at $1000
    is the same class of lie as showing one it prices at $517 under a $500 cap.

    The item that stays out is the one with nothing to display at all."""
    client, repo = inv_client
    only_listed = _raw("sv1-1", price="1000.00")
    only_listed.current_market_value = None  # no catalog row, no market price
    repo.put_inventory_item(only_listed)

    nothing_to_display = _raw("sv1-2")
    nothing_to_display.listed_price = None
    nothing_to_display.current_market_value = Decimal("80.00")
    repo.put_inventory_item(nothing_to_display)

    resp = client.get(
        "/inventory/search?min_price=50",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["card_id"] == "sv1-1"
    assert body["hidden_no_price"] == 1


def test_search_price_bound_excludes_genuinely_priceless_items(inv_client, mint_token):
    """OPEN DECISION (Phase 12 SCOPE, not resolved by this phase): once the
    denormalizer fix lands, ~39 live cards remain genuinely priceless
    (`no_usable_price` — no catalog price under any finish). This test pins
    the CURRENT documented behavior — a price-bound filter continues to
    silently exclude such items — because Phase 12's text explicitly leaves
    open whether the UI instead needs an explicit "no listed price" affordance
    so they aren't invisibly dropped.

    FLAG FOR A HUMAN: this is a decision point, not a settled contract. This
    test locks in "silently excluded" only because that is what the phase
    text calls the CURRENT behavior; it is written so a human notices and
    confirms rather than has a guess silently locked in by test coverage.
    """
    client, repo = inv_client
    priceless = _raw("sv1-1")
    priceless.listed_price = None
    priceless.current_market_value = None
    repo.put_inventory_item(priceless)

    resp = client.get(
        "/inventory/search?max_price=999999",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


# ---------------------------------------------------------------------------
# PHASE 12 / OWNER DECISION 2 (RED, written during GREEN — the decision was
# still OPEN when the rest of this file's Phase 12 tests were authored).
#
# RESOLUTION: priceless items stay EXCLUDED from a price-bounded search (a card
# with no known price cannot honestly be claimed to be under $500 — the
# exclusion half is already pinned by
# `test_search_price_bound_excludes_genuinely_priceless_items` above), BUT they
# are no longer INVISIBLY dropped: the response carries a count of how many the
# bound hid, so the UI can say "N cards hidden (no price on file)".
# ---------------------------------------------------------------------------


def test_search_price_bound_reports_the_count_of_priceless_items_it_hid(
    inv_client, mint_token,
):
    """The exclusion stays; the silence does not. A price-bounded search
    reports how many otherwise-matching items it dropped for having no
    resolvable price.

    RFC 0008 §A/T1 moved the surviving item's price onto a real catalog row: it
    used to be priced by `current_market_value` alone, which the bound no longer
    reads, so the fixture would otherwise have made this a test of three hidden
    items rather than of the count itself."""
    client, repo = inv_client
    repo.batch_upsert_catalog_cards([
        _catalog("sv1-1", "Sprigatito",
                 prices={"holofoil": FinishPrice(market=Decimal("80.00"))}),
    ])
    priced = _raw("sv1-1")
    priced.listed_price = None
    repo.put_inventory_item(priced)
    for card_id in ("sv1-2", "sv1-3"):
        priceless = _raw(card_id)
        priceless.listed_price = None
        priceless.current_market_value = None
        repo.put_inventory_item(priceless)

    resp = client.get(
        "/inventory/search?max_price=500",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["card_id"] == "sv1-1"
    assert body["hidden_no_price"] == 2


def test_search_reports_zero_hidden_when_the_bound_hides_every_item(
    inv_client, mint_token,
):
    """The owner's reported symptom, made honest: when a price bound empties
    the whole result set because nothing has a price, the count says so rather
    than leaving the UI to claim "no cards found"."""
    client, repo = inv_client
    priceless = _raw("sv1-1")
    priceless.listed_price = None
    priceless.current_market_value = None
    repo.put_inventory_item(priceless)

    resp = client.get(
        "/inventory/search?min_price=1&max_price=500",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    body = resp.json()
    assert body["total"] == 0
    assert body["hidden_no_price"] == 1


def test_search_without_a_price_bound_hides_nothing_and_reports_zero(
    inv_client, mint_token,
):
    """No bound, no hiding: priceless items are returned normally and the
    count is 0, so the UI never renders the affordance spuriously."""
    client, repo = inv_client
    priceless = _raw("sv1-1")
    priceless.listed_price = None
    priceless.current_market_value = None
    repo.put_inventory_item(priceless)

    resp = client.get(
        "/inventory/search",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    body = resp.json()
    assert body["total"] == 1
    assert body["hidden_no_price"] == 0


def test_search_hidden_count_excludes_items_other_filters_already_dropped(
    inv_client, mint_token,
):
    """The count must be honest: it reports items the PRICE BOUND hid, not
    every priceless item in the vault. A priceless Sprigatito that the `name`
    filter already excluded was not hidden by the price bound and must not be
    counted, or the affordance would overstate what widening the range
    recovers."""
    client, repo = inv_client
    repo.batch_upsert_catalog_cards([
        _catalog("sv1-1", "Sprigatito"),
        _catalog("sv1-2", "Charizard"),
    ])
    for card_id in ("sv1-1", "sv1-2"):
        priceless = _raw(card_id)
        priceless.listed_price = None
        priceless.current_market_value = None
        repo.put_inventory_item(priceless)

    resp = client.get(
        "/inventory/search?name=Charizard&max_price=500",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    body = resp.json()
    assert body["total"] == 0
    assert body["hidden_no_price"] == 1


# ---- GET /inventory/facets (Phase 13 — DB-driven dropdown options) ----

def test_facets_requires_authentication(inv_client):
    client, _ = inv_client
    resp = client.get("/inventory/facets")
    assert resp.status_code == 401


def test_facets_returns_distinct_values_from_inventory(inv_client, mint_token):
    """The facets endpoint returns only values present in the DB, not hardcoded."""
    client, repo = inv_client
    repo.batch_upsert_catalog_cards([
        _catalog("sv1-1", "Sprigatito", set_id="en:sv01", set_name="Scarlet & Violet", rarity="Common"),
        _catalog("base1-4", "Charizard", set_id="en:base1", set_name="Base", rarity="Rare Holo"),
    ])
    repo.put_inventory_item(_raw("sv1-1", condition=Condition.NM))
    repo.put_inventory_item(_raw("base1-4", condition=Condition.LP))

    resp = client.get(
        "/inventory/facets",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200
    body = resp.json()

    # Sets: alphabetically sorted by name.
    set_names = [s["name"] for s in body["sets"]]
    assert "Base" in set_names
    assert "Scarlet & Violet" in set_names
    assert set_names == sorted(set_names, key=str.lower)

    # Rarities: only what's in the catalog for held cards.
    assert "Common" in body["rarities"]
    assert "Rare Holo" in body["rarities"]

    # Conditions: only what's on the items.
    assert "NM" in body["conditions"]
    assert "LP" in body["conditions"]
    assert "HP" not in body["conditions"]

    # Languages: default EN.
    assert "EN" in body["languages"]


def test_facets_excludes_literal_none_rarity(inv_client, mint_token):
    """The literal string 'None' from TCGdex must not appear as a facet option."""
    client, repo = inv_client
    repo.batch_upsert_catalog_cards([
        _catalog("sv1-1", "Card", rarity="None"),
    ])
    repo.put_inventory_item(_raw("sv1-1"))

    resp = client.get(
        "/inventory/facets",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    body = resp.json()
    assert "None" not in body["rarities"]


def test_facets_excludes_non_visible_items(inv_client, mint_token):
    """Items in non-customer-visible locations don't contribute facet values."""
    client, repo = inv_client
    repo.batch_upsert_catalog_cards([
        _catalog("sv1-1", "Hidden Card", set_id="en:hidden", set_name="Hidden Set", rarity="Ultra Rare"),
    ])
    # Item in binder (non-visible location) — should not contribute.
    repo.put_inventory_item(_raw("sv1-1", location="binder"))

    resp = client.get(
        "/inventory/facets",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    body = resp.json()
    assert body["sets"] == []
    assert body["rarities"] == []


# ---- GET /inventory/search?sort= (Phase 14 — Sort control) ----

def test_sort_by_price_desc(inv_client, mint_token):
    """price_desc sorts by the DISPLAY price (card.market_price for raw items),
    with priceless items (no display price) last."""
    client, repo = inv_client
    repo.batch_upsert_catalog_cards([
        _catalog("sv1-1", "Cheap", prices={"holofoil": FinishPrice(market=Decimal("10"))}),
        _catalog("sv1-2", "Expensive", prices={"holofoil": FinishPrice(market=Decimal("100"))}),
        _catalog("sv1-3", "Priceless"),  # no catalog prices → card.market_price = None
    ])
    repo.put_inventory_item(_raw("sv1-1", price="0"))
    repo.put_inventory_item(_raw("sv1-2", price="0"))
    priceless = _raw("sv1-3", price="0")
    priceless.listed_price = None  # no listed_price fallback either
    repo.put_inventory_item(priceless)

    resp = client.get(
        "/inventory/search?sort=price_desc",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    body = resp.json()
    names = [i["card"]["name"] for i in body["items"]]
    assert names == ["Expensive", "Cheap", "Priceless"]


def test_sort_by_price_asc(inv_client, mint_token):
    """price_asc sorts by the DISPLAY price ascending, priceless last."""
    client, repo = inv_client
    repo.batch_upsert_catalog_cards([
        _catalog("sv1-1", "Cheap", prices={"holofoil": FinishPrice(market=Decimal("10"))}),
        _catalog("sv1-2", "Expensive", prices={"holofoil": FinishPrice(market=Decimal("100"))}),
        _catalog("sv1-3", "Priceless"),  # no catalog prices
    ])
    repo.put_inventory_item(_raw("sv1-1", price="0"))
    repo.put_inventory_item(_raw("sv1-2", price="0"))
    priceless = _raw("sv1-3", price="0")
    priceless.listed_price = None
    repo.put_inventory_item(priceless)

    resp = client.get(
        "/inventory/search?sort=price_asc",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    body = resp.json()
    names = [i["card"]["name"] for i in body["items"]]
    assert names == ["Cheap", "Expensive", "Priceless"]


def test_sort_by_name_asc(inv_client, mint_token):
    """name_asc sorts alphabetically by catalog name."""
    client, repo = inv_client
    repo.batch_upsert_catalog_cards([
        _catalog("sv1-1", "Zebra"),
        _catalog("sv1-2", "Apple"),
    ])
    repo.put_inventory_item(_raw("sv1-1"))
    repo.put_inventory_item(_raw("sv1-2"))

    resp = client.get(
        "/inventory/search?sort=name_asc",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    body = resp.json()
    names = [i["card"]["name"] for i in body["items"]]
    assert names == ["Apple", "Zebra"]


def test_sort_invalid_falls_back_to_newest(inv_client, mint_token):
    """An unrecognized sort value falls back to newest (no 422)."""
    client, repo = inv_client
    repo.put_inventory_item(_raw("sv1-1"))

    resp = client.get(
        "/inventory/search?sort=invalid_sort_value",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# RFC 0008 §A / T1 — the price bound must compare the price the CUSTOMER SEES.
#
# Three code paths used to read three different figures for "the price of a
# card": the bound read the nightly-denormalized `current_market_value`, while
# the sort and the rendered tile both read the LIVE `card.market_price`. The
# owner reported a Rayquaza DISPLAYING $517 that still passed `max_price=500`.
#
# These pin the single-authority invariant: filter, sort, and tile all resolve
# a price through `_display_price`, and may never diverge again.
# ---------------------------------------------------------------------------

def _live_priced(repo, card_id, name, *, live, stale, finish="holofoil"):
    """Seed one customer-visible raw item whose LIVE catalog price and STALE
    denormalized `current_market_value` deliberately disagree.

    `listed_price` is set to None because it is null on every live item by owner
    decision (Section 1/D3) — so the catalog price is the only figure the tile
    can render, which is exactly the condition the bug was reported under.
    """
    repo.batch_upsert_catalog_cards([
        _catalog(card_id, name, prices={finish: FinishPrice(market=Decimal(live))}),
    ])
    item = _raw(card_id, finish=finish)
    item.listed_price = None
    item.current_market_value = Decimal(stale) if stale is not None else None
    repo.put_inventory_item(item)
    return item


def test_price_bound_excludes_a_card_whose_displayed_price_is_over_the_max(
    inv_client, mint_token,
):
    """The owner's report, exactly: a card DISPLAYING $517 must not survive
    `max_price=500` on the strength of a stale $400 denormalized value."""
    client, repo = inv_client
    _live_priced(repo, "sv1-rayquaza", "Rayquaza", live="517.00", stale="400.00")

    resp = client.get(
        "/inventory/search?max_price=500",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    # It was excluded for being too expensive, not for being priceless.
    assert body["hidden_no_price"] == 0


def test_price_bound_includes_a_card_whose_displayed_price_is_under_the_max(
    inv_client, mint_token,
):
    """The mirror case: a stale $600 must not hide a card the customer sees at
    $450. Divergence in the other direction hides real stock from a real buyer."""
    client, repo = inv_client
    _live_priced(repo, "sv1-1", "Sprigatito", live="450.00", stale="600.00")

    resp = client.get(
        "/inventory/search?max_price=500",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["card_id"] == "sv1-1"
    assert body["items"][0]["card"]["market_price"] == "450.00"


def test_price_bound_returns_normally_priced_stock_and_hides_nothing(
    inv_client, mint_token,
):
    """REGRESSION GUARD FOR THE ORDERING TRAP.

    `_display_price` reads `item.card`, which only `_enrich()` populates. If the
    bound is pointed at `_display_price` while enrichment still runs AFTER it,
    `item.card` is None for every item, every card falls back to the permanently
    null `listed_price`, and the filter silently swallows the ENTIRE inventory
    into `hidden_no_price` — a failure that reads as "there's just no stock".

    This item is priced only by the catalog, so it can only be returned if
    enrichment ran first."""
    client, repo = inv_client
    _live_priced(repo, "sv1-1", "Sprigatito", live="42.00", stale="42.00")

    resp = client.get(
        "/inventory/search?max_price=500",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["hidden_no_price"] == 0


def test_price_bound_counts_items_with_no_displayable_price(inv_client, mint_token):
    """`hidden_no_price` keeps its meaning — "excluded because the price is
    unknown" — now measured against the figure the tile renders.

    NOTE THE SECOND ITEM. It carries a `current_market_value` well inside the
    bound but has no catalog row and no `listed_price`, so the customer's tile
    shows "Price N/A". It is now counted as hidden rather than silently matched
    on a figure nobody can see. That is deliberate: the denormalized value is no
    longer an independent source of truth for the filter."""
    client, repo = inv_client
    nothing = _raw("sv1-1")
    nothing.listed_price = None
    nothing.current_market_value = None
    repo.put_inventory_item(nothing)

    denormalized_only = _raw("sv1-2")
    denormalized_only.listed_price = None
    denormalized_only.current_market_value = Decimal("120.00")
    repo.put_inventory_item(denormalized_only)

    resp = client.get(
        "/inventory/search?max_price=500",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["hidden_no_price"] == 2


def test_price_bound_and_price_sort_agree_on_the_same_figure(inv_client, mint_token):
    """THE INVARIANT THIS TASK EXISTS TO ESTABLISH.

    With a bound applied and `sort=price_desc`, every returned item's DISPLAYED
    price is inside the bound and the ordering is by that same figure. Each
    fixture's stale value is deliberately wrong in a different direction, so a
    filter still reading `current_market_value` returns a different set AND a
    different order."""
    client, repo = inv_client
    _live_priced(repo, "sv1-cheap", "Cheap", live="100.00", stale="900.00")
    _live_priced(repo, "sv1-mid", "Mid", live="300.00", stale="50.00")
    _live_priced(repo, "sv1-dear", "Dear", live="700.00", stale="20.00")

    resp = client.get(
        "/inventory/search?max_price=500&sort=price_desc",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert [i["card_id"] for i in body["items"]] == ["sv1-mid", "sv1-cheap"]
    prices = [Decimal(i["card"]["market_price"]) for i in body["items"]]
    assert all(p <= Decimal("500") for p in prices)
    assert prices == sorted(prices, reverse=True)


# ---------------------------------------------------------------------------
# RFC 0008 §B / T2 — `LP+` / `LP-` must reach the condition filter.
#
# Storage is ALWAYS two fields (`condition` tier + `condition_modifier`), but
# every human-facing surface speaks one combined string. `/inventory/facets`
# emitted the bare tier only, so it was structurally incapable of offering
# `LP+`/`LP-` no matter what was in stock, and `/inventory/search?condition=`
# was typed as the bare-tier enum, so the combined form 422'd.
#
# `FilterPanel.tsx` renders whatever `facets.conditions` contains — the fix is
# backend-only by construction.
# ---------------------------------------------------------------------------

def test_facets_conditions_include_the_modifier(inv_client, mint_token):
    """An `LP+` in stock must be offerable as `LP+`, not flattened to `LP`."""
    client, repo = inv_client
    repo.put_inventory_item(_raw("sv1-1", condition=Condition.LP, condition_modifier="+"))

    resp = client.get(
        "/inventory/facets",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200
    assert "LP+" in resp.json()["conditions"]


def test_facets_conditions_treat_each_grade_as_a_distinct_option(inv_client, mint_token):
    """`LP+`, `LP` and `LP-` are three different grades at three different
    prices, so they are three separate options — not one collapsed `LP`."""
    client, repo = inv_client
    repo.put_inventory_item(_raw("sv1-1", condition=Condition.LP, condition_modifier="+"))
    repo.put_inventory_item(_raw("sv1-2", condition=Condition.LP))
    repo.put_inventory_item(_raw("sv1-3", condition=Condition.LP, condition_modifier="-"))

    resp = client.get(
        "/inventory/facets",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.json()["conditions"] == ["LP+", "LP", "LP-"]


def test_facets_conditions_are_ordered_best_to_worst_not_alphabetically(
    inv_client, mint_token,
):
    """The owner-facing vocabulary order is NM, LP+, LP, LP-, MP, HP, DMG.
    `sorted()` would give `DMG, HP, LP, LP+, LP-, MP, NM` — alphabetical, and
    nonsense to a collector reading a dropdown."""
    client, repo = inv_client
    repo.put_inventory_item(_raw("sv1-1", condition=Condition.DMG))
    repo.put_inventory_item(_raw("sv1-2", condition=Condition.LP, condition_modifier="-"))
    repo.put_inventory_item(_raw("sv1-3", condition=Condition.NM))
    repo.put_inventory_item(_raw("sv1-4", condition=Condition.LP, condition_modifier="+"))
    repo.put_inventory_item(_raw("sv1-5", condition=Condition.HP))
    repo.put_inventory_item(_raw("sv1-6", condition=Condition.LP))
    repo.put_inventory_item(_raw("sv1-7", condition=Condition.MP))

    resp = client.get(
        "/inventory/facets",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.json()["conditions"] == ["NM", "LP+", "LP", "LP-", "MP", "HP", "DMG"]


def test_facets_omit_a_grade_with_nothing_in_stock(inv_client, mint_token):
    """A facet reflects actual stock. Padding the list out to all seven options
    is what `CONDITION_OPTIONS` is for, and that belongs to the admin editor."""
    client, repo = inv_client
    repo.put_inventory_item(_raw("sv1-1", condition=Condition.LP))

    resp = client.get(
        "/inventory/facets",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    conditions = resp.json()["conditions"]
    assert conditions == ["LP"]
    assert "LP+" not in conditions


def test_search_condition_with_a_modifier_narrows_to_exactly_that_grade(
    inv_client, mint_token,
):
    """The combined form the facet now offers must actually filter. An `LP+`
    query returns the LP+ card and not the plain LP one."""
    client, repo = inv_client
    repo.put_inventory_item(_raw("sv1-plus", condition=Condition.LP, condition_modifier="+"))
    repo.put_inventory_item(_raw("sv1-plain", condition=Condition.LP))
    repo.put_inventory_item(_raw("sv1-minus", condition=Condition.LP, condition_modifier="-"))

    resp = client.get(
        "/inventory/search?condition=LP%2B",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["card_id"] == "sv1-plus"


def test_search_bare_condition_tier_still_matches_every_modifier(inv_client, mint_token):
    """REGRESSION GUARD. A bare tier means the WHOLE tier — `LP` keeps matching
    LP+, LP and LP-. Accepting the combined form must not quietly turn the bare
    tier into an exact-match query."""
    client, repo = inv_client
    repo.put_inventory_item(_raw("sv1-plus", condition=Condition.LP, condition_modifier="+"))
    repo.put_inventory_item(_raw("sv1-plain", condition=Condition.LP))
    repo.put_inventory_item(_raw("sv1-minus", condition=Condition.LP, condition_modifier="-"))
    repo.put_inventory_item(_raw("sv1-nm", condition=Condition.NM))

    resp = client.get(
        "/inventory/search?condition=LP",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert sorted(i["card_id"] for i in body["items"]) == [
        "sv1-minus", "sv1-plain", "sv1-plus",
    ]


def test_search_rejects_an_unparseable_condition(inv_client, mint_token):
    """Garbage is a 422, not a silent empty result — an empty grid would read as
    "we have no LP cards" rather than "that isn't a condition"."""
    client, _ = inv_client
    resp = client.get(
        "/inventory/search?condition=ZZ",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 422


def test_search_condition_with_a_modifier_still_excludes_graded_items(
    inv_client, mint_token,
):
    """Existing rule, unchanged by the new parsing: a condition filter is a
    raw-card filter, and graded slabs drop out whenever it is set."""
    client, repo = inv_client
    repo.put_inventory_item(_raw("sv1-plus", condition=Condition.LP, condition_modifier="+"))
    repo.put_inventory_item(_graded("sv1-slab"))

    resp = client.get(
        "/inventory/search?condition=LP%2B",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    body = resp.json()
    assert body["total"] == 1
    assert all(i["kind"] == "raw" for i in body["items"])


# ---------------------------------------------------------------------------
# CONDITION-ADJUSTED CUSTOMER PRICE (RFC 0008 follow-up, T1 row 1)
#
# `services.condition_pricing` scales the catalog's NM figure by tier — LP x0.82,
# MP x0.58, HP x0.33, DMG x0.15 — and the nightly denormalizer already bakes that
# into `current_market_value`. But the CUSTOMER-facing figure (the tile, the sort
# and, after T1, the price filter) all read the raw unadjusted `card.market_price`,
# so a DMG card was shown to a buyer at ~6.7x what the business values it at —
# wrong in the business's favour, the worst direction to be wrong in.
#
# Owner decision 2026-08-06: customer prices MUST include the condition
# multiplier. The adjustment is applied ONCE, at enrichment, so `card.market_price`
# IS the adjusted figure — which keeps T1's single-authority invariant intact
# (filter, sort and tile still resolve the same number) rather than reintroducing
# the divergence T1 removed.
# ---------------------------------------------------------------------------

def test_customer_price_is_condition_adjusted_for_a_damaged_card(
    inv_client, mint_token,
):
    """The bug, in its worst form: a DMG card whose catalog NM figure is $100
    must reach the customer at $15.00 (0.15x), not $100."""
    client, repo = inv_client
    repo.batch_upsert_catalog_cards([
        _catalog("sv1-dmg", "Charizard",
                 prices={"holofoil": FinishPrice(market=Decimal("100.00"))}),
    ])
    item = _raw("sv1-dmg", condition=Condition.DMG)
    item.listed_price = None
    repo.put_inventory_item(item)

    resp = client.get(
        "/inventory/search",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"][0]["card"]["market_price"] == "15.00"


def test_customer_price_adjustment_honours_the_condition_modifier(
    inv_client, mint_token,
):
    """LP+ is the midpoint of LP (0.82) and NM (1.00) — 0.91x, so $100 -> $91."""
    client, repo = inv_client
    repo.batch_upsert_catalog_cards([
        _catalog("sv1-lpplus", "Pikachu",
                 prices={"holofoil": FinishPrice(market=Decimal("100.00"))}),
    ])
    item = _raw("sv1-lpplus", condition=Condition.LP, condition_modifier="+")
    item.listed_price = None
    repo.put_inventory_item(item)

    resp = client.get(
        "/inventory/search",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    body = resp.json()
    assert body["items"][0]["card"]["market_price"] == "91.00"


def test_near_mint_price_is_left_exactly_alone(inv_client, mint_token):
    """NM is the anchor (1.00x). The overwhelming majority of stock must be
    completely unaffected by this change."""
    client, repo = inv_client
    repo.batch_upsert_catalog_cards([
        _catalog("sv1-nm", "Mew",
                 prices={"holofoil": FinishPrice(market=Decimal("42.50"))}),
    ])
    item = _raw("sv1-nm", condition=Condition.NM)
    item.listed_price = None
    repo.put_inventory_item(item)

    resp = client.get(
        "/inventory/search",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    body = resp.json()
    assert body["items"][0]["card"]["market_price"] == "42.50"


def test_price_filter_uses_the_condition_adjusted_price(inv_client, mint_token):
    """The whole point of applying this at enrichment: the filter inherits it.
    A DMG card with a $600 NM catalog figure is really a $90 card, so it must
    SURVIVE `max_price=100` — the reverse of the bug, and the honest answer."""
    client, repo = inv_client
    repo.batch_upsert_catalog_cards([
        _catalog("sv1-cheap", "Blastoise",
                 prices={"holofoil": FinishPrice(market=Decimal("600.00"))}),
    ])
    item = _raw("sv1-cheap", condition=Condition.DMG)
    item.listed_price = None
    repo.put_inventory_item(item)

    resp = client.get(
        "/inventory/search?max_price=100",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    body = resp.json()
    assert body["total"] == 1
    assert body["hidden_no_price"] == 0
    assert body["items"][0]["card"]["market_price"] == "90.00"


def test_condition_adjustment_is_explained_to_the_customer(inv_client, mint_token):
    """Phase 19's visibility rule: an adjusted price must say WHY, or it reads
    as an arbitrary number. `value_note` is customer-visible by design."""
    client, repo = inv_client
    repo.batch_upsert_catalog_cards([
        _catalog("sv1-note", "Gengar",
                 prices={"holofoil": FinishPrice(market=Decimal("100.00"))}),
    ])
    item = _raw("sv1-note", condition=Condition.MP)
    item.listed_price = None
    repo.put_inventory_item(item)

    resp = client.get(
        "/inventory/search",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    body = resp.json()
    assert body["items"][0]["value_note"] == "Condition-adjusted (MP, 0.58x NM)"


def test_graded_slabs_are_not_condition_adjusted(inv_client, mint_token):
    """A slab carries a GRADE, not a condition tier, and its catalog price is an
    ungraded figure that `_display_price` already skips. Nothing to adjust — and
    adjusting one would be a category error."""
    client, repo = inv_client
    repo.batch_upsert_catalog_cards([
        _catalog("sv1-slab2", "Umbreon",
                 prices={"holofoil": FinishPrice(market=Decimal("100.00"))}),
    ])
    repo.put_inventory_item(_graded("sv1-slab2", price="500.00"))

    resp = client.get(
        "/inventory/search",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    body = resp.json()
    slab = next(i for i in body["items"] if i["card_id"] == "sv1-slab2")
    assert slab["listed_price"] == "500.00"


def test_summary_total_uses_condition_adjusted_prices(inv_client, mint_token):
    """The dashboard header must not disagree with the tiles beneath it.

    `/inventory/summary` resolves prices live through the same catalog figure
    the search results use, so it has to apply the SAME condition multiplier —
    otherwise this change would recreate exactly the header-vs-tile divergence
    Phase 12 and RFC 0008 T1 removed. One DMG card at a $100 NM figure is $15 of
    inventory, not $100.

    Note the stored fallback (`current_market_value`) is deliberately NOT
    adjusted here: the nightly denormalizer already baked the multiplier into it,
    so adjusting again would apply it twice.
    """
    client, repo = inv_client
    repo.batch_upsert_catalog_cards([
        _catalog("sv1-sum", "Snorlax",
                 prices={"holofoil": FinishPrice(market=Decimal("100.00"))}),
    ])
    item = _raw("sv1-sum", condition=Condition.DMG)
    item.listed_price = None
    repo.put_inventory_item(item)

    resp = client.get(
        "/inventory/summary",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200
    assert resp.json()["est_value"] == "15.00"
