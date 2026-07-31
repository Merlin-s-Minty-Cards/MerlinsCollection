"""Tests for the admin purchases router (``/admin/purchases/...``).

Covers full buy session lifecycle: create, add items, confirm, cancel.
"""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from merlins_collection.models.inventory import ItemStatus


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
# Buy Session Lifecycle
# ===========================================================================

class TestBuySessionCreate:
    def test_create_session(self, admin_client):
        client, repo, token = admin_client
        resp = client.post("/admin/purchases", json={
            "payment_method": "cash",
            "counterparty": "Vendor Bob",
        }, headers=_auth(token))
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "draft"
        assert "buy_id" in data
        assert data["counterparty"] == "Vendor Bob"

    def test_get_session(self, admin_client):
        client, repo, token = admin_client
        create = client.post("/admin/purchases", json={}, headers=_auth(token))
        buy_id = create.json()["buy_id"]

        resp = client.get(f"/admin/purchases/{buy_id}", headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["buy_id"] == buy_id

    def test_get_nonexistent_returns_404(self, admin_client):
        client, _, token = admin_client
        resp = client.get("/admin/purchases/fake-id", headers=_auth(token))
        assert resp.status_code == 404


class TestBuySessionItems:
    def test_add_item(self, admin_client):
        client, repo, token = admin_client
        create = client.post("/admin/purchases", json={}, headers=_auth(token))
        buy_id = create.json()["buy_id"]

        resp = client.post(f"/admin/purchases/{buy_id}/items", json={
            "name": "Pikachu #25",
            "buy_price": "15.00",
            "condition": "NM",
            "finish": "holofoil",
        }, headers=_auth(token))
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 1

    def test_add_item_requires_name_and_price(self, admin_client):
        client, repo, token = admin_client
        create = client.post("/admin/purchases", json={}, headers=_auth(token))
        buy_id = create.json()["buy_id"]

        resp = client.post(f"/admin/purchases/{buy_id}/items", json={
            "condition": "NM",
        }, headers=_auth(token))
        assert resp.status_code == 422

    def test_remove_item_by_index(self, admin_client):
        client, repo, token = admin_client
        create = client.post("/admin/purchases", json={}, headers=_auth(token))
        buy_id = create.json()["buy_id"]

        client.post(f"/admin/purchases/{buy_id}/items", json={
            "name": "Pikachu", "buy_price": "10.00",
        }, headers=_auth(token))
        client.post(f"/admin/purchases/{buy_id}/items", json={
            "name": "Charizard", "buy_price": "50.00",
        }, headers=_auth(token))

        resp = client.delete(f"/admin/purchases/{buy_id}/items/0", headers=_auth(token))
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["name"] == "Charizard"

    def test_remove_invalid_index_returns_404(self, admin_client):
        client, repo, token = admin_client
        create = client.post("/admin/purchases", json={}, headers=_auth(token))
        buy_id = create.json()["buy_id"]

        resp = client.delete(f"/admin/purchases/{buy_id}/items/99", headers=_auth(token))
        assert resp.status_code == 404


class TestBuySessionConfirm:
    def test_confirm_creates_inventory_items(self, admin_client):
        client, repo, token = admin_client
        create = client.post("/admin/purchases", json={
            "payment_method": "cash",
        }, headers=_auth(token))
        buy_id = create.json()["buy_id"]

        client.post(f"/admin/purchases/{buy_id}/items", json={
            "name": "Pikachu #25",
            "buy_price": "15.00",
            "condition": "NM",
            "finish": "holofoil",
            "market_value": "40.00",
        }, headers=_auth(token))
        client.post(f"/admin/purchases/{buy_id}/items", json={
            "name": "Charizard #4",
            "buy_price": "80.00",
            "condition": "LP",
            "finish": "holofoil",
        }, headers=_auth(token))

        resp = client.post(f"/admin/purchases/{buy_id}/confirm", headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "confirmed"
        assert data["items_created"] == 2
        assert data["total_cost"] == "95.00"

        # Verify items exist in inventory
        all_items = repo.list_inventory()
        new_items = [i for i in all_items if i.status == ItemStatus.AVAILABLE]
        assert len(new_items) == 2

    def test_confirm_empty_session_returns_422(self, admin_client):
        client, repo, token = admin_client
        create = client.post("/admin/purchases", json={}, headers=_auth(token))
        buy_id = create.json()["buy_id"]

        resp = client.post(f"/admin/purchases/{buy_id}/confirm", headers=_auth(token))
        assert resp.status_code == 422

    def test_confirm_already_confirmed_returns_409(self, admin_client):
        client, repo, token = admin_client
        create = client.post("/admin/purchases", json={}, headers=_auth(token))
        buy_id = create.json()["buy_id"]
        client.post(f"/admin/purchases/{buy_id}/items", json={
            "name": "Pikachu", "buy_price": "15.00",
        }, headers=_auth(token))
        client.post(f"/admin/purchases/{buy_id}/confirm", headers=_auth(token))

        resp = client.post(f"/admin/purchases/{buy_id}/confirm", headers=_auth(token))
        assert resp.status_code == 409


class TestBuySessionCancel:
    def test_cancel_draft(self, admin_client):
        client, repo, token = admin_client
        create = client.post("/admin/purchases", json={}, headers=_auth(token))
        buy_id = create.json()["buy_id"]

        resp = client.post(f"/admin/purchases/{buy_id}/cancel", headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

    def test_cancel_confirmed_returns_409(self, admin_client):
        client, repo, token = admin_client
        create = client.post("/admin/purchases", json={}, headers=_auth(token))
        buy_id = create.json()["buy_id"]
        client.post(f"/admin/purchases/{buy_id}/items", json={
            "name": "Pikachu", "buy_price": "15.00",
        }, headers=_auth(token))
        client.post(f"/admin/purchases/{buy_id}/confirm", headers=_auth(token))

        resp = client.post(f"/admin/purchases/{buy_id}/cancel", headers=_auth(token))
        assert resp.status_code == 409
