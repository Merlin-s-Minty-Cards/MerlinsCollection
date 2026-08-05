"""Tests for transaction history & lineage endpoints (A3).

GET /admin/inventory/{item_id}/timeline — item event history
GET /admin/inventory/{item_id}/lineage — full trade chain
"""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from merlins_collection.models.business import ItemCategory, Transaction, TransactionType
from merlins_collection.models.inventory import (
    Condition,
    ItemStatus,
    RawInventoryItem,
)


# ---- helpers ----

def _raw(item_id="item-1", *, card_id="sv1-1", status=ItemStatus.AVAILABLE,
         cost_basis="20.00", lineage_id=None, predecessor_item_id=None):
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
        lineage_id=lineage_id,
        predecessor_item_id=predecessor_item_id,
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
# Timeline
# ===========================================================================

class TestItemTimeline:
    def test_timeline_empty(self, admin_client):
        """Item with no timeline events returns empty list."""
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="item-1"))

        resp = client.get("/admin/inventory/item-1/timeline", headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["item_id"] == "item-1"
        assert data["events"] == []

    def test_timeline_with_events(self, admin_client):
        """Item with timeline events returns them in chronological order."""
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="item-1"))

        # Write timeline events directly
        repo.put_timeline_event("item-1", {
            "item_id": "item-1",
            "txn_id": "txn-1",
            "type": "purchase",
            "date": "2025-03-15",
            "amount": "15.00",
            "payment_method": "cash",
            "trade_id": None,
            "show_id": "SHOW1",
        })
        repo.put_timeline_event("item-1", {
            "item_id": "item-1",
            "txn_id": "txn-2",
            "type": "sale",
            "date": "2025-04-01",
            "amount": "25.00",
            "payment_method": "cash",
            "trade_id": None,
            "show_id": "SHOW2",
        })

        resp = client.get("/admin/inventory/item-1/timeline", headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["events"]) == 2
        assert data["events"][0]["type"] == "purchase"
        assert data["events"][0]["date"] == "2025-03-15"
        assert data["events"][1]["type"] == "sale"

    def test_timeline_nonexistent_item_returns_404(self, admin_client):
        client, repo, token = admin_client
        resp = client.get("/admin/inventory/fake-id/timeline", headers=_auth(token))
        assert resp.status_code == 404


# ===========================================================================
# Lineage
# ===========================================================================

class TestItemLineage:
    def test_lineage_standalone_item(self, admin_client):
        """Item with no lineage returns single-item chain."""
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="item-1", lineage_id="item-1"))

        resp = client.get("/admin/inventory/item-1/lineage", headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["lineage_id"] == "item-1"
        assert len(data["chain"]) == 1
        assert data["chain"][0]["item_id"] == "item-1"

    def test_lineage_trade_chain(self, admin_client):
        """Items linked by predecessor_item_id form a chain."""
        client, repo, token = admin_client
        # Create a chain: A -> B -> C
        repo.put_inventory_item(_raw(
            item_id="item-a", cost_basis="15.00",
            lineage_id="item-a", predecessor_item_id=None,
            status=ItemStatus.SOLD,
        ))
        repo.put_inventory_item(_raw(
            item_id="item-b", card_id="sv1-2", cost_basis="20.00",
            lineage_id="item-a", predecessor_item_id="item-a",
            status=ItemStatus.SOLD,
        ))
        repo.put_inventory_item(_raw(
            item_id="item-c", card_id="sv1-3", cost_basis="25.00",
            lineage_id="item-a", predecessor_item_id="item-b",
        ))

        resp = client.get("/admin/inventory/item-c/lineage", headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["lineage_id"] == "item-a"
        assert len(data["chain"]) == 3
        # Chain should be in order: A, B, C
        assert data["chain"][0]["item_id"] == "item-a"
        assert data["chain"][1]["item_id"] == "item-b"
        assert data["chain"][2]["item_id"] == "item-c"

    def test_lineage_nonexistent_item_returns_404(self, admin_client):
        client, repo, token = admin_client
        resp = client.get("/admin/inventory/fake-id/lineage", headers=_auth(token))
        assert resp.status_code == 404

    def test_lineage_no_lineage_id(self, admin_client):
        """Item without lineage_id returns itself as standalone."""
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="item-1"))

        resp = client.get("/admin/inventory/item-1/lineage", headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["chain"]) == 1


# ===========================================================================
# Trade confirm writes timeline events
# ===========================================================================

class TestTradeConfirmTimeline:
    def test_confirm_trade_writes_timeline_events(self, admin_client):
        """Confirming a trade writes timeline events for outgoing and incoming items."""
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="our-1", cost_basis="20.00"))

        # Create and populate trade
        create = client.post("/admin/trades", json={}, headers=_auth(token))
        trade_id = create.json()["trade_id"]

        client.post(f"/admin/trades/{trade_id}/outgoing", json={
            "item_id": "our-1", "agreed_value": "50.00",
        }, headers=_auth(token))
        client.post(f"/admin/trades/{trade_id}/incoming", json={
            "name": "Their card", "agreed_value": "50.00", "condition": "NM",
        }, headers=_auth(token))

        # Confirm
        resp = client.post(f"/admin/trades/{trade_id}/confirm", headers=_auth(token))
        assert resp.status_code == 200

        # Check timeline for outgoing item
        timeline = repo.get_timeline_events("our-1")
        assert len(timeline) == 1
        assert timeline[0]["type"] == "trade_out"
        # Task 3.0: card-only trades in transfer mode record outgoing sales at
        # basis_pool (cost_basis), not agreed_value — the invariant is:
        # Σ outgoing sale amounts == Σ incoming bases == basis_pool.
        assert timeline[0]["amount"] == "20.00"
