"""Tests for the unauthenticated ``/public`` router (shows + featured cards).

These endpoints expose ONLY safe fields via purpose-built response models and
must never require auth. The in-process TTL cache is cleared before each test so
one test's seeded data never leaks into the next.
"""

import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from merlins_collection.models.business import Show
from merlins_collection.models.catalog import CardImages, CatalogCard
from merlins_collection.models.inventory import (
    BulkInventoryItem,
    Condition,
    GradedInventoryItem,
    GradingCompany,
    ItemStatus,
    RawInventoryItem,
    SealedInventoryItem,
    SealedProductType,
)

# ---- seed helpers ----

def _catalog(card_id, name, *, set_id="sv1", small=None):
    url = small if small is not None else f"https://images.pokemontcg.io/{card_id}.png"
    return CatalogCard(
        card_id=card_id,
        name=name,
        set_id=set_id,
        set_name="Scarlet & Violet",
        number="001",
        rarity="Common",
        images=CardImages(small=url, large="https://images.pokemontcg.io/large.png"),
        last_synced_at=datetime.now(tz=timezone.utc),
    )


def _raw(card_id, *, market=None, listed="10.00", status=ItemStatus.AVAILABLE):
    # RFC 0025 T2: `customer_visible_items` (called by the featured endpoint)
    # now requires a sticker price. The featured endpoint's own market-first
    # RANKING is untouched by this RFC (`GET /public/featured`'s API contract
    # stays "unchanged shape; the cohort narrows") — only the VISIBILITY gate
    # does, so `sticker_price` is set independently of `market`/`listed` here
    # rather than derived from either, and defaults to always-visible.
    return RawInventoryItem(
        card_id=card_id,
        status=status,
        listed_price=Decimal(listed) if listed is not None else None,
        current_market_value=Decimal(market) if market is not None else None,
        sticker_price=Decimal("10.00"),
        cost_basis=Decimal("5.00"),
        acquired_at=date.today(),
        finish="holofoil",
        condition=Condition.NM,
        location="glass",
    )


def _graded(card_id, *, market=None, listed="50.00"):
    return GradedInventoryItem(
        card_id=card_id,
        listed_price=Decimal(listed) if listed is not None else None,
        current_market_value=Decimal(market) if market is not None else None,
        sticker_price=Decimal("50.00"),
        cost_basis=Decimal("30.00"),
        acquired_at=date.today(),
        company=GradingCompany.PSA,
        grade=Decimal("9"),
        cert_number="12345678",
        location="glass",
    )


# ---- fixture ----

@pytest.fixture
def pub_client(dynamo_repo):
    """TestClient with only the repo overridden — public routes need no auth."""
    from merlins_collection.dependencies import get_repo
    from merlins_collection.main import app
    from merlins_collection.routers import public

    public.reset_caches()
    app.dependency_overrides[get_repo] = lambda: dynamo_repo
    yield TestClient(app), dynamo_repo
    app.dependency_overrides.clear()
    public.reset_caches()


# ---- featured cards ----

def test_featured_cards_returns_top_available_by_value(pub_client):
    client, repo = pub_client
    repo.batch_upsert_catalog_cards([
        _catalog("c1", "Lugia"),
        _catalog("c2", "Charizard"),
        _catalog("c3", "Pikachu"),
    ])
    repo.put_inventory_item(_raw("c1", market="100.00"))
    repo.put_inventory_item(_raw("c2", market="300.00"))
    repo.put_inventory_item(_raw("c3", market="200.00"))

    resp = client.get("/public/featured-cards")
    assert resp.status_code == 200
    names = [c["name"] for c in resp.json()["cards"]]
    assert names == ["Charizard", "Pikachu", "Lugia"]


def test_featured_cards_caps_at_five(pub_client):
    client, repo = pub_client
    repo.batch_upsert_catalog_cards([_catalog(f"c{i}", f"Card {i}") for i in range(8)])
    for i in range(8):
        repo.put_inventory_item(_raw(f"c{i}", market=f"{i}0.00"))

    resp = client.get("/public/featured-cards")
    assert resp.status_code == 200
    assert len(resp.json()["cards"]) == 5


