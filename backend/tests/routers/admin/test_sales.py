"""Tests for the admin sales router (``/admin/sales/...``).

Covers full sell session lifecycle: create, add items, confirm, cancel.
"""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

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
