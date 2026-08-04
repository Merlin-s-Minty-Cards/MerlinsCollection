"""Tests for show analytics endpoints (A4).

POST /admin/shows/{show_id}/analytics/generate
GET /admin/shows/{show_id}/analytics
GET /admin/analytics/by-date
GET /admin/shows
GET /admin/analytics/dates
GET /admin/analytics/daily
GET /admin/transactions
"""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from merlins_collection.models.business import (
    ItemCategory,
    Show,
    Transaction,
    TransactionType,
)
from merlins_collection.models.catalog import PricePoint


# ---- fixtures ----

@pytest.fixture
def admin_client(cognito_config, jwks, dynamo_repo, mint_token):
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
# Generate Analytics
# ===========================================================================

class TestGenerateAnalytics:
    def test_generate_analytics(self, admin_client):
        """Generate snapshot from show transactions."""
        client, repo, token = admin_client

        # Create a show
        show = Show(
            show_id="show-1", name="Portland Card Show",
            date=date(2025, 4, 15),
            cash_at_start=Decimal("500.00"),
            inventory_value_at_start=Decimal("15000.00"),
        )
        repo.put_show(show)

        # Create transactions for this show
        repo.put_transaction(Transaction(
            type=TransactionType.SALE, item_id="item-1",
            category=ItemCategory.RAW, date=date(2025, 4, 15),
            amount=Decimal("50.00"), payment_method="cash", show_id="show-1",
        ))
        repo.put_transaction(Transaction(
            type=TransactionType.SALE, item_id="item-2",
            category=ItemCategory.RAW, date=date(2025, 4, 15),
            amount=Decimal("30.00"), payment_method="venmo", show_id="show-1",
        ))
        repo.put_transaction(Transaction(
            type=TransactionType.PURCHASE, item_id="item-3",
            category=ItemCategory.RAW, date=date(2025, 4, 15),
            amount=Decimal("20.00"), payment_method="cash", show_id="show-1",
        ))

        resp = client.post("/admin/shows/show-1/analytics/generate",
                           headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["show_id"] == "show-1"
        assert data["total_sold"] == "80.00"
        assert data["total_bought"] == "20.00"
        assert data["net_sales"] == "60.00"
        assert data["items_sold_count"] == 2
        assert data["items_bought_count"] == 1
        assert data["cash_at_start"] == "500.00"
        assert data["inventory_value_at_start"] == "15000.00"

    def test_generate_nonexistent_show_returns_404(self, admin_client):
        client, repo, token = admin_client
        resp = client.post("/admin/shows/fake/analytics/generate",
                           headers=_auth(token))
        assert resp.status_code == 404


# ===========================================================================
# Get Analytics
# ===========================================================================

class TestGetAnalytics:
    def test_get_analytics(self, admin_client):
        """Retrieve stored analytics snapshot."""
        client, repo, token = admin_client

        show = Show(show_id="show-1", name="Test Show", date=date(2025, 4, 15))
        repo.put_show(show)
        repo.put_transaction(Transaction(
            type=TransactionType.SALE, item_id="item-1",
            category=ItemCategory.RAW, date=date(2025, 4, 15),
            amount=Decimal("100.00"), payment_method="cash", show_id="show-1",
        ))

        # Generate first
        client.post("/admin/shows/show-1/analytics/generate", headers=_auth(token))

        # Then retrieve
        resp = client.get("/admin/shows/show-1/analytics", headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["total_sold"] == "100.00"

    def test_get_nonexistent_returns_404(self, admin_client):
        client, repo, token = admin_client
        resp = client.get("/admin/shows/fake/analytics", headers=_auth(token))
        assert resp.status_code == 404


# ===========================================================================
# By-date query
# ===========================================================================

class TestAnalyticsByDate:
    def test_by_date_range(self, admin_client):
        """List analytics in a date range."""
        client, repo, token = admin_client

        # Create two shows
        show1 = Show(show_id="show-1", name="Show 1", date=date(2025, 3, 1))
        show2 = Show(show_id="show-2", name="Show 2", date=date(2025, 4, 15))
        show3 = Show(show_id="show-3", name="Show 3", date=date(2025, 6, 1))
        repo.put_show(show1)
        repo.put_show(show2)
        repo.put_show(show3)

        # Generate analytics for show1 and show2
        repo.put_transaction(Transaction(
            type=TransactionType.SALE, item_id="i1",
            category=ItemCategory.RAW, date=date(2025, 3, 1),
            amount=Decimal("50.00"), payment_method="cash", show_id="show-1",
        ))
        repo.put_transaction(Transaction(
            type=TransactionType.SALE, item_id="i2",
            category=ItemCategory.RAW, date=date(2025, 4, 15),
            amount=Decimal("75.00"), payment_method="cash", show_id="show-2",
        ))
        client.post("/admin/shows/show-1/analytics/generate", headers=_auth(token))
        client.post("/admin/shows/show-2/analytics/generate", headers=_auth(token))

        # Query date range covering both
        resp = client.get(
            "/admin/analytics/by-date?start=2025-03-01&end=2025-05-01",
            headers=_auth(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

    def test_by_date_empty(self, admin_client):
        """No shows in range returns empty list."""
        client, repo, token = admin_client
        resp = client.get(
            "/admin/analytics/by-date?start=2020-01-01&end=2020-12-31",
            headers=_auth(token),
        )
        assert resp.status_code == 200
        assert resp.json() == []


# ===========================================================================
# Repository bug fix: get_price_history date range with finish unspecified
# ===========================================================================
# Lives here because test_analytics.py is this task's owned test file; the
# endpoint it silently breaks (GET /admin/market/card/{id}/trend) omits
# `finish` by default.

class TestPriceHistoryDateRange:
    def test_get_price_history_date_range_without_finish(self, dynamo_repo):
        """Raw price keys are ``PRICE#RAW#<finish>#<date>``.

        With ``finish=None`` the date bound must still be applied to the *date*
        component; previously it was compared against ``PRICE#RAW#<date>``,
        which sorts before every real key and returned zero points.
        """
        repo = dynamo_repo
        repo.append_price_points([
            PricePoint(card_id="c1", date=date(2026, 7, 1), source="tcgplayer",
                       kind="raw", finish="normal", market=Decimal("1.00")),
            PricePoint(card_id="c1", date=date(2026, 7, 15), source="tcgplayer",
                       kind="raw", finish="holofoil", market=Decimal("2.00")),
            PricePoint(card_id="c1", date=date(2026, 6, 1), source="tcgplayer",
                       kind="raw", finish="normal", market=Decimal("3.00")),
            PricePoint(card_id="c1", date=date(2026, 8, 1), source="tcgplayer",
                       kind="raw", finish="holofoil", market=Decimal("4.00")),
        ])

        got = repo.get_price_history(
            "c1", start=date(2026, 7, 1), end=date(2026, 7, 31))

        assert {(p.finish, p.date) for p in got} == {
            ("normal", date(2026, 7, 1)),
            ("holofoil", date(2026, 7, 15)),
        }

    def test_get_price_history_date_range_with_finish_still_works(self, dynamo_repo):
        repo = dynamo_repo
        repo.append_price_points([
            PricePoint(card_id="c2", date=date(2026, 7, 5), source="tcgplayer",
                       kind="raw", finish="normal", market=Decimal("1.00")),
            PricePoint(card_id="c2", date=date(2026, 8, 5), source="tcgplayer",
                       kind="raw", finish="normal", market=Decimal("2.00")),
            PricePoint(card_id="c2", date=date(2026, 7, 6), source="tcgplayer",
                       kind="raw", finish="holofoil", market=Decimal("9.00")),
        ])
        got = repo.get_price_history(
            "c2", finish="normal", start=date(2026, 7, 1), end=date(2026, 7, 31))
        assert [(p.finish, p.date) for p in got] == [("normal", date(2026, 7, 5))]