def test_featured_cards_uses_listed_price_when_market_absent(pub_client):
    client, repo = pub_client
    repo.batch_upsert_catalog_cards([_catalog("c1", "Lugia"), _catalog("c2", "Mew")])
    # c1 has no market but a high listed price; c2 has a lower market value.
    repo.put_inventory_item(_raw("c1", market=None, listed="500.00"))
    repo.put_inventory_item(_raw("c2", market="200.00", listed="1.00"))

    resp = client.get("/public/featured-cards")
    names = [c["name"] for c in resp.json()["cards"]]
    assert names == ["Lugia", "Mew"]


def test_featured_cards_excludes_items_without_catalog_image(pub_client):
    client, repo = pub_client
    repo.batch_upsert_catalog_cards([
        _catalog("c1", "Lugia"),
        _catalog("c2", "NoImage", small=""),  # catalog card lacks an image
    ])
    repo.put_inventory_item(_raw("c1", market="100.00"))
    repo.put_inventory_item(_raw("c2", market="900.00"))   # highest value, but no image
    repo.put_inventory_item(_raw("c3", market="999.00"))   # card_id not in catalog

    resp = client.get("/public/featured-cards")
    names = [c["name"] for c in resp.json()["cards"]]
    assert names == ["Lugia"]


def test_featured_cards_excludes_non_available_and_non_customer_kinds(pub_client):
    client, repo = pub_client
    repo.batch_upsert_catalog_cards([_catalog("c1", "Lugia"), _catalog("c2", "Sold")])
    repo.put_inventory_item(_raw("c1", market="100.00"))
    repo.put_inventory_item(_raw("c2", market="900.00", status=ItemStatus.SOLD))
    repo.put_inventory_item(
        SealedInventoryItem(
            product_name="Booster Box", product_type=SealedProductType.BOOSTER_BOX,
            cost_basis=Decimal("50.00"), acquired_at=date.today(),
            current_market_value=Decimal("800.00"),
        )
    )
    repo.put_inventory_item(
        BulkInventoryItem(
            description="Bulk lot", cost_basis=Decimal("5.00"),
            acquired_at=date.today(), current_market_value=Decimal("700.00"),
        )
    )

    resp = client.get("/public/featured-cards")
    names = [c["name"] for c in resp.json()["cards"]]
    assert names == ["Lugia"]


def test_featured_cards_returns_empty_list_when_none_qualify(pub_client):
    client, repo = pub_client
    # An available raw item with no card_id (the ~93% NULL reality) — nothing to show.
    repo.put_inventory_item(_raw(None, market="100.00"))

    resp = client.get("/public/featured-cards")
    assert resp.status_code == 200
    assert resp.json() == {"cards": []}


def test_featured_cards_exposes_only_name_and_image(pub_client):
    client, repo = pub_client
    repo.batch_upsert_catalog_cards([_catalog("c1", "Lugia")])
    repo.put_inventory_item(_raw("c1", market="100.00"))

    resp = client.get("/public/featured-cards")
    card = resp.json()["cards"][0]
    assert set(card.keys()) == {"name", "image_url"}
    assert card["image_url"].startswith("https://images.pokemontcg.io/")


def test_featured_cards_excludes_non_allowlisted_or_insecure_image_hosts(pub_client):
    """A card whose image is NOT https-on-allowlisted-host must not qualify — such a
    URL would throw inside next/image at SSR and 500 the whole home page."""
    client, repo = pub_client
    repo.batch_upsert_catalog_cards([
        _catalog("c1", "Good"),  # https://images.pokemontcg.io/... (allowed)
        _catalog("c2", "EvilHost", small="https://evil.example.com/x.png"),
        _catalog("c3", "Insecure", small="http://images.pokemontcg.io/x.png"),  # not https
        _catalog("c4", "Relative", small="/images/x.png"),
        _catalog("c5", "Garbage", small="not a url"),
    ])
    # Give the bad ones the highest values so ONLY host-filtering can exclude them.
    repo.put_inventory_item(_raw("c1", market="10.00"))
    repo.put_inventory_item(_raw("c2", market="900.00"))
    repo.put_inventory_item(_raw("c3", market="800.00"))
    repo.put_inventory_item(_raw("c4", market="700.00"))
    repo.put_inventory_item(_raw("c5", market="600.00"))

    resp = client.get("/public/featured-cards")
    names = [c["name"] for c in resp.json()["cards"]]
    assert names == ["Good"]


