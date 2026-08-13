"""Tests for the admin sales router (``/admin/sales/...``).

Covers full sell session lifecycle: create, add items, confirm, cancel.
"""

from datetime import date
from decimal import Decimal


from merlins_collection.models.inventory import (
    Condition,
    ItemStatus,
    RawInventoryItem,
)


# ---- helpers ----

def _raw(item_id="item-1", *, card_id="sv1-1", status=ItemStatus.AVAILABLE, cost_basis="10.00",
         current_market_value="50.00"):
    return RawInventoryItem(
        item_id=item_id,
        card_id=card_id,
        finish="holofoil",
        condition=Condition.NM,
        location="glass",
        status=status,
        cost_basis=Decimal(cost_basis),
        current_market_value=Decimal(current_market_value),
        acquired_at=date(2025, 1, 1),
    )


# ---- fixtures ----

# ``admin_client`` now comes from ``conftest.py`` in this package; the identical
# copy that used to sit here was one of sixteen.


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ===========================================================================
# Sell Session Lifecycle
# ===========================================================================

class TestSellSessionCreate:
    def test_create_session(self, admin_client):
        client, repo, token = admin_client
        resp = client.post("/admin/sales", json={
            "payment_method": "cash",
            "counterparty": "John Doe",
        }, headers=_auth(token))
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "draft"
        assert "sell_id" in data
        assert data["counterparty"] == "John Doe"

    def test_get_session(self, admin_client):
        client, repo, token = admin_client
        create = client.post("/admin/sales", json={}, headers=_auth(token))
        sell_id = create.json()["sell_id"]

        resp = client.get(f"/admin/sales/{sell_id}", headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["sell_id"] == sell_id

    def test_get_nonexistent_returns_404(self, admin_client):
        client, _, token = admin_client
        resp = client.get("/admin/sales/fake-id", headers=_auth(token))
        assert resp.status_code == 404


class TestSellSessionItems:
    def test_add_item(self, admin_client):
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="card-1"))

        create = client.post("/admin/sales", json={}, headers=_auth(token))
        sell_id = create.json()["sell_id"]

        resp = client.post(f"/admin/sales/{sell_id}/items", json={
            "item_id": "card-1",
            "agreed_price": "45.00",
        }, headers=_auth(token))
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 1

    def test_add_item_with_numeric_prices(self, admin_client):
        # What the Sell page ACTUALLY sends. `addItem` in sell/page.tsx builds
        # agreed_price with parseFloat, so the body carries JSON numbers, not
        # the strings every other test in this class uses. Those numbers reach
        # the repo as Python floats, which boto3 refuses -- this 500'd on the
        # live site ("TypeError: Float types are not supported").
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="card-1"))

        create = client.post("/admin/sales", json={}, headers=_auth(token))
        sell_id = create.json()["sell_id"]

        resp = client.post(f"/admin/sales/{sell_id}/items", json={
            "item_id": "card-1",
            "agreed_price": 45.5,
            "original_price": 60.0,
            "discount_pct": 24.17,
        }, headers=_auth(token))
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 1

    def test_add_unavailable_item_returns_409(self, admin_client):
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="sold-1", status=ItemStatus.SOLD))

        create = client.post("/admin/sales", json={}, headers=_auth(token))
        sell_id = create.json()["sell_id"]

        resp = client.post(f"/admin/sales/{sell_id}/items", json={
            "item_id": "sold-1",
            "agreed_price": "45.00",
        }, headers=_auth(token))
        assert resp.status_code == 409

    def test_add_duplicate_item_returns_409(self, admin_client):
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="card-1"))

        create = client.post("/admin/sales", json={}, headers=_auth(token))
        sell_id = create.json()["sell_id"]

        client.post(f"/admin/sales/{sell_id}/items", json={
            "item_id": "card-1", "agreed_price": "45.00",
        }, headers=_auth(token))

        resp = client.post(f"/admin/sales/{sell_id}/items", json={
            "item_id": "card-1", "agreed_price": "45.00",
        }, headers=_auth(token))
        assert resp.status_code == 409

    def test_remove_item(self, admin_client):
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="card-1"))

        create = client.post("/admin/sales", json={}, headers=_auth(token))
        sell_id = create.json()["sell_id"]

        client.post(f"/admin/sales/{sell_id}/items", json={
            "item_id": "card-1", "agreed_price": "45.00",
        }, headers=_auth(token))

        resp = client.delete(f"/admin/sales/{sell_id}/items/card-1", headers=_auth(token))
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 0


