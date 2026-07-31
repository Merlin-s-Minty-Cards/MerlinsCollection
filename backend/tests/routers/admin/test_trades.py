"""Tests for the admin trades router (``/admin/trades/...``).

Covers the full trade lifecycle: create, add outgoing/incoming legs,
cash component, balance calculation, customer view, confirm, cancel.
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

def _raw(item_id="item-1", *, card_id="sv1-1", status=ItemStatus.AVAILABLE,
         cost_basis="20.00", current_market_value="50.00"):
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
# Trade Session CRUD
# ===========================================================================

class TestTradeSessionCreate:
    def test_create_session(self, admin_client):
        client, repo, token = admin_client
        resp = client.post("/admin/trades", json={
            "counterparty": "Card Collector",
            "mode": "customer",
        }, headers=_auth(token))
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "draft"
        assert data["mode"] == "customer"
        assert "trade_id" in data

    def test_get_session(self, admin_client):
        client, repo, token = admin_client
        create = client.post("/admin/trades", json={}, headers=_auth(token))
        trade_id = create.json()["trade_id"]

        resp = client.get(f"/admin/trades/{trade_id}", headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["trade_id"] == trade_id

    def test_get_nonexistent_returns_404(self, admin_client):
        client, _, token = admin_client
        resp = client.get("/admin/trades/fake-id", headers=_auth(token))
        assert resp.status_code == 404


# ===========================================================================
# Outgoing Legs
# ===========================================================================

class TestTradeOutgoingLegs:
    def test_add_outgoing_leg(self, admin_client):
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="our-card-1"))

        create = client.post("/admin/trades", json={}, headers=_auth(token))
        trade_id = create.json()["trade_id"]

        resp = client.post(f"/admin/trades/{trade_id}/outgoing", json={
            "item_id": "our-card-1",
            "agreed_value": "45.00",
        }, headers=_auth(token))
        assert resp.status_code == 200
        legs = resp.json()["outgoing_legs"]
        assert len(legs) == 1
        assert legs[0]["item_id"] == "our-card-1"
        assert legs[0]["our_cost_basis"] == "20.00"  # From inventory item

    def test_add_unavailable_item_returns_409(self, admin_client):
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="sold-1", status=ItemStatus.SOLD))

        create = client.post("/admin/trades", json={}, headers=_auth(token))
        trade_id = create.json()["trade_id"]

        resp = client.post(f"/admin/trades/{trade_id}/outgoing", json={
            "item_id": "sold-1", "agreed_value": "45.00",
        }, headers=_auth(token))
        assert resp.status_code == 409

    def test_remove_outgoing_leg(self, admin_client):
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="our-card-1"))

        create = client.post("/admin/trades", json={}, headers=_auth(token))
        trade_id = create.json()["trade_id"]
        client.post(f"/admin/trades/{trade_id}/outgoing", json={
            "item_id": "our-card-1", "agreed_value": "45.00",
        }, headers=_auth(token))

        resp = client.delete(f"/admin/trades/{trade_id}/outgoing/our-card-1",
                             headers=_auth(token))
        assert resp.status_code == 200
        assert len(resp.json()["outgoing_legs"]) == 0


# ===========================================================================
# Incoming Legs
# ===========================================================================

class TestTradeIncomingLegs:
    def test_add_incoming_leg(self, admin_client):
        client, repo, token = admin_client
        create = client.post("/admin/trades", json={}, headers=_auth(token))
        trade_id = create.json()["trade_id"]

        resp = client.post(f"/admin/trades/{trade_id}/incoming", json={
            "name": "Their Charizard",
            "agreed_value": "60.00",
            "condition": "LP",
            "finish": "holofoil",
        }, headers=_auth(token))
        assert resp.status_code == 200
        legs = resp.json()["incoming_legs"]
        assert len(legs) == 1
        assert legs[0]["name"] == "Their Charizard"

    def test_remove_incoming_leg(self, admin_client):
        client, repo, token = admin_client
        create = client.post("/admin/trades", json={}, headers=_auth(token))
        trade_id = create.json()["trade_id"]
        client.post(f"/admin/trades/{trade_id}/incoming", json={
            "name": "Card A", "agreed_value": "20.00",
        }, headers=_auth(token))
        client.post(f"/admin/trades/{trade_id}/incoming", json={
            "name": "Card B", "agreed_value": "30.00",
        }, headers=_auth(token))

        resp = client.delete(f"/admin/trades/{trade_id}/incoming/0",
                             headers=_auth(token))
        assert resp.status_code == 200
        legs = resp.json()["incoming_legs"]
        assert len(legs) == 1
        assert legs[0]["name"] == "Card B"


# ===========================================================================
# Cash Component
# ===========================================================================

class TestTradeCash:
    def test_set_cash(self, admin_client):
        client, repo, token = admin_client
        create = client.post("/admin/trades", json={}, headers=_auth(token))
        trade_id = create.json()["trade_id"]

        resp = client.put(f"/admin/trades/{trade_id}/cash", json={
            "direction": "they_pay",
            "amount": "15.00",
        }, headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["cash"]["direction"] == "they_pay"
        assert resp.json()["cash"]["amount"] == "15.00"

    def test_remove_cash(self, admin_client):
        client, repo, token = admin_client
        create = client.post("/admin/trades", json={}, headers=_auth(token))
        trade_id = create.json()["trade_id"]
        client.put(f"/admin/trades/{trade_id}/cash", json={
            "direction": "they_pay", "amount": "15.00",
        }, headers=_auth(token))

        resp = client.delete(f"/admin/trades/{trade_id}/cash", headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["cash"] is None


# ===========================================================================
# Balance & Customer View
# ===========================================================================

class TestTradeBalance:
    def test_balance_calculation(self, admin_client):
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="our-1", cost_basis="20.00",
                                     current_market_value="50.00"))

        create = client.post("/admin/trades", json={}, headers=_auth(token))
        trade_id = create.json()["trade_id"]

        client.post(f"/admin/trades/{trade_id}/outgoing", json={
            "item_id": "our-1", "agreed_value": "50.00",
        }, headers=_auth(token))
        client.post(f"/admin/trades/{trade_id}/incoming", json={
            "name": "Their card", "agreed_value": "35.00",
        }, headers=_auth(token))
        client.put(f"/admin/trades/{trade_id}/cash", json={
            "direction": "they_pay", "amount": "15.00",
        }, headers=_auth(token))

        resp = client.get(f"/admin/trades/{trade_id}/balance", headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_out_value"] == "50.00"
        assert data["total_in_value"] == "35.00"
        assert data["cash_delta"] == "15.00"
        assert data["is_balanced"] is True
        # Margin: (35 + 15 - 20) / 20 = 150%
        assert data["margin_pct"] == "150.0"


class TestTradeCustomerView:
    def test_customer_view_strips_cost_data(self, admin_client):
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="our-1"))

        create = client.post("/admin/trades", json={}, headers=_auth(token))
        trade_id = create.json()["trade_id"]

        client.post(f"/admin/trades/{trade_id}/outgoing", json={
            "item_id": "our-1", "agreed_value": "50.00", "name": "Our Pikachu",
        }, headers=_auth(token))
        client.post(f"/admin/trades/{trade_id}/incoming", json={
            "name": "Their Charizard", "agreed_value": "50.00",
        }, headers=_auth(token))

        resp = client.get(f"/admin/trades/{trade_id}/customer-view",
                          headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()

        # Should NOT contain cost data
        for leg in data["outgoing_legs"]:
            assert "our_cost_basis" not in leg
            assert "item_id" not in leg
        assert data["balance_description"] == "Even trade"


# ===========================================================================
# Confirm
# ===========================================================================

class TestTradeConfirm:
    def test_confirm_full_trade(self, admin_client):
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="our-1", cost_basis="20.00",
                                     current_market_value="50.00"))
        repo.put_inventory_item(_raw(item_id="our-2", card_id="sv1-2",
                                     cost_basis="15.00",
                                     current_market_value="40.00"))

        create = client.post("/admin/trades", json={}, headers=_auth(token))
        trade_id = create.json()["trade_id"]

        # Add outgoing (our cards)
        client.post(f"/admin/trades/{trade_id}/outgoing", json={
            "item_id": "our-1", "agreed_value": "50.00",
        }, headers=_auth(token))
        client.post(f"/admin/trades/{trade_id}/outgoing", json={
            "item_id": "our-2", "agreed_value": "40.00",
        }, headers=_auth(token))

        # Add incoming (their cards)
        client.post(f"/admin/trades/{trade_id}/incoming", json={
            "name": "Their Mew", "agreed_value": "75.00", "condition": "NM",
        }, headers=_auth(token))

        # Cash to balance: they pay $15
        client.put(f"/admin/trades/{trade_id}/cash", json={
            "direction": "they_pay", "amount": "15.00",
        }, headers=_auth(token))

        # Confirm
        resp = client.post(f"/admin/trades/{trade_id}/confirm", headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "confirmed"
        assert data["items_sold"] == 2
        assert data["items_created"] == 1
        assert data["total_out_value"] == "90.00"
        assert data["total_in_value"] == "75.00"

        # Verify outgoing items are SOLD
        assert repo.get_inventory_item("our-1").status == ItemStatus.SOLD
        assert repo.get_inventory_item("our-2").status == ItemStatus.SOLD

        # Verify incoming item was created
        all_items = repo.list_inventory()
        new_items = [i for i in all_items if i.status == ItemStatus.AVAILABLE]
        assert len(new_items) == 1
        assert new_items[0].cost_basis == Decimal("75.00")

    def test_confirm_empty_trade_returns_422(self, admin_client):
        client, repo, token = admin_client
        create = client.post("/admin/trades", json={}, headers=_auth(token))
        trade_id = create.json()["trade_id"]

        resp = client.post(f"/admin/trades/{trade_id}/confirm", headers=_auth(token))
        assert resp.status_code == 422

    def test_confirm_already_confirmed_returns_409(self, admin_client):
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="our-1"))

        create = client.post("/admin/trades", json={}, headers=_auth(token))
        trade_id = create.json()["trade_id"]
        client.post(f"/admin/trades/{trade_id}/outgoing", json={
            "item_id": "our-1", "agreed_value": "50.00",
        }, headers=_auth(token))
        client.post(f"/admin/trades/{trade_id}/confirm", headers=_auth(token))

        resp = client.post(f"/admin/trades/{trade_id}/confirm", headers=_auth(token))
        assert resp.status_code == 409


# ===========================================================================
# Cancel
# ===========================================================================

class TestTradeCancel:
    def test_cancel_draft(self, admin_client):
        client, repo, token = admin_client
        create = client.post("/admin/trades", json={}, headers=_auth(token))
        trade_id = create.json()["trade_id"]

        resp = client.post(f"/admin/trades/{trade_id}/cancel", headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

    def test_cancel_confirmed_returns_409(self, admin_client):
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="our-1"))

        create = client.post("/admin/trades", json={}, headers=_auth(token))
        trade_id = create.json()["trade_id"]
        client.post(f"/admin/trades/{trade_id}/outgoing", json={
            "item_id": "our-1", "agreed_value": "50.00",
        }, headers=_auth(token))
        client.post(f"/admin/trades/{trade_id}/confirm", headers=_auth(token))

        resp = client.post(f"/admin/trades/{trade_id}/cancel", headers=_auth(token))
        assert resp.status_code == 409
