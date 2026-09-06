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
    # RFC 0025 T2: `is_customer_visible` now requires a sticker price, so
    # EVERY item this helper builds must carry one by default — every test in
    # this file that never mentions "sticker" is testing something else
    # entirely (a name filter, a condition filter, ...) and must keep
    # constructing a customer-visible item to do it. Defaults to the same
    # figure as `price` (the old "the" price) so a test that asserted a bound
    # or sort against `price=` keeps asserting the same thing against the new
    # single authority. Pass `sticker_price=None` via `**extra`, or mutate the
    # returned item afterwards (this file's existing convention), to build a
    # stickerless (hidden) item on purpose.
    kw = {"sticker_price": Decimal(price)}
    kw.update(extra)
    return RawInventoryItem(
        card_id=card_id,
        listed_price=Decimal(price),
        cost_basis=Decimal("5.00"),
        acquired_at=date.today(),
        finish=finish,
        condition=condition,
        location=location,
        **kw,
    )


def _graded(card_id, *, grade="9", price="50.00", location="glass"):
    return GradedInventoryItem(
        card_id=card_id,
        listed_price=Decimal(price),
        sticker_price=Decimal(price),
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
    assert resp.json() == {"cards_in_vault": 0, "sets_tracked": 0}


def test_summary_no_longer_carries_est_value(inv_client, mint_token):
    """RFC 0025 T5 — the owner asked for the Est. value widget removed, not
    relabeled. A tripwire: the field's absence is a deliberate contract
    change, not a thing that should silently come back."""
    client, repo = inv_client
    item = _raw("sv1-1", price="10.00")
    item.current_market_value = Decimal("100.00")
    repo.put_inventory_item(item)

    resp = client.get(
        "/inventory/summary",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200
    assert "est_value" not in resp.json()


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
        card_id=None, listed_price=Decimal("5.00"), sticker_price=Decimal("5.00"),
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


# ---- RFC 0025 T2 — a customer price IS the sticker; no sticker, no listing ----
#
# A stickerless card in the vault is a routine state — the Prep Queue
# (/admin/outgoing) exists specifically to find unstickered available
# inventory — not an edge case. `_raw`'s default `sticker_price` (mirroring
# `price`) is what keeps every test ABOVE this point passing unmodified; the
# tests below exercise the sticker rule itself.

def test_customer_visible_items_excludes_a_stickerless_item(dynamo_repo):
    """An available, glass-located raw item with NO sticker price must not
    reach a customer — a human has not yet decided what to charge for it."""
    from merlins_collection.routers.inventory import customer_visible_items

    stickerless = _raw("sv1-1")
    stickerless.sticker_price = None
    dynamo_repo.put_inventory_item(stickerless)

    items = customer_visible_items(dynamo_repo)

    assert items == []


def test_customer_visible_items_includes_a_stickered_item(dynamo_repo):
    """The same item, once it carries a sticker price, is visible."""
    from merlins_collection.routers.inventory import customer_visible_items

    stickered = _raw("sv1-1")
    stickered.sticker_price = Decimal("25.00")
    dynamo_repo.put_inventory_item(stickered)

    items = customer_visible_items(dynamo_repo)

    assert [i.card_id for i in items] == ["sv1-1"]


def test_display_price_returns_the_sticker_and_never_falls_back():
    """`_display_price` is the sticker, full stop — never `card.market_price`
    (which may be wildly different, and is a Near Mint catalog figure, not a
    price a human set holding this specific card) and never `listed_price`
    (permanently dead, RFC 0008 §B). A direct unit test: `GET /inventory/search`
    keeps its wire shape unchanged (the RFC's own API contract) — `listed_price`
    and `card.market_price` are the item's own real values, unrelated to what
    `_display_price` resolves to; only the filter bound and the sort order are
    driven by it, which the tests below this one exercise through the endpoint."""
    from merlins_collection.routers.inventory import _display_price, _enrich

    card = _catalog("sv1-1", "Charizard",
                     prices={"holofoil": FinishPrice(market=Decimal("999.00"))})
    item = _raw("sv1-1")
    item.sticker_price = Decimal("25.00")
    item.listed_price = Decimal("40.00")

    enriched = _enrich(item, card)

    assert _display_price(enriched) == Decimal("25.00")


def test_price_bound_filters_against_the_sticker(inv_client, mint_token):
    client, repo = inv_client
    cheap = _raw("sv1-cheap")
    cheap.sticker_price = Decimal("5.00")
    repo.put_inventory_item(cheap)
    pricey = _raw("sv1-pricey")
    pricey.sticker_price = Decimal("500.00")
    repo.put_inventory_item(pricey)

    resp = client.get(
        "/inventory/search",
        params={"max_price": "100"},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200
    ids = {i["card_id"] for i in resp.json()["items"]}
    assert ids == {"sv1-cheap"}


def test_hidden_no_price_is_structurally_zero(inv_client, mint_token):
    """Every customer-visible item now HAS a sticker (the visibility gate
    itself requires one), so the price bound can never exclude one for lack
    of a resolvable price — `hidden_no_price` is always 0. Kept as a live
    field and counting path rather than deleted (a contract change for no
    gain); this test turns it into a tripwire instead of dead code."""
    client, repo = inv_client
    item = _raw("sv1-1")
    item.sticker_price = Decimal("10.00")
    repo.put_inventory_item(item)

    resp = client.get(
        "/inventory/search",
        params={"max_price": "1"},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200
    assert resp.json()["hidden_no_price"] == 0


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


def test_price_filter_matches_on_the_sticker_price(inv_client, mint_token):
    """RFC 0025 T2 superseded the old live-catalog/stale-denormalized
    reconciliation this test used to exercise (`_display_price` no longer
    reads the catalog or `current_market_value` at all) — the filter now
    binds against the sticker, full stop."""
    client, repo = inv_client
    under_bound = _raw("sv1-1")
    under_bound.sticker_price = Decimal("30.00")
    repo.put_inventory_item(under_bound)
    over_bound = _raw("sv1-2")
    over_bound.sticker_price = Decimal("80.00")
    repo.put_inventory_item(over_bound)

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


def test_search_response_carries_sticker_price(inv_client, mint_token):
    """RFC 0025 follow-ups #7: the wire item must carry ``sticker_price`` —

    ``_display_price`` (the filter bound and the sort) became ``sticker_price``
    under RFC 0025, but the item itself never gained the field on
    ``_CUSTOMER_ITEM_FIELDS``, so the frontend tile kept reading the OLD
    ``card.market_price ?? listed_price`` computation: a customer could
    filter/sort by one price and see a different one rendered. This is the
    regression test for adding ``sticker_price`` to the allowlist.
    """
    client, repo = inv_client
    repo.put_inventory_item(_raw("sv1-sticker", price="10.00", sticker_price=Decimal("42.00")))
    resp = client.get(
        "/inventory/search",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert item["sticker_price"] == "42.00"


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


# ---------------------------------------------------------------------------
# PHASE 12's "priceless item" test family (once six tests here) is GONE, not
# adapted — RFC 0025 T2 removed the scenario it existed to cover. Every test
# below this comment used to seed a customer-visible item with
# `listed_price=None` and `current_market_value=None` to construct a
# "priceless but visible" row and assert on `hidden_no_price`'s count. That
# row can no longer exist: `is_customer_visible` now requires a sticker
# price, so a "priceless customer-visible item" is a contradiction, and
# `hidden_no_price` is structurally always 0 — pinned by the single tripwire
# test `test_hidden_no_price_is_structurally_zero` above, per the RFC's own
# instruction ("removing it is a contract change for no gain... add a test
# asserting it is zero"). Six narrow tests asserting nonzero counts against
# an impossible fixture would each have to be rewritten into a duplicate of
# that one tripwire; deleting them is not a coverage loss.
# ---------------------------------------------------------------------------


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
    """RFC 0025 T2: price_desc sorts by the STICKER price — the single figure
    `_display_price` now resolves to for every result (a customer-visible
    item always has one; "priceless last" is no longer a reachable case here,
    since a priceless item can no longer be customer-visible at all — see
    `test_hidden_no_price_is_structurally_zero`)."""
    client, repo = inv_client
    repo.batch_upsert_catalog_cards([
        _catalog("sv1-1", "Cheap"),
        _catalog("sv1-2", "Expensive"),
    ])
    cheap = _raw("sv1-1")
    cheap.sticker_price = Decimal("10.00")
    repo.put_inventory_item(cheap)
    expensive = _raw("sv1-2")
    expensive.sticker_price = Decimal("100.00")
    repo.put_inventory_item(expensive)

    resp = client.get(
        "/inventory/search?sort=price_desc",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    body = resp.json()
    names = [i["card"]["name"] for i in body["items"]]
    assert names == ["Expensive", "Cheap"]


def test_sort_by_price_asc(inv_client, mint_token):
    """price_asc sorts by the sticker price ascending."""
    client, repo = inv_client
    repo.batch_upsert_catalog_cards([
        _catalog("sv1-1", "Cheap"),
        _catalog("sv1-2", "Expensive"),
    ])
    cheap = _raw("sv1-1")
    cheap.sticker_price = Decimal("10.00")
    repo.put_inventory_item(cheap)
    expensive = _raw("sv1-2")
    expensive.sticker_price = Decimal("100.00")
    repo.put_inventory_item(expensive)

    resp = client.get(
        "/inventory/search?sort=price_asc",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    body = resp.json()
    names = [i["card"]["name"] for i in body["items"]]
    assert names == ["Cheap", "Expensive"]


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
# RFC 0008 §A / T1's original invariant — filter, sort, and (formerly) the
# tile must never diverge on what "the price" of a card is — SURVIVES RFC
# 0025 T2, but its old test fixtures do not: `_display_price` used to
# reconcile a LIVE catalog figure against a STALE nightly-denormalized
# `current_market_value` (the "Rayquaza displayed $517, passed max_price=500"
# bug), and every test in that block seeded items with `listed_price=None`
# specifically to exercise that reconciliation. RFC 0025 deleted the
# reconciliation itself — `_display_price` is now `item.sticker_price`, a
# single stored field with nothing to disagree with — so those fixtures
# no longer test a reachable code path. Replaced with the equivalent
# single-authority check in sticker terms: bound and sort still agree,
# because both still resolve through the one `_display_price` function.
# ---------------------------------------------------------------------------

def test_price_bound_and_price_sort_agree_on_the_same_figure(inv_client, mint_token):
    client, repo = inv_client
    cheap = _raw("sv1-cheap")
    cheap.sticker_price = Decimal("100.00")
    repo.put_inventory_item(cheap)
    mid = _raw("sv1-mid")
    mid.sticker_price = Decimal("300.00")
    repo.put_inventory_item(mid)
    dear = _raw("sv1-dear")
    dear.sticker_price = Decimal("700.00")
    repo.put_inventory_item(dear)

    resp = client.get(
        "/inventory/search?max_price=500&sort=price_desc",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert [i["card_id"] for i in body["items"]] == ["sv1-mid", "sv1-cheap"]


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


