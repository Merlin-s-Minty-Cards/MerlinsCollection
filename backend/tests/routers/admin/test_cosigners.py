"""Tests for the admin cosigners router (``/admin/cosigners/...``).

A2: Cosigner Management — CRUD + asset linking + analytics.
"""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from merlins_collection.models.business import Consignor
from merlins_collection.models.inventory import (
    Condition,
    ConsignmentTerms,
    ItemStatus,
    RawInventoryItem,
)


# ---- helpers ----

def _raw(item_id="item-1", *, card_id="sv1-1", status=ItemStatus.AVAILABLE,
         cost_basis="20.00", consignment=None):
    return RawInventoryItem(
        item_id=item_id,
        card_id=card_id,
        finish="holofoil",
        condition=Condition.NM,
        location="glass",
        status=status,
        cost_basis=Decimal(cost_basis),
        current_market_value=Decimal("50.00"),
        acquired_at=date(2025, 1, 1),
        consignment=consignment,
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
# CRUD
# ===========================================================================

class TestCosignerCreate:
    def test_create_cosigner(self, admin_client):
        client, repo, token = admin_client
        resp = client.post("/admin/cosigners", json={
            "name": "Alice",
            "email": "alice@example.com",
            "phone": "555-0101",
            "payout_percent": "60",
            "notes": "Local collector",
        }, headers=_auth(token))
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Alice"
        assert data["email"] == "alice@example.com"
        assert data["payout_percent"] == "60"
        assert data["active"] is True
        assert "consignor_id" in data

    def test_create_minimal(self, admin_client):
        client, repo, token = admin_client
        resp = client.post("/admin/cosigners", json={
            "name": "Bob",
        }, headers=_auth(token))
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Bob"
        assert data["payout_percent"] == "50"  # default


class TestCosignerList:
    def test_list_empty(self, admin_client):
        client, repo, token = admin_client
        resp = client.get("/admin/cosigners", headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_returns_all(self, admin_client):
        client, repo, token = admin_client
        client.post("/admin/cosigners", json={"name": "Alice"}, headers=_auth(token))
        client.post("/admin/cosigners", json={"name": "Bob"}, headers=_auth(token))

        resp = client.get("/admin/cosigners", headers=_auth(token))
        assert resp.status_code == 200
        assert len(resp.json()) == 2


class TestCosignerGet:
    def test_get_cosigner(self, admin_client):
        client, repo, token = admin_client
        create = client.post("/admin/cosigners", json={
            "name": "Alice", "email": "alice@test.com",
        }, headers=_auth(token))
        cid = create.json()["consignor_id"]

        resp = client.get(f"/admin/cosigners/{cid}", headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["name"] == "Alice"

    def test_get_nonexistent_returns_404(self, admin_client):
        client, repo, token = admin_client
        resp = client.get("/admin/cosigners/fake-id", headers=_auth(token))
        assert resp.status_code == 404


class TestCosignerUpdate:
    def test_patch_cosigner(self, admin_client):
        client, repo, token = admin_client
        create = client.post("/admin/cosigners", json={
            "name": "Alice", "payout_percent": "50",
        }, headers=_auth(token))
        cid = create.json()["consignor_id"]

        resp = client.patch(f"/admin/cosigners/{cid}", json={
            "payout_percent": "65",
            "phone": "555-9999",
        }, headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["payout_percent"] == "65"
        assert resp.json()["phone"] == "555-9999"

    def test_patch_nonexistent_returns_404(self, admin_client):
        client, repo, token = admin_client
        resp = client.patch("/admin/cosigners/fake-id", json={
            "name": "New name",
        }, headers=_auth(token))
        assert resp.status_code == 404


class TestCosignerDelete:
    def test_delete_deactivates(self, admin_client):
        """DELETE marks cosigner as inactive rather than hard deleting."""
        client, repo, token = admin_client
        create = client.post("/admin/cosigners", json={"name": "Alice"}, headers=_auth(token))
        cid = create.json()["consignor_id"]

        resp = client.delete(f"/admin/cosigners/{cid}", headers=_auth(token))
        assert resp.status_code == 200

        # Check it's now inactive
        get_resp = client.get(f"/admin/cosigners/{cid}", headers=_auth(token))
        assert get_resp.json()["active"] is False


# ===========================================================================
# Assets and linking
# ===========================================================================

class TestCosignerAssets:
    def test_get_assets(self, admin_client):
        """GET /admin/cosigners/{id}/assets returns linked inventory."""
        client, repo, token = admin_client
        create = client.post("/admin/cosigners", json={"name": "Alice"}, headers=_auth(token))
        cid = create.json()["consignor_id"]

        # Create items linked to this consignor
        terms = ConsignmentTerms(
            consignor_id=cid, split_percent=Decimal("0.50"), minimum_price=Decimal("10.00"),
        )
        repo.put_inventory_item(_raw(item_id="item-1", consignment=terms))
        repo.put_inventory_item(_raw(item_id="item-2", card_id="sv1-2", consignment=terms))
        repo.put_inventory_item(_raw(item_id="item-3", card_id="sv1-3"))  # not consigned

        resp = client.get(f"/admin/cosigners/{cid}/assets", headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 2
        assert data["total"] == 2

    def test_link_items(self, admin_client):
        """POST /admin/cosigners/{id}/link batch-links items to cosigner."""
        client, repo, token = admin_client
        create = client.post("/admin/cosigners", json={
            "name": "Alice", "payout_percent": "60",
        }, headers=_auth(token))
        cid = create.json()["consignor_id"]

        # Create items without consignment
        repo.put_inventory_item(_raw(item_id="item-a"))
        repo.put_inventory_item(_raw(item_id="item-b", card_id="sv1-2"))

        resp = client.post(f"/admin/cosigners/{cid}/link", json={
            "item_ids": ["item-a", "item-b"],
            "split_percent": "0.60",
            "minimum_price": "25.00",
        }, headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["linked"] == 2

        # Verify items now have consignment
        item_a = repo.get_inventory_item("item-a")
        assert item_a.consignment is not None
        assert item_a.consignment.consignor_id == cid
        assert item_a.consignment.split_percent == Decimal("0.60")

    def test_link_default_split_is_our_cut(self, admin_client):
        """Without an explicit split_percent, default must be OUR cut (1 - consignor's payout fraction)."""
        client, repo, token = admin_client
        create = client.post("/admin/cosigners", json={
            "name": "Alice", "payout_percent": "70",
        }, headers=_auth(token))
        cid = create.json()["consignor_id"]

        repo.put_inventory_item(_raw(item_id="item-a"))

        resp = client.post(f"/admin/cosigners/{cid}/link", json={
            "item_ids": ["item-a"],
        }, headers=_auth(token))
        assert resp.status_code == 200

        item_a = repo.get_inventory_item("item-a")
        assert item_a.consignment.split_percent == Decimal("0.30")


# ===========================================================================
# Analytics
# ===========================================================================

class TestCosignerAnalytics:
    def test_analytics(self, admin_client):
        """GET /admin/cosigners/{id}/analytics returns stats."""
        client, repo, token = admin_client
        create = client.post("/admin/cosigners", json={"name": "Alice"}, headers=_auth(token))
        cid = create.json()["consignor_id"]

        terms = ConsignmentTerms(
            consignor_id=cid, split_percent=Decimal("0.50"), minimum_price=Decimal("10.00"),
        )
        repo.put_inventory_item(_raw(item_id="item-1", cost_basis="20.00", consignment=terms))
        repo.put_inventory_item(_raw(
            item_id="item-2", card_id="sv1-2", cost_basis="30.00",
            consignment=terms, status=ItemStatus.SOLD,
        ))

        resp = client.get(f"/admin/cosigners/{cid}/analytics", headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_items"] == 2
        assert data["items_sold"] == 1
        # Both items use the _raw() default current_market_value of 50.00,
        # which takes precedence over cost_basis (20 + 30) per the fix.
        assert data["total_value"] == "100.00"  # 50 + 50 (market value)

    def test_analytics_total_value_prefers_market(self, admin_client):
        """total_value uses current_market_value when present, else falls back to cost_basis."""
        client, repo, token = admin_client
        create = client.post("/admin/cosigners", json={"name": "Alice"}, headers=_auth(token))
        cid = create.json()["consignor_id"]

        terms = ConsignmentTerms(
            consignor_id=cid, split_percent=Decimal("0.50"), minimum_price=Decimal("10.00"),
        )
        item_with_market = RawInventoryItem(
            item_id="item-1",
            card_id="sv1-1",
            finish="holofoil",
            condition=Condition.NM,
            location="glass",
            status=ItemStatus.AVAILABLE,
            cost_basis=Decimal("10.00"),
            current_market_value=Decimal("25.00"),
            acquired_at=date(2025, 1, 1),
            consignment=terms,
        )
        item_without_market = RawInventoryItem(
            item_id="item-2",
            card_id="sv1-2",
            finish="holofoil",
            condition=Condition.NM,
            location="glass",
            status=ItemStatus.AVAILABLE,
            cost_basis=Decimal("15.00"),
            current_market_value=None,
            acquired_at=date(2025, 1, 1),
            consignment=terms,
        )
        repo.put_inventory_item(item_with_market)
        repo.put_inventory_item(item_without_market)

        resp = client.get(f"/admin/cosigners/{cid}/analytics", headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        # 25.00 (market value preferred) + 15.00 (cost_basis fallback)
        assert data["total_value"] == "40.00"