class TestSellSessionConfirm:
    def test_confirm_marks_items_sold(self, admin_client):
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="card-1"))
        repo.put_inventory_item(_raw(item_id="card-2", card_id="sv1-2"))

        create = client.post("/admin/sales", json={"payment_method": "cash"}, headers=_auth(token))
        sell_id = create.json()["sell_id"]

        client.post(f"/admin/sales/{sell_id}/items", json={
            "item_id": "card-1", "agreed_price": "45.00",
        }, headers=_auth(token))
        client.post(f"/admin/sales/{sell_id}/items", json={
            "item_id": "card-2", "agreed_price": "30.00",
        }, headers=_auth(token))

        resp = client.post(f"/admin/sales/{sell_id}/confirm", headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "confirmed"
        assert data["items_sold"] == 2
        assert data["total_revenue"] == "75.00"

        # Verify items are SOLD in DB
        assert repo.get_inventory_item("card-1").status == ItemStatus.SOLD
        assert repo.get_inventory_item("card-2").status == ItemStatus.SOLD

    def test_confirm_empty_session_returns_422(self, admin_client):
        client, repo, token = admin_client
        create = client.post("/admin/sales", json={}, headers=_auth(token))
        sell_id = create.json()["sell_id"]

        resp = client.post(f"/admin/sales/{sell_id}/confirm", headers=_auth(token))
        assert resp.status_code == 422

    def test_confirm_already_confirmed_returns_409(self, admin_client):
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="card-1"))

        create = client.post("/admin/sales", json={}, headers=_auth(token))
        sell_id = create.json()["sell_id"]
        client.post(f"/admin/sales/{sell_id}/items", json={
            "item_id": "card-1", "agreed_price": "45.00",
        }, headers=_auth(token))
        client.post(f"/admin/sales/{sell_id}/confirm", headers=_auth(token))

        # Try to confirm again
        resp = client.post(f"/admin/sales/{sell_id}/confirm", headers=_auth(token))
        assert resp.status_code == 409


# ===========================================================================
# Task 2.1: sale timeline events
# ===========================================================================

class TestSaleTimelineEvent:
    def test_confirm_writes_sale_timeline_event(self, admin_client):
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="card-1"))
        repo.put_inventory_item(_raw(item_id="card-2", card_id="sv1-2"))

        create = client.post("/admin/sales", json={"payment_method": "cash"}, headers=_auth(token))
        sell_id = create.json()["sell_id"]

        client.post(f"/admin/sales/{sell_id}/items", json={
            "item_id": "card-1", "agreed_price": "45.00",
        }, headers=_auth(token))
        client.post(f"/admin/sales/{sell_id}/items", json={
            "item_id": "card-2", "agreed_price": "30.00",
        }, headers=_auth(token))

        resp = client.post(f"/admin/sales/{sell_id}/confirm", headers=_auth(token))
        assert resp.status_code == 200

        events1 = client.get("/admin/inventory/card-1/timeline", headers=_auth(token)).json()["events"]
        sale_events1 = [e for e in events1 if e.get("type") == "sale"]
        assert len(sale_events1) == 1
        assert sale_events1[0]["amount"] == "45.00"

        events2 = client.get("/admin/inventory/card-2/timeline", headers=_auth(token)).json()["events"]
        sale_events2 = [e for e in events2 if e.get("type") == "sale"]
        assert len(sale_events2) == 1
        assert sale_events2[0]["amount"] == "30.00"


class TestSellSessionCancel:
    def test_cancel_draft(self, admin_client):
        client, repo, token = admin_client
        create = client.post("/admin/sales", json={}, headers=_auth(token))
        sell_id = create.json()["sell_id"]

        resp = client.post(f"/admin/sales/{sell_id}/cancel", headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

    def test_cancel_confirmed_returns_409(self, admin_client):
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="card-1"))

        create = client.post("/admin/sales", json={}, headers=_auth(token))
        sell_id = create.json()["sell_id"]
        client.post(f"/admin/sales/{sell_id}/items", json={
            "item_id": "card-1", "agreed_price": "45.00",
        }, headers=_auth(token))
        client.post(f"/admin/sales/{sell_id}/confirm", headers=_auth(token))

        resp = client.post(f"/admin/sales/{sell_id}/cancel", headers=_auth(token))
        assert resp.status_code == 409


# ===========================================================================
# RFC 0010 T10 — one real transaction renders as one line
# ===========================================================================

class TestSaleBatchId:
    def test_confirm_stamps_every_row_with_the_sell_id(self, admin_client):
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="card-1"))
        repo.put_inventory_item(_raw(item_id="card-2", card_id="sv1-2"))

        sell_id = client.post(
            "/admin/sales", json={"payment_method": "cash"}, headers=_auth(token)
        ).json()["sell_id"]
        for item_id, price in (("card-1", "45.00"), ("card-2", "30.00")):
            client.post(f"/admin/sales/{sell_id}/items", json={
                "item_id": item_id, "agreed_price": price,
            }, headers=_auth(token))
        client.post(f"/admin/sales/{sell_id}/confirm", headers=_auth(token))

        txns = repo.list_transactions(date(2000, 1, 1), date(2100, 1, 1))
        assert len(txns) == 2
        assert {t.batch_id for t in txns} == {sell_id}