def test_featured_cards_accepts_tcgdex_hosted_images(pub_client):
    """The catalog is now seeded from TCGdex, which serves every card image from
    ``assets.tcgdex.net`` (see ``services/tcgdex.py`` ALLOWED_IMAGE_HOSTS, which
    DROPS an image on any other host). With the old pokemontcg.io-only allowlist
    here, no reseeded card could ever qualify and the home page's featured strip
    went silently empty. ``next.config.ts`` already allows this host; this keeps
    the backend in the lockstep its own comment demands."""
    client, repo = pub_client
    repo.batch_upsert_catalog_cards([
        _catalog("c1", "Tcgdex", small="https://assets.tcgdex.net/en/sv/sv01/1/high.png"),
    ])
    repo.put_inventory_item(_raw("c1", market="10.00"))

    resp = client.get("/public/featured-cards")
    names = [c["name"] for c in resp.json()["cards"]]
    assert names == ["Tcgdex"]


def test_featured_cards_dedupes_by_card_id_keeping_highest_ranked(pub_client):
    """Multiple copies of one card (same card_id) render at most one tile."""
    client, repo = pub_client
    repo.batch_upsert_catalog_cards([_catalog("c1", "Lugia"), _catalog("c2", "Mew")])
    repo.put_inventory_item(_raw("c1", market="100.00"))
    repo.put_inventory_item(_raw("c1", market="90.00"))
    repo.put_inventory_item(_raw("c1", market="80.00"))
    repo.put_inventory_item(_raw("c2", market="50.00"))

    resp = client.get("/public/featured-cards")
    names = [c["name"] for c in resp.json()["cards"]]
    assert names == ["Lugia", "Mew"]  # Lugia appears exactly once


# ---- Pacific business-day split (item 3) ----

class _FrozenDatetime:
    """Stand-in for public.datetime whose now() is a fixed UTC instant."""

    # 2026-08-15 02:00 UTC == 2026-08-14 19:00 America/Los_Angeles.
    _INSTANT = datetime(2026, 8, 15, 2, 0, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz=None):
        return cls._INSTANT.astimezone(tz) if tz is not None else cls._INSTANT.replace(tzinfo=None)


def test_business_today_is_pacific_not_server_utc(monkeypatch):
    from merlins_collection.routers import public

    monkeypatch.setattr(public, "datetime", _FrozenDatetime)
    # UTC date is Aug 15, but the Pacific business day is still Aug 14.
    assert public._business_today() == date(2026, 8, 14)


def test_shows_split_uses_pacific_business_day(pub_client, monkeypatch):
    from merlins_collection.routers import public

    monkeypatch.setattr(public, "datetime", _FrozenDatetime)
    public.reset_caches()
    client, repo = pub_client
    # On the UTC server it's already Aug 15; a show dated Aug 14 must still be
    # UPCOMING because it's today in Pacific (RFC boundary: today == upcoming).
    _seed_show(repo, "Today In Pacific", date(2026, 8, 14))
    _seed_show(repo, "Yesterday", date(2026, 8, 13))

    body = client.get("/public/shows").json()
    assert [s["name"] for s in body["upcoming"]] == ["Today In Pacific"]
    assert [s["name"] for s in body["past"]] == ["Yesterday"]


# ---- TTL cache: single-flight + serve-stale-on-error (item 2) ----

def test_ttl_cache_coalesces_concurrent_burst_to_one_compute():
    from concurrent.futures import ThreadPoolExecutor

    from merlins_collection.routers.public import _TTLCache

    cache = _TTLCache(300)
    calls = {"n": 0}

    def compute():
        calls["n"] += 1
        time.sleep(0.1)  # widen the window so a naive cache would let others in
        return "value"

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: cache.get_or_compute(compute), range(8)))

    assert calls["n"] == 1, "a concurrent burst must coalesce to ONE scan"
    assert results == ["value"] * 8


def test_ttl_cache_serves_last_known_good_on_compute_error():
    from merlins_collection.routers.public import _TTLCache

    cache = _TTLCache(0)  # ttl=0 -> always considered stale, so it recomputes
    assert cache.get_or_compute(lambda: "good") == "good"

    def boom():
        raise RuntimeError("DynamoDB brown-out")

    # A failing recompute serves the last-known-good value, not an exception and
    # not a fresh table scan on every subsequent hit.
    assert cache.get_or_compute(boom) == "good"


