"""Tests for Stream E (sticker_price) and Stream F (payment method fees).

Stream E: sticker_price field on inventory items — CRUD, serialization.
Stream F: Venmo/Zelle payment methods, fee calculation on sell.
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
         cost_basis="10.00", current_market_value="50.00", sticker_price=None):
    kwargs = dict(
        item_id=item_id,
        card_id=card_id,
        finish="holofoil",
        condition=Condition.NM,
        location="glass",
        status=status,
        cost_basis=Decimal(cost_basis),
        current_market_value=Decimal(current_market_value),
        acquired_at=date(2025, 1, 1),
        display_name=f"Test Card {item_id}",
    )
    if sticker_price is not None:
        kwargs["sticker_price"] = Decimal(sticker_price)
    return RawInventoryItem(**kwargs)


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
# Stream E: Sticker Price
# ===========================================================================

class TestStickerPrice:
    """sticker_price field on inventory items."""

    def test_create_item_with_sticker_price(self, admin_client):
        client, repo, token = admin_client
        resp = client.post("/admin/inventory", json={
            "kind": "raw",
            "card_id": "sv1-1",
            "finish": "holofoil",
            "condition": "NM",
            "cost_basis": "10.00",
            "sticker_price": "45.00",
            "current_market_value": "50.00",
            "acquired_at": "2025-01-01",
        }, headers=_auth(token))
        assert resp.status_code == 201
        data = resp.json()
        assert data["sticker_price"] == "45.00" or data["sticker_price"] == 45.0

    def test_sticker_price_defaults_none(self, admin_client):
        client, repo, token = admin_client
        resp = client.post("/admin/inventory", json={
            "kind": "raw",
            "card_id": "sv1-1",
            "finish": "holofoil",
            "condition": "NM",
            "cost_basis": "10.00",
            "current_market_value": "50.00",
            "acquired_at": "2025-01-01",
        }, headers=_auth(token))
        assert resp.status_code == 201
        assert resp.json()["sticker_price"] is None

    def test_update_sticker_price(self, admin_client):
        client, repo, token = admin_client
        repo.put_inventory_item(_raw("card-1"))

        resp = client.put("/admin/inventory/card-1", json={
            "sticker_price": "39.99",
        }, headers=_auth(token))
        assert resp.status_code == 200
        # Verify the update persisted
        item = repo.get_inventory_item("card-1")
        assert item.sticker_price == Decimal("39.99")

    def test_sticker_price_in_admin_search(self, admin_client):
        client, repo, token = admin_client
        repo.put_inventory_item(_raw("card-1", sticker_price="35.00"))

        resp = client.get("/admin/inventory/search", headers=_auth(token))
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["sticker_price"] == "35.00" or items[0]["sticker_price"] == 35.0

    def test_sticker_price_in_get_item(self, admin_client):
        client, repo, token = admin_client
        repo.put_inventory_item(_raw("card-1", sticker_price="42.00"))

        resp = client.get("/admin/inventory/card-1", headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["sticker_price"] == "42.00" or data["sticker_price"] == 42.0

    def test_clear_sticker_price(self, admin_client):
        client, repo, token = admin_client
        repo.put_inventory_item(_raw("card-1", sticker_price="35.00"))

        resp = client.put("/admin/inventory/card-1", json={
            "sticker_price": None,
        }, headers=_auth(token))
        assert resp.status_code == 200
        item = repo.get_inventory_item("card-1")
        assert item.sticker_price is None


# ===========================================================================
# Stream F: Payment Method Fee Calculation
# ===========================================================================

class TestFeeCalculation:
    """Venmo fee: (amount × 1.9%) + $0.10."""

    def test_venmo_fee_basic(self, admin_client):
        """$100 sale via Venmo: ($100 × 0.019) + $0.10 = $2.00."""
        client, _, token = admin_client
        resp = client.get("/admin/sales/calculate-fee", params={
            "amount": "100.00",
            "payment_method": "venmo",
        }, headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["fee"] == "2.00"
        assert data["net"] == "98.00"

    def test_venmo_fee_small_amount(self, admin_client):
        """$5 sale via Venmo: ($5 × 0.019) + $0.10 = $0.10 + $0.10 = $0.20."""
        client, _, token = admin_client
        resp = client.get("/admin/sales/calculate-fee", params={
            "amount": "5.00",
            "payment_method": "venmo",
        }, headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["fee"] == "0.20"
        assert data["net"] == "4.80"

    def test_venmo_fee_large_amount(self, admin_client):
        """$250 sale via Venmo: ($250 × 0.019) + $0.10 = $4.75 + $0.10 = $4.85."""
        client, _, token = admin_client
        resp = client.get("/admin/sales/calculate-fee", params={
            "amount": "250.00",
            "payment_method": "venmo",
        }, headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["fee"] == "4.85"
        assert data["net"] == "245.15"

    def test_cash_no_fee(self, admin_client):
        client, _, token = admin_client
        resp = client.get("/admin/sales/calculate-fee", params={
            "amount": "100.00",
            "payment_method": "cash",
        }, headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["fee"] == "0"

    def test_zelle_no_fee(self, admin_client):
        client, _, token = admin_client
        resp = client.get("/admin/sales/calculate-fee", params={
            "amount": "100.00",
            "payment_method": "zelle",
        }, headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["fee"] == "0"

    def test_card_no_fee(self, admin_client):
        client, _, token = admin_client
        resp = client.get("/admin/sales/calculate-fee", params={
            "amount": "100.00",
            "payment_method": "card",
        }, headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["fee"] == "0"

    def test_confirm_sale_with_venmo_calculates_fee(self, admin_client):
        """Confirming a sale with venmo payment should auto-calculate fee."""
        client, repo, token = admin_client
        repo.put_inventory_item(_raw("card-1"))

        # Create session with venmo
        create = client.post("/admin/sales", json={
            "payment_method": "venmo",
        }, headers=_auth(token))
        sell_id = create.json()["sell_id"]

        # Add item
        client.post(f"/admin/sales/{sell_id}/items", json={
            "item_id": "card-1",
            "agreed_price": "100.00",
        }, headers=_auth(token))

        # Confirm
        resp = client.post(f"/admin/sales/{sell_id}/confirm", headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["fee"] == "2.00"
        assert data["net_revenue"] == "98.00"

    def test_confirm_sale_with_cash_no_fee(self, admin_client):
        client, repo, token = admin_client
        repo.put_inventory_item(_raw("card-1"))

        create = client.post("/admin/sales", json={
            "payment_method": "cash",
        }, headers=_auth(token))
        sell_id = create.json()["sell_id"]

        client.post(f"/admin/sales/{sell_id}/items", json={
            "item_id": "card-1",
            "agreed_price": "50.00",
        }, headers=_auth(token))

        resp = client.post(f"/admin/sales/{sell_id}/confirm", headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["fee"] == "0"
        assert data["net_revenue"] == "50.00"