class TestSellItemPriceEdit:
    """``PATCH /sales/{id}/items/{item_id}`` — a discount must reach the ledger.

    Before this route existed there was no way to send one. The Sell page's
    per-item price field and its bulk-discount button both mutated local state
    only, and ``handleConfirm`` PATCHed session metadata and POSTed
    ``/confirm`` with no body — so the sale recorded whatever ``addItem``
    posted when the card was added: sticker, else market.

    The money consequence is the reason this is a test and not a nicety:
    discounting a card at a show sold it to the customer at the lower price and
    booked it at the higher one, so revenue and profit were BOTH overstated on
    every discounted sale. See docs/plans/rfc-0010/follow-ups.md (T1).
    """

    def _session_with_item(self, client, repo, token, *, price="50.00"):
        repo.put_inventory_item(_raw(item_id="card-1"))
        sell_id = client.post(
            "/admin/sales", json={"payment_method": "cash"}, headers=_auth(token)
        ).json()["sell_id"]
        client.post(f"/admin/sales/{sell_id}/items", json={
            "item_id": "card-1", "agreed_price": price,
        }, headers=_auth(token))
        return sell_id

    def test_edited_price_is_what_the_sale_records(self, admin_client):
        """The headline bug: the edit has to survive all the way to the ledger."""
        client, repo, token = admin_client
        sell_id = self._session_with_item(client, repo, token, price="50.00")

        patch = client.patch(
            f"/admin/sales/{sell_id}/items/card-1",
            json={"agreed_price": 40.00},
            headers=_auth(token),
        )
        assert patch.status_code == 200

        confirm = client.post(f"/admin/sales/{sell_id}/confirm", headers=_auth(token))
        assert confirm.status_code == 200
        # Compared as a Decimal, not a string: how many trailing zeros the total
        # carries is a formatting choice this route does not make a promise
        # about, and `formatMoney` renders either as "$40.00".
        assert Decimal(confirm.json()["total_revenue"]) == Decimal("40.00")

        txns = repo.list_transactions(date(2000, 1, 1), date(2100, 1, 1))
        assert [t.amount for t in txns] == [Decimal("40.00")]

    def test_patch_returns_the_updated_session(self, admin_client):
        client, repo, token = admin_client
        sell_id = self._session_with_item(client, repo, token)

        resp = client.patch(
            f"/admin/sales/{sell_id}/items/card-1",
            json={"agreed_price": "42.50"},
            headers=_auth(token),
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert Decimal(str(items[0]["agreed_price"])) == Decimal("42.50")

    def test_a_free_card_is_allowed(self, admin_client):
        """``0`` is a real price at a show — a throw-in. Never test falsiness."""
        client, repo, token = admin_client
        sell_id = self._session_with_item(client, repo, token)

        resp = client.patch(
            f"/admin/sales/{sell_id}/items/card-1",
            json={"agreed_price": 0},
            headers=_auth(token),
        )
        assert resp.status_code == 200
        assert Decimal(str(resp.json()["items"][0]["agreed_price"])) == Decimal("0")

    def test_a_negative_price_is_rejected(self, admin_client):
        client, repo, token = admin_client
        sell_id = self._session_with_item(client, repo, token)

        resp = client.patch(
            f"/admin/sales/{sell_id}/items/card-1",
            json={"agreed_price": -5},
            headers=_auth(token),
        )
        assert resp.status_code == 422

    def test_a_non_finite_price_is_rejected(self, admin_client):
        """``Decimal("NaN")`` PARSES. A bare try/except is not enough."""
        client, repo, token = admin_client
        sell_id = self._session_with_item(client, repo, token)

        resp = client.patch(
            f"/admin/sales/{sell_id}/items/card-1",
            json={"agreed_price": "NaN"},
            headers=_auth(token),
        )
        assert resp.status_code == 422

    def test_a_missing_price_is_rejected(self, admin_client):
        client, repo, token = admin_client
        sell_id = self._session_with_item(client, repo, token)

        resp = client.patch(
            f"/admin/sales/{sell_id}/items/card-1",
            json={}, headers=_auth(token),
        )
        assert resp.status_code == 422

    def test_unknown_item_returns_404(self, admin_client):
        client, repo, token = admin_client
        sell_id = self._session_with_item(client, repo, token)

        resp = client.patch(
            f"/admin/sales/{sell_id}/items/not-in-session",
            json={"agreed_price": "10.00"},
            headers=_auth(token),
        )
        assert resp.status_code == 404

    def test_unknown_session_returns_404(self, admin_client):
        client, repo, token = admin_client
        resp = client.patch(
            "/admin/sales/no-such-session/items/card-1",
            json={"agreed_price": "10.00"},
            headers=_auth(token),
        )
        assert resp.status_code == 404

    def test_a_confirmed_session_cannot_be_repriced(self, admin_client):
        """The ledger's correction path is a void, not an edit to a closed sale."""
        client, repo, token = admin_client
        sell_id = self._session_with_item(client, repo, token)
        client.post(f"/admin/sales/{sell_id}/confirm", headers=_auth(token))

        resp = client.patch(
            f"/admin/sales/{sell_id}/items/card-1",
            json={"agreed_price": "10.00"},
            headers=_auth(token),
        )
        assert resp.status_code == 409