# ---- Item 1: error-backoff suppresses the brown-out re-scan storm ----

def test_ttl_cache_error_backoff_suppresses_rescan_storm():
    """During a sustained upstream failure the cache must NOT re-run the failing
    scan on every request — it serves last-known-good behind a backoff window."""
    from merlins_collection.routers.public import _TTLCache

    cache = _TTLCache(0, error_backoff=30)  # ttl=0 => never "fresh" by ttl alone
    calls = {"n": 0}

    def good():
        calls["n"] += 1
        return "good"

    def boom():
        calls["n"] += 1
        raise RuntimeError("DynamoDB brown-out")

    assert cache.get_or_compute(good) == "good"   # n == 1 (seed a good value)
    assert cache.get_or_compute(boom) == "good"   # n == 2 (failing scan opens backoff)
    # Every subsequent request inside the backoff window serves stale WITHOUT
    # re-running the failing scan.
    for _ in range(20):
        assert cache.get_or_compute(boom) == "good"
    assert calls["n"] == 2, (
        "compute must be bounded during the error-backoff window, not run per request"
    )


def test_ttl_cache_recovers_after_error_backoff_elapses():
    """Once the backoff window elapses and a scan succeeds, the fresh value serves."""
    from merlins_collection.routers.public import _TTLCache

    cache = _TTLCache(0, error_backoff=0.05)

    def boom():
        raise RuntimeError("DynamoDB brown-out")

    assert cache.get_or_compute(lambda: "old") == "old"
    assert cache.get_or_compute(boom) == "old"      # enters backoff, serves stale
    time.sleep(0.06)                                 # let the backoff window elapse
    assert cache.get_or_compute(lambda: "new") == "new"  # recompute runs and recovers


def test_ttl_cache_first_call_error_propagates_with_no_value():
    """A first-call error with NO prior value must still raise — never serve a
    value that does not exist."""
    from merlins_collection.routers.public import _TTLCache

    cache = _TTLCache(300)

    def boom():
        raise RuntimeError("DynamoDB brown-out")

    with pytest.raises(RuntimeError):
        cache.get_or_compute(boom)


# ---- Item 3: bounded lock acquisition (a hung scan can't wedge callers forever) ----

def test_ttl_cache_acquire_timeout_serves_last_known_good():
    """If a prior scan is wedged holding the lock, a new caller must not block
    indefinitely — it serves last-known-good after the acquire timeout."""
    from merlins_collection.routers.public import _TTLCache

    cache = _TTLCache(300, lock_timeout=0.05)
    assert cache.get_or_compute(lambda: "good") == "good"

    # Simulate a hung scan by holding the lock from this thread; the next call's
    # acquire must time out and fall back to the cached value.
    assert cache._lock.acquire()
    try:
        assert cache.get_or_compute(lambda: "never-runs") == "good"
    finally:
        cache._lock.release()


def test_ttl_cache_acquire_timeout_without_value_raises_503():
    """A wedged lock with NO cached value fails cleanly (503-style) rather than
    blocking forever."""
    from fastapi import HTTPException

    from merlins_collection.routers.public import _TTLCache

    cache = _TTLCache(300, lock_timeout=0.05)
    assert cache._lock.acquire()
    try:
        with pytest.raises(HTTPException) as exc_info:
            cache.get_or_compute(lambda: "never-runs")
        assert exc_info.value.status_code == 503
    finally:
        cache._lock.release()


# ---- per-IP rate limiting on the public surface (item 2c) ----

class _AlwaysLimited:
    def check(self, tiers, *, now=None):
        from merlins_collection.rate_limit import RateLimitResult

        return RateLimitResult(limited=True, retry_after=30)


def test_public_endpoints_carry_a_rate_cap(pub_client):
    from merlins_collection.main import app
    from merlins_collection.rate_limit import get_rate_limiter

    client, _ = pub_client
    app.dependency_overrides[get_rate_limiter] = lambda: _AlwaysLimited()
    try:
        assert client.get("/public/shows").status_code == 429
        assert client.get("/public/featured-cards").status_code == 429
    finally:
        app.dependency_overrides.pop(get_rate_limiter, None)


