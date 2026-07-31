"""Tests for the admin market lookup router (``/admin/market/...``).

Covers catalog search, card detail, price trend, and watchlist CRUD.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from merlins_collection.models.catalog import CardImages, CatalogCard, FinishPrice
from merlins_collection.models.inventory import Language


# ---- helpers ----

def _catalog_card(card_id="en:sv1-1", name="Pikachu", set_id="sv1",
                  set_name="Scarlet & Violet", number="001", rarity="Common",
                  prices=None):
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
    )


# ---- fixtures ----

@pytest.fixture
def admin_client(cognito_config, jwks, dynamo_repo, mint_token):
    """TestClient + repo + admin token for admin market endpoint tests."""
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

    admin_token = mint_token(claims={"cognito:groups": ["admin"]})
    client = TestClient(app)
    yield client, dynamo_repo, admin_token
    app.dependency_overrides.clear()


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
