"""Tests for the admin market lookup router (``/admin/market/...``).

Covers catalog search, card detail, price trend, and watchlist CRUD.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from merlins_collection.models.catalog import (
    CardImages,
    CatalogCard,
    FinishPrice,
    PricePoint,
)
from merlins_collection.models.inventory import (
    Condition,
    RawInventoryItem,
    SealedInventoryItem,
    SealedProductType,
)


# ---- helpers ----

def _catalog_card(card_id="en:sv1-1", name="Pikachu", set_id="sv1",
                  set_name="Scarlet & Violet", number="001", rarity="Common",
                  prices=None, detail="brief"):
    return CatalogCard(
        card_id=card_id,
        name=name,
        set_id=set_id,
        set_name=set_name,
        number=number,
        rarity=rarity,
        images=CardImages(
            small="https://example.com/small.webp",
            large="https://example.com/large.webp",
        ),
        last_synced_at=datetime.now(tz=timezone.utc),
        prices=prices or {},
        detail=detail,
    )


# ---- fixtures ----

@pytest.fixture(autouse=True)
def _reset_sync_status_dicts():
    """Round-1 finding, fixed here (Task 2.8): both sync-run status dicts are
    module-level mutable state, so a test that stamps one to `"running"` (or
    leaves it `"completed"`) without resetting it leaks into whichever test
    runs next -- order-dependence that gets worse now that there are two of
    these dicts instead of one. Reset both to their idle shape after every
    test regardless of how it left them."""
    yield
    from merlins_collection.routers.admin import market

    market._SYNC_STATUS.update({
        "state": "idle", "started_at": None, "finished_at": None,
        "priced_cards": None, "updated_items": None, "error": None,
    })
    market._CATALOG_SYNC_STATUS.update({
        "state": "idle", "started_at": None, "finished_at": None,
        "sets_checked": None, "new_sets": None, "cards_added": None,
        "error": None,
    })


# ``admin_client`` now comes from ``conftest.py`` in this package; the identical
# copy that used to sit here was one of sixteen.


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ===========================================================================
# Catalog Search
# ===========================================================================

class TestAdminMarketSearch:
    """GET /admin/market/search — search catalog cards by name/set."""

    def test_search_by_name(self, admin_client):
        client, repo, token = admin_client
        repo.batch_upsert_catalog_cards([
            _catalog_card(card_id="en:sv1-1", name="Pikachu"),
            _catalog_card(card_id="en:sv1-2", name="Charizard", number="002"),
        ])

        resp = client.get("/admin/market/search?name=pika", headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        assert any("Pikachu" in item["name"] for item in data["items"])

    def test_search_by_set(self, admin_client):
        client, repo, token = admin_client
        repo.batch_upsert_catalog_cards([
            _catalog_card(card_id="en:sv1-1", set_id="sv1"),
            _catalog_card(card_id="en:base1-4", name="Charizard",
                          set_id="base1", set_name="Base Set"),
        ])

        resp = client.get("/admin/market/search?set_id=sv1", headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert all(item["set_id"] == "sv1" for item in data["items"])

    def test_search_returns_prices(self, admin_client):
        client, repo, token = admin_client
        prices = {"holofoil": FinishPrice(market=Decimal("189.99"), source="tcgplayer")}
        repo.batch_upsert_catalog_cards([
            _catalog_card(card_id="en:base1-4", name="Charizard", prices=prices),
        ])

        resp = client.get("/admin/market/search?name=charizard", headers=_auth(token))
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) >= 1
        assert "prices" in items[0]

    def test_search_empty_returns_empty(self, admin_client):
        client, _, token = admin_client
        resp = client.get("/admin/market/search?name=nonexistent", headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_search_caps_results_at_50(self, admin_client):
        client, repo, token = admin_client
        repo.batch_upsert_catalog_cards([
            _catalog_card(card_id=f"en:sv1-{i}", name="Pikachu", number=str(i))
            for i in range(60)
        ])

        resp = client.get("/admin/market/search?name=pikachu", headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 50
        assert data["total"] == 60

    def test_search_filters_by_number(self, admin_client):
        client, repo, token = admin_client
        repo.batch_upsert_catalog_cards([
            _catalog_card(card_id="en:sv1-25", name="Pikachu", number="25"),
            _catalog_card(card_id="en:sv1-26", name="Pikachu", number="26"),
        ])

        resp = client.get(
            "/admin/market/search?name=pikachu&number=25", headers=_auth(token)
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["number"] == "25"


class TestAdminMarketSearchDisplayPrice:
    """The picker's price column (RFC 0010 T15).

    A card picker must show name, image AND price (CLAUDE.md). ``prices`` is
    keyed by finish, so "the price of this card" needs a *choice* — and a
    catalog result has no item and therefore no finish, so the frontend cannot
    make it. The backend picks the figure with the one shared authority,
    ``models.inventory._market_price``, and hands the picker a flat
    ``display_price`` plus the ``display_finish`` it came from.
    """

    def _first(self, client, token, name):
        resp = client.get(f"/admin/market/search?name={name}", headers=_auth(token))
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) >= 1
        return items[0]

    def test_search_returns_display_price_and_finish(self, admin_client):
        client, repo, token = admin_client
        repo.batch_upsert_catalog_cards([
            _catalog_card(
                card_id="en:sv1-25", name="Pikachu", detail="full",
                prices={"normal": FinishPrice(market=Decimal("12.34"),
                                              source="tcgplayer")},
            ),
        ])

        item = self._first(client, token, "pikachu")
        assert item["display_price"] == "12.34"
        assert item["display_finish"] == "normal"

    def test_holofoil_only_card_still_yields_a_figure(self, admin_client):
        """Proves the fallback WALK is used, not an exact 'normal' match.

        A holo-only card carries no ``normal`` band at all. If this returns
        ``None`` the endpoint is doing a dict lookup instead of calling
        ``_market_price`` — the exact divergence that left 174 of 213 live
        items unpriced.
        """
        client, repo, token = admin_client
        repo.batch_upsert_catalog_cards([
            _catalog_card(
                card_id="en:base1-4", name="Charizard", detail="full",
                prices={"holofoil": FinishPrice(market=Decimal("189.99"),
                                                source="tcgplayer")},
            ),
        ])

        item = self._first(client, token, "charizard")
        assert item["display_price"] == "189.99"
        assert item["display_finish"] == "holofoil"

    def test_card_with_no_bands_yields_null_not_zero(self, admin_client):
        """An absent price is ABSENT. Never ``0``, never ``"0"``, never ``""``.

        ``FinishPrice`` bands are only written when a provider published a
        figure, so a card with no bands has no price — and rendering that as
        ``$0.00`` would tell a buyer a card is worthless.
        """
        client, repo, token = admin_client
        repo.batch_upsert_catalog_cards([
            _catalog_card(card_id="en:sv1-99", name="Bulbasaur", detail="full"),
        ])

        item = self._first(client, token, "bulbasaur")
        assert item["display_price"] is None
        assert item["display_finish"] is None

    def test_detail_is_present_on_every_item(self, admin_client):
        """'never fetched' and 'no provider covers it' are DIFFERENT facts.

        ``detail`` is the only field that keeps them apart, so the picker
        cannot render them differently without it.
        """
        client, repo, token = admin_client
        repo.batch_upsert_catalog_cards([
            _catalog_card(card_id="en:sv1-1", name="Squirtle", detail="brief"),
            _catalog_card(card_id="en:sv1-2", name="Squirtle ex", number="002",
                          detail="full"),
        ])

        resp = client.get("/admin/market/search?name=squirtle", headers=_auth(token))
        items = resp.json()["items"]
        assert len(items) == 2
        assert {i["detail"] for i in items} == {"brief", "full"}


# ===========================================================================
# Card Detail
# ===========================================================================

class TestAdminMarketCardDetail:
    """GET /admin/market/card/{card_id}"""

    def test_get_card_detail(self, admin_client):
        client, repo, token = admin_client
        prices = {"holofoil": FinishPrice(market=Decimal("50.00"), source="tcgplayer")}
        repo.batch_upsert_catalog_cards([
            _catalog_card(card_id="en:sv1-25", name="Raichu", prices=prices),
        ])

        resp = client.get("/admin/market/card/en:sv1-25", headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Raichu"
        assert "prices" in data

    def test_get_nonexistent_card_returns_404(self, admin_client):
        client, _, token = admin_client
        resp = client.get("/admin/market/card/en:no-such-card", headers=_auth(token))
        assert resp.status_code == 404


# ===========================================================================
# Price Trend
# ===========================================================================

class TestAdminMarketPriceTrend:
    """GET /admin/market/card/{card_id}/trend"""

    def test_returns_price_history(self, admin_client):
        client, repo, token = admin_client
        repo.batch_upsert_catalog_cards([_catalog_card(card_id="en:sv1-1")])
        # Add price points within the last 30 days
        from datetime import timedelta
        from merlins_collection.models.catalog import PricePoint
        today = date.today()
        points = [
            PricePoint(card_id="en:sv1-1", date=today - timedelta(days=10),
                       source="tcgplayer", kind="raw", finish="holofoil",
                       market=Decimal("10.00")),
            PricePoint(card_id="en:sv1-1", date=today - timedelta(days=3),
                       source="tcgplayer", kind="raw", finish="holofoil",
                       market=Decimal("12.50")),
        ]
        repo.append_price_points(points)

        resp = client.get(
            "/admin/market/card/en:sv1-1/trend?finish=holofoil",
            headers=_auth(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "points" in data
        assert len(data["points"]) == 2

    def test_trend_nonexistent_card_returns_404(self, admin_client):
        client, _, token = admin_client
        resp = client.get("/admin/market/card/en:no-card/trend", headers=_auth(token))
        assert resp.status_code == 404


# ===========================================================================
# Watchlist
# ===========================================================================

class TestAdminWatchlist:
    """CRUD for /admin/watchlist"""

    def test_add_to_watchlist(self, admin_client):
        client, repo, token = admin_client
        payload = {
            "card_id": "en:sv1-1",
            "name": "Pikachu",
            "set_name": "Scarlet & Violet",
            "target_buy_price": "8.00",
            "notes": "Want for collection",
        }
        resp = client.post("/admin/watchlist", json=payload, headers=_auth(token))
        assert resp.status_code == 201
        data = resp.json()
        assert "entry_id" in data
        assert data["card_id"] == "en:sv1-1"

    def test_list_watchlist(self, admin_client):
        client, repo, token = admin_client
        # Add two entries
        client.post("/admin/watchlist", json={
            "card_id": "en:sv1-1", "name": "Pikachu", "set_name": "SV",
        }, headers=_auth(token))
        client.post("/admin/watchlist", json={
            "card_id": "en:sv1-2", "name": "Charizard", "set_name": "SV",
        }, headers=_auth(token))

        resp = client.get("/admin/watchlist", headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["entries"]) == 2

    def test_delete_watchlist_entry(self, admin_client):
        client, repo, token = admin_client
        # Add entry
        add_resp = client.post("/admin/watchlist", json={
            "card_id": "en:sv1-1", "name": "Pikachu", "set_name": "SV",
        }, headers=_auth(token))
        entry_id = add_resp.json()["entry_id"]

        # Delete it
        resp = client.delete(f"/admin/watchlist/{entry_id}", headers=_auth(token))
        assert resp.status_code == 200

        # Verify gone
        list_resp = client.get("/admin/watchlist", headers=_auth(token))
        assert list_resp.json()["entries"] == []

    def test_delete_nonexistent_returns_404(self, admin_client):
        client, _, token = admin_client
        resp = client.delete("/admin/watchlist/fake-id", headers=_auth(token))
        assert resp.status_code == 404


# ===========================================================================
# Coverage Report
# ===========================================================================

class TestAdminMarketCoverage:
    """GET /admin/market/coverage"""

    def test_coverage_reports_unmatched(self, admin_client):
        client, repo, token = admin_client
        repo.batch_upsert_catalog_cards([
            _catalog_card(
                card_id="en:sv1-1",
                prices={"holofoil": FinishPrice(market=Decimal("10.00"), source="tcgplayer")},
            ),
        ])
        repo.put_inventory_item(RawInventoryItem(
            card_id="en:sv1-1",
            cost_basis=Decimal("4"),
            acquired_at=date(2026, 1, 1),
            finish="holofoil",
            condition=Condition.NM,
            current_market_value=Decimal("10.00"),
        ))
        repo.put_inventory_item(SealedInventoryItem(
            product_name="Booster Box",
            product_type=SealedProductType.BOOSTER_BOX,
            cost_basis=Decimal("100"),
            acquired_at=date(2026, 1, 1),
        ))

        resp = client.get("/admin/market/coverage", headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_items"] == 2
        assert data["items_with_card_id"] == 1
        assert data["items_with_market_value"] == 1
        assert data["catalog_cards"] == 1
        assert data["catalog_cards_with_prices"] == 1
        assert data["item_coverage_pct"] == "50.0"
        assert len(data["unmatched_sample"]) == 1
        assert data["unmatched_sample"][0]["name"] == "Booster Box"

    def test_coverage_empty_reports_zero_pct(self, admin_client):
        client, _, token = admin_client
        resp = client.get("/admin/market/coverage", headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_items"] == 0
        assert data["item_coverage_pct"] == "0"


# ===========================================================================
# Sync Trigger
# ===========================================================================

class TestAdminMarketSync:
    """POST /admin/market/sync and GET /admin/market/sync/status"""

    def test_sync_endpoint_runs_refresh(self, admin_client, monkeypatch):
        client, repo, token = admin_client
        called = {}
        monkeypatch.setattr(
            "merlins_collection.routers.admin.market.refresh_held_prices",
            lambda repo, tcgdex_client, today: (
                called.update(prices=True) or {"cards_updated": 3}
            ),
        )
        monkeypatch.setattr(
            "merlins_collection.routers.admin.market.refresh_inventory_market_values",
            lambda repo: called.update(items=True) or 5,
        )

        resp = client.post("/admin/market/sync", headers=_auth(token))
        assert resp.status_code == 202
        assert resp.json() == {"state": "started"}

        status = client.get("/admin/market/sync/status", headers=_auth(token)).json()
        assert status["state"] == "completed", status.get("error")
        assert status["priced_cards"] == 3
        assert status["updated_items"] == 5
        assert called == {"prices": True, "items": True}

    def test_sync_returns_409_when_already_running(self, admin_client, monkeypatch):
        client, repo, token = admin_client
        # Never finishes on its own within this test — we directly stamp the
        # module status to "running" to simulate an in-flight sync.
        from merlins_collection.routers.admin import market

        market._SYNC_STATUS["state"] = "running"
        try:
            resp = client.post("/admin/market/sync", headers=_auth(token))
            assert resp.status_code == 409
        finally:
            market._SYNC_STATUS["state"] = "idle"


# ===========================================================================
# Catalog Sync (Task 2.8) — incremental "check for new sets"
# ===========================================================================

class TestAdminCatalogSync:
    """POST /admin/market/catalog-sync and GET /admin/market/catalog-sync/status

    Uses a SEPARATE module-level status dict (`_CATALOG_SYNC_STATUS`) from the
    price sync's `_SYNC_STATUS` -- the two jobs are independently runnable and
    independently reportable.
    """

    def test_catalog_sync_endpoint_starts_and_reports(self, admin_client, monkeypatch):
        client, repo, token = admin_client
        called = {}
        monkeypatch.setattr(
            "merlins_collection.routers.admin.market.sync_new_sets",
            lambda repo, tcgdex_client: (
                called.update(ran=True) or {
                    "sets_checked": 5, "new_sets": ["en:swsh9"], "cards_added": 120,
                }
            ),
        )

        resp = client.post("/admin/market/catalog-sync", headers=_auth(token))
        assert resp.status_code == 202
        assert resp.json() == {"state": "started"}

        status = client.get(
            "/admin/market/catalog-sync/status", headers=_auth(token)
        ).json()
        assert status["state"] == "completed", status.get("error")
        assert status["sets_checked"] == 5
        assert status["new_sets"] == ["en:swsh9"]
        assert status["cards_added"] == 120
        assert called == {"ran": True}

    def test_catalog_sync_409_when_running(self, admin_client):
        client, repo, token = admin_client
        from merlins_collection.routers.admin import market

        market._CATALOG_SYNC_STATUS["state"] = "running"
        resp = client.post("/admin/market/catalog-sync", headers=_auth(token))
        assert resp.status_code == 409

    def test_catalog_sync_endpoint_reports_failure_without_getting_stuck(
        self, admin_client, monkeypatch
    ):
        """A crash in the background job must set `state="failed"` with an
        `error`, never leave the status stuck on `"running"` -- that would
        permanently 409 every future run."""
        client, repo, token = admin_client
        monkeypatch.setattr(
            "merlins_collection.routers.admin.market.sync_new_sets",
            lambda repo, tcgdex_client: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        resp = client.post("/admin/market/catalog-sync", headers=_auth(token))
        assert resp.status_code == 202

        status = client.get(
            "/admin/market/catalog-sync/status", headers=_auth(token)
        ).json()
        assert status["state"] == "failed"
        assert "boom" in status["error"]

        # recoverable: a fresh trigger is accepted, not blocked by a stuck "running"
        monkeypatch.setattr(
            "merlins_collection.routers.admin.market.sync_new_sets",
            lambda repo, tcgdex_client: {
                "sets_checked": 0, "new_sets": [], "cards_added": 0,
            },
        )
        resp = client.post("/admin/market/catalog-sync", headers=_auth(token))
        assert resp.status_code == 202


# ===========================================================================
# Purchase Confidence
# ===========================================================================

class TestAdminMarketConfidence:
    """GET /admin/market/card/{card_id}/confidence"""

    def test_confidence_levels(self, admin_client):
        client, repo, token = admin_client
        repo.batch_upsert_catalog_cards([_catalog_card(card_id="en:sv1-1")])

        today = date.today()
        tight_points = [
            PricePoint(
                card_id="en:sv1-1", date=today - timedelta(days=i),
                source="tcgplayer", kind="raw", finish="holofoil",
                market=Decimal("10.00") + Decimal("0.01") * i,
            )
            for i in range(10)
        ]
        repo.append_price_points(tight_points)

        resp = client.get(
            "/admin/market/card/en:sv1-1/confidence?days=90", headers=_auth(token)
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["points"] == 10
        assert data["level"] == "high"

    def test_confidence_low_with_few_points(self, admin_client):
        client, repo, token = admin_client
        repo.batch_upsert_catalog_cards([_catalog_card(card_id="en:sv1-2")])

        today = date.today()
        sparse_points = [
            PricePoint(
                card_id="en:sv1-2", date=today - timedelta(days=1),
                source="tcgplayer", kind="raw", finish="holofoil",
                market=Decimal("10.00"),
            ),
            PricePoint(
                card_id="en:sv1-2", date=today,
                source="tcgplayer", kind="raw", finish="holofoil",
                market=Decimal("40.00"),
            ),
        ]
        repo.append_price_points(sparse_points)

        resp = client.get(
            "/admin/market/card/en:sv1-2/confidence?days=90", headers=_auth(token)
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["points"] == 2
        assert data["level"] == "low"

    def test_confidence_nonexistent_card_returns_404(self, admin_client):
        client, _, token = admin_client
        resp = client.get(
            "/admin/market/card/en:no-card/confidence", headers=_auth(token)
        )
        assert resp.status_code == 404


# ===========================================================================
# RFC 0009 T7 — the graded refresh-skip bug
# ===========================================================================
#
# Open since Round 2 (claude-progress.txt, KNOWN BUGS): "Admin refresh-prices
# button silently skips graded slabs (raw-only scope); nightly sync does refresh
# them. Scope mismatch, not a wrong number."
#
# The mismatch was real but narrower than the note says: `_run_market_sync`
# already denormalized a slab's STORED graded value onto the item. What it never
# did was FETCH one, because until T6 there was no provider to fetch from — so a
# slab with no hand-typed value stayed unpriced no matter how often the button
# was pressed. T7 puts the graded fetch into the same run.

from decimal import Decimal as _D  # noqa: E402

from merlins_collection.models.inventory import (  # noqa: E402
    GradedInventoryItem,
    GradingCompany,
)
from merlins_collection.services.slab.pricing import GradedPrices  # noqa: E402


class _FakeGradedProvider:
    """One vendor id, one answer, no socket. Records what it was asked for."""

    def __init__(self, prices=None):
        self._prices = prices
        self.calls: list[str] = []

    def resolve(self, *, name, set_name, number, language=None):
        return None

    def prices(self, price_source_id):
        self.calls.append(price_source_id)
        return self._prices


def _graded_prices(**by_grade) -> GradedPrices:
    return GradedPrices(
        price_source_id="253266",
        prices={k: _D(v) for k, v in by_grade.items()},
        confidences={k: "high" for k in by_grade},
        currency="USD", currency_assumed=True, as_of=None,
    )


class TestMarketSyncIncludesGradedSlabs:
    def test_the_market_refresh_now_prices_a_graded_slab(self, admin_client,
                                                         monkeypatch):
        """RED 13. Before T7 this slab came out of the run with no value at all:
        the depth pass excludes graded cards by design, and the denormalizer can
        only copy a figure that somebody has already stored."""
        from merlins_collection.routers.admin import market

        client, repo, token = admin_client
        repo.batch_upsert_catalog_cards([_catalog_card(card_id="en:sv1-1")])
        slab = GradedInventoryItem(
            card_id="en:sv1-1", cost_basis=_D("300"), acquired_at=date(2026, 1, 1),
            company=GradingCompany.PSA, grade=_D("10"), cert_number="70000001",
            price_source_id="253266",
        )
        repo.put_inventory_item(slab)

        provider = _FakeGradedProvider(_graded_prices(psa10="2479.5"))
        monkeypatch.setattr(market, "build_pricing_provider", lambda: provider)
        monkeypatch.setattr(
            "merlins_collection.routers.admin.market.refresh_held_prices",
            lambda repo, tcgdex_client, today: {"cards_updated": 0},
        )

        resp = client.post("/admin/market/sync", headers=_auth(token))
        assert resp.status_code == 202

        status = client.get("/admin/market/sync/status", headers=_auth(token)).json()
        assert status["state"] == "completed", status.get("error")
        assert provider.calls == ["253266"]
        assert repo.get_inventory_item(
            slab.item_id).current_market_value == _D("2479.5")

    def test_the_raw_refresh_is_unchanged(self, admin_client, monkeypatch):
        """RED 14, the regression gate. Raw singles are the overwhelming majority
        of the table; adding a graded step must not disturb their path, their
        counts or the status shape the Market page polls."""
        from merlins_collection.routers.admin import market

        client, repo, token = admin_client
        called = {}
        monkeypatch.setattr(
            "merlins_collection.routers.admin.market.refresh_held_prices",
            lambda repo, tcgdex_client, today: (
                called.update(prices=True) or {"cards_updated": 3}
            ),
        )
        monkeypatch.setattr(
            "merlins_collection.routers.admin.market.refresh_inventory_market_values",
            lambda repo: called.update(items=True) or 5,
        )

        resp = client.post("/admin/market/sync", headers=_auth(token))
        assert resp.status_code == 202

        status = client.get("/admin/market/sync/status", headers=_auth(token)).json()
        assert status["state"] == "completed", status.get("error")
        assert status["priced_cards"] == 3
        assert status["updated_items"] == 5
        assert called == {"prices": True, "items": True}

    def test_a_missing_pricing_key_does_not_fail_the_market_sync(self, admin_client,
                                                                 monkeypatch):
        """The raw half of the run is the part this button has always been for.
        An unconfigured graded provider must cost the graded step and nothing
        else — `PokemonPriceTrackerClient.__init__` raises on an empty key."""
        from merlins_collection.config import settings

        # Forced empty, not assumed: `env_file=".env"` resolves against the CWD,
        # so a run from `backend/` would load the real key and bill this test.
        monkeypatch.setattr(settings, "pokemonpricetracker_api_key", "")
        monkeypatch.setattr(
            "merlins_collection.routers.admin.market.refresh_held_prices",
            lambda repo, tcgdex_client, today: {"cards_updated": 1},
        )

        client, _repo, token = admin_client
        client.post("/admin/market/sync", headers=_auth(token))

        status = client.get("/admin/market/sync/status", headers=_auth(token)).json()
        assert status["state"] == "completed", status.get("error")
        assert status["priced_cards"] == 1