class _BrokenLimiter:
    def check(self, tiers, *, now=None):
        from merlins_collection.rate_limit import RateLimiterUnavailable

        raise RateLimiterUnavailable("simulated DynamoDB failure")


def test_public_endpoints_fail_open_when_limiter_unavailable(pub_client):
    """The public reads are cheap, so a broken limiter must not take them down —
    they fail OPEN (serve) rather than 503."""
    from merlins_collection.main import app
    from merlins_collection.rate_limit import get_rate_limiter

    client, _ = pub_client
    app.dependency_overrides[get_rate_limiter] = lambda: _BrokenLimiter()
    try:
        assert client.get("/public/shows").status_code == 200
        assert client.get("/public/featured-cards").status_code == 200
    finally:
        app.dependency_overrides.pop(get_rate_limiter, None)


# ---- shows ----

def _seed_show(repo, name, day, *, venue=None, city=None):
    repo.put_show(Show(name=name, date=day, venue=venue, city=city))


def test_shows_splits_upcoming_and_past_by_today(pub_client):
    client, repo = pub_client
    today = date.today()
    _seed_show(repo, "Future Show", today + timedelta(days=10))
    _seed_show(repo, "Old Show", today - timedelta(days=10))

    body = client.get("/public/shows").json()
    assert [s["name"] for s in body["upcoming"]] == ["Future Show"]
    assert [s["name"] for s in body["past"]] == ["Old Show"]


def test_shows_upcoming_ascending_past_descending(pub_client):
    client, repo = pub_client
    today = date.today()
    _seed_show(repo, "Near", today + timedelta(days=5))
    _seed_show(repo, "Far", today + timedelta(days=20))
    _seed_show(repo, "Recent", today - timedelta(days=5))
    _seed_show(repo, "Ancient", today - timedelta(days=20))

    body = client.get("/public/shows").json()
    assert [s["name"] for s in body["upcoming"]] == ["Near", "Far"]
    assert [s["name"] for s in body["past"]] == ["Recent", "Ancient"]


def test_shows_show_on_today_is_upcoming(pub_client):
    client, repo = pub_client
    _seed_show(repo, "Today Show", date.today())

    body = client.get("/public/shows").json()
    assert [s["name"] for s in body["upcoming"]] == ["Today Show"]
    assert body["past"] == []


def test_shows_past_limited_to_90_days(pub_client):
    """A show older than 90 days is excluded from the past list (Phase 16)."""
    client, repo = pub_client
    # Use the same business-timezone "today" the router uses so the test is not
    # sensitive to UTC vs Pacific clock skew in CI.
    from merlins_collection.routers.public import _business_today
    today = _business_today()
    _seed_show(repo, "Recent", today - timedelta(days=30))
    _seed_show(repo, "Old", today - timedelta(days=89))
    _seed_show(repo, "Too Old", today - timedelta(days=91))
    _seed_show(repo, "Ancient", today - timedelta(days=180))

    body = client.get("/public/shows").json()
    past_names = [s["name"] for s in body["past"]]
    assert "Recent" in past_names
    assert "Old" in past_names
    assert "Too Old" not in past_names
    assert "Ancient" not in past_names


def test_shows_exposes_only_safe_fields(pub_client):
    client, repo = pub_client
    repo.put_show(Show(
        name="Rich Show", date=date.today() + timedelta(days=3),
        venue="Hall A", city="Portland, OR",
        sales_goal=Decimal("500"), cash_at_start=Decimal("200"),
        inventory_value_at_start=Decimal("3000"), notes="internal note",
    ))

    show = client.get("/public/shows").json()["upcoming"][0]
    assert set(show.keys()) == {"name", "date", "venue", "city"}


def test_shows_renders_missing_venue_city_as_null(pub_client):
    client, repo = pub_client
    _seed_show(repo, "Bare Show", date.today() + timedelta(days=1))

    show = client.get("/public/shows").json()["upcoming"][0]
    assert show["venue"] is None
    assert show["city"] is None


def test_shows_empty_when_no_shows(pub_client):
    client, _ = pub_client
    assert client.get("/public/shows").json() == {"upcoming": [], "past": []}
