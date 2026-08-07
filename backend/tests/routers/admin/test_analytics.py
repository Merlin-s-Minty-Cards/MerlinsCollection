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


from merlins_collection.models.business import (
    ItemCategory,
    Show,
    Transaction,
    TransactionType,
)
from merlins_collection.models.catalog import PricePoint
from merlins_collection.models.inventory import InventoryItemAdapter


# ---- fixtures ----

# ``admin_client`` now comes from ``conftest.py`` in this package; the identical
# copy that used to sit here was one of sixteen.


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
# Helpers for the Round-2 (Task 2.4) tests
# ===========================================================================

def _raw_item(item_id: str, *, acquired: date, cost: str,
              market: str | None = None, status: str = "available"):
    """Build a minimal raw inventory item for seeding."""
    data = {
        "kind": "raw",
        "item_id": item_id,
        "status": status,
        "finish": "holofoil",
        "condition": "NM",
        "cost_basis": cost,
        "acquired_at": acquired.isoformat(),
    }
    if market is not None:
        data["current_market_value"] = market
    return InventoryItemAdapter.validate_python(data)


def _txn(txn_type, item_id, day, amount, **kw):
    return Transaction(
        type=txn_type, item_id=item_id, category=ItemCategory.RAW,
        date=day, amount=Decimal(amount), payment_method="cash", **kw,
    )


# ===========================================================================
# GET /admin/shows  (fixes the analytics page 404-ing show list)
# ===========================================================================

