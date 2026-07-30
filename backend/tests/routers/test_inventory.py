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


def test_price_filter_matches_on_market_value(inv_client, mint_token):
    """RETITLED AND RE-REASONED IN PHASE 12 (was
    ``test_price_filter_falls_back_to_market_value``, which described
    ``current_market_value`` as a FALLBACK behind ``listed_price``). It is no
    longer a fallback: ``_price`` reads ``current_market_value`` outright, since
    ``listed_price`` is null on every item by owner decision. The fixture and
    the assertion are unchanged — they held under both contracts — but the name
    and reasoning now describe the real one, so this and
    ``test_price_filter_no_longer_matches_on_dead_listed_price_alone`` are not
    two differently-reasoned pins on the same predicate.

    Three items, ``min_price=50``: only the one whose ``current_market_value``
    clears the bound survives. The 30-listed item and the wholly unpriced item
    are both out — the first for being under the bound (its 30 is a dead sticker
    price that no longer counts either way), the second for having no price."""
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
    assert body["items"][0]["card_id"] == "sv1-2"


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
    """The search projection is an allowlist: no internal per-item field ships."""
    client, repo = inv_client
    repo.put_inventory_item(_raw(
        "sv1-secret", location="glass",
        market_value_at_purchase=Decimal("40.00"),
        acquired_show_id="show-1", notes="bought cheap from Dave",
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


# ---------------------------------------------------------------------------
# PHASE 12 — inventory price correctness (RED phase)
#
# claude-progress.txt Section 3, Phase 12 (absorbs Phase 10). Three symptoms,
# one root cause plus two more bugs in the same neighborhood:
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


def test_price_filter_no_longer_matches_on_dead_listed_price_alone(inv_client, mint_token):
    """Phase 12 / D3: `_price()` must stop preferring `listed_price` (null on
    every item by owner design — permanently dead, Section 1/D3) over
    `current_market_value`. An item with a high `listed_price` but NO
    `current_market_value` must not match a price bound on the strength of its
    dead sticker price alone.

    NOTE FOR THE GREEN PHASE (per task instructions, not modified here):
    `test_price_filter_falls_back_to_market_value` (this file, currently
    around line 672) PINS THE OLD CONTRACT (`listed_price` preferred, market
    value only a fallback). It happens to still assert `total == 1` under
    either contract for its own fixture (its excluded item is excluded either
    way), so it may keep passing unmodified — but its docstring/assertion no
    longer describes the real contract once this test is green, and it should
    be reread and re-titled or consolidated with this test as part of GREEN,
    not left as a second, differently-reasoned pin on the same predicate.
    """
    client, repo = inv_client
    only_listed = _raw("sv1-1", price="1000.00")
    only_listed.current_market_value = None  # no market price yet
    repo.put_inventory_item(only_listed)

    only_market = _raw("sv1-2")
    only_market.listed_price = None
    only_market.current_market_value = Decimal("80.00")
    repo.put_inventory_item(only_market)

    resp = client.get(
        "/inventory/search?min_price=50",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["card_id"] == "sv1-2"


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
    resolvable price."""
    client, repo = inv_client
    priced = _raw("sv1-1")
    priced.listed_price = None
    priced.current_market_value = Decimal("80.00")
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