class TestListShowsEndpoint:
    def test_list_shows_endpoint(self, admin_client):
        client, repo, token = admin_client
        repo.put_show(Show(show_id="s-old", name="Old Show", date=date(2026, 5, 1)))
        repo.put_show(Show(show_id="s-new", name="New Show", date=date(2026, 7, 1)))

        resp = client.get("/admin/shows", headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert [s["show_id"] for s in data] == ["s-new", "s-old"]
        assert data[0]["name"] == "New Show"
        assert data[0]["date"] == "2026-07-01"


# ===========================================================================
# GET /admin/analytics/dates
# ===========================================================================

class TestAnalyticsDates:
    def test_dates_endpoint_returns_distinct_dates_desc(self, admin_client):
        client, repo, token = admin_client
        repo.put_transaction(_txn(TransactionType.SALE, "i1", date(2026, 7, 1), "10"))
        repo.put_transaction(_txn(TransactionType.SALE, "i2", date(2026, 7, 1), "20"))
        repo.put_transaction(_txn(TransactionType.PURCHASE, "i3", date(2026, 7, 5), "5"))

        resp = client.get(
            "/admin/analytics/dates?start=2026-06-01&end=2026-07-31",
            headers=_auth(token),
        )
        assert resp.status_code == 200
        assert resp.json() == {"dates": ["2026-07-05", "2026-07-01"]}


# ===========================================================================
# GET /admin/analytics/daily
# ===========================================================================

class TestDailyMetrics:
    def test_daily_metrics_exclude_trade_cash_legs(self, admin_client):
        """Trade out a $25 card for a $20 card + $5 cash.

        The cash leg is stored with item_id == trade_id, so it must NOT be
        added to total_sold: sold=25, bought=20 -- not sold=30.
        """
        client, repo, token = admin_client
        day = date(2026, 7, 5)
        repo.put_transaction(_txn(TransactionType.SALE, "card-out", day, "25",
                                  trade_id="tr-1"))
        repo.put_transaction(_txn(TransactionType.PURCHASE, "card-in", day, "20",
                                  trade_id="tr-1"))
        # cash component written by trades.py confirm: item_id == trade_id
        repo.put_transaction(_txn(TransactionType.SALE, "tr-1", day, "5",
                                  trade_id="tr-1"))

        resp = client.get("/admin/analytics/daily?date=2026-07-05",
                          headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["date"] == "2026-07-05"
        assert data["total_sold"] == "25"
        assert data["total_bought"] == "20"
        assert data["net_sales"] == "5"
        assert data["items_sold_count"] == 1
        assert data["items_bought_count"] == 1
        assert data["trades_count"] == 1

    def test_inventory_value_at_start_excludes_same_day_acquisitions(
        self, admin_client
    ):
        client, repo, token = admin_client
        d = date(2026, 7, 15)

        # In: acquired before D, still available, market value wins over cost
        repo.put_inventory_item(_raw_item(
            "in-available", acquired=date(2026, 7, 1), cost="80", market="100"))
        # Out: acquired ON D (same-day flip)
        repo.put_inventory_item(_raw_item(
            "out-sameday", acquired=d, cost="500", market="500"))
        # In: sold, but sold AFTER D -> it was on hand at the start of D.
        # No current_market_value -> falls back to cost_basis (40).
        repo.put_inventory_item(_raw_item(
            "in-sold-later", acquired=date(2026, 6, 1), cost="40", status="sold"))
        repo.put_transaction(_txn(TransactionType.SALE, "in-sold-later",
                                  date(2026, 7, 20), "60"))
        # Out: sold BEFORE D
        repo.put_inventory_item(_raw_item(
            "out-sold-before", acquired=date(2026, 6, 1), cost="900",
            status="sold"))
        repo.put_transaction(_txn(TransactionType.SALE, "out-sold-before",
                                  date(2026, 7, 1), "900"))

        resp = client.get("/admin/analytics/daily?date=2026-07-15",
                          headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["inventory_value_at_start"] == "140"

    def test_sell_through_rate(self, admin_client):
        """2-item starting set, 1 of them sold that day -> 0.5."""
        client, repo, token = admin_client
        d = date(2026, 7, 10)
        repo.put_inventory_item(_raw_item(
            "x", acquired=date(2026, 7, 1), cost="10", market="10", status="sold"))
        repo.put_inventory_item(_raw_item(
            "y", acquired=date(2026, 7, 1), cost="10", market="10", status="sold"))
        repo.put_transaction(_txn(TransactionType.SALE, "x", d, "15"))
        repo.put_transaction(_txn(TransactionType.SALE, "y", date(2026, 7, 20), "15"))

        resp = client.get("/admin/analytics/daily?date=2026-07-10",
                          headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["sell_through_rate"] == "0.5"

    def test_sell_through_rate_null_when_no_starting_inventory(self, admin_client):
        client, repo, token = admin_client
        resp = client.get("/admin/analytics/daily?date=2026-07-10",
                          headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["sell_through_rate"] is None


# ===========================================================================
# GET /admin/transactions  (archive)
# ===========================================================================

class TestTransactionsArchive:
    def test_transactions_archive_filters_by_date_and_type(self, admin_client):
        client, repo, token = admin_client
        repo.put_transaction(_txn(TransactionType.SALE, "a", date(2026, 7, 1), "10"))
        repo.put_transaction(_txn(TransactionType.SALE, "b", date(2026, 7, 20), "30"))
        repo.put_transaction(_txn(TransactionType.PURCHASE, "c", date(2026, 7, 2), "5"))
        repo.put_transaction(_txn(TransactionType.SALE, "d", date(2026, 5, 1), "99"))

        resp = client.get(
            "/admin/transactions?start=2026-07-01&end=2026-07-31&type=sale",
            headers=_auth(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        # newest first
        assert [t["item_id"] for t in data["items"]] == ["b", "a"]

        # no type filter -> all three in range
        resp2 = client.get(
            "/admin/transactions?start=2026-07-01&end=2026-07-31",
            headers=_auth(token),
        )
        assert resp2.json()["total"] == 3


# ===========================================================================
# Per-show snapshot now carries sell_through_rate (metric rule 5)
# ===========================================================================

class TestShowSellThrough:
    def test_generate_show_analytics_sets_sell_through(self, admin_client):
        client, repo, token = admin_client
        show_date = date(2026, 7, 10)
        # Show record deliberately lacks inventory_value_at_start.
        repo.put_show(Show(show_id="show-st", name="ST", date=show_date))

        repo.put_inventory_item(_raw_item(
            "p", acquired=date(2026, 7, 1), cost="10", market="60", status="sold"))
        repo.put_inventory_item(_raw_item(
            "q", acquired=date(2026, 7, 1), cost="10", market="40"))

        repo.put_transaction(_txn(TransactionType.SALE, "p", show_date, "75",
                                  show_id="show-st"))

        resp = client.post("/admin/shows/show-st/analytics/generate",
                           headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["sell_through_rate"] == "0.5"
        assert data["inventory_value_at_start"] == "100"

    def test_show_analytics_excludes_trade_cash_legs(self, admin_client):
        client, repo, token = admin_client
        show_date = date(2026, 7, 11)
        repo.put_show(Show(show_id="show-tc", name="TC", date=show_date))
        repo.put_transaction(_txn(TransactionType.SALE, "card-out", show_date, "25",
                                  show_id="show-tc", trade_id="tr-9"))
        repo.put_transaction(_txn(TransactionType.PURCHASE, "card-in", show_date, "20",
                                  show_id="show-tc", trade_id="tr-9"))
        repo.put_transaction(_txn(TransactionType.SALE, "tr-9", show_date, "5",
                                  show_id="show-tc", trade_id="tr-9"))

        resp = client.post("/admin/shows/show-tc/analytics/generate",
                           headers=_auth(token))
        data = resp.json()
        assert data["total_sold"] == "25"
        assert data["total_bought"] == "20"
        assert data["trades_count"] == 1


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
