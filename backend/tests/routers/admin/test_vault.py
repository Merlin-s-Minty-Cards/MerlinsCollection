"""Tests for the admin vault router (``/admin/vault/...``).

Covers vault listing with P&L, move-to-vault, and release-from-vault.
"""

from datetime import date
from decimal import Decimal


from merlins_collection.models.inventory import (
    Condition,
    ConsignmentTerms,
    ItemStatus,
    RawInventoryItem,
)


# ---- helpers ----

def _raw(item_id="item-1", *, card_id="sv1-1", status=ItemStatus.ON_HOLD,
         cost_basis="10.00", current_market_value="50.00", sticker_price=None):
    kwargs = dict(
        item_id=item_id,
        card_id=card_id,
        finish="holofoil",
        condition=Condition.NM,
        location="vault-binder",
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

# ``admin_client`` now comes from ``conftest.py`` in this package; the identical
# copy that used to sit here was one of sixteen.


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ===========================================================================
# Vault Listing
# ===========================================================================

class TestVaultGet:
    def test_empty_vault(self, admin_client):
        client, repo, token = admin_client
        resp = client.get("/admin/vault", headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["summary"]["total_items"] == 0

    def test_vault_returns_on_hold_items(self, admin_client):
        client, repo, token = admin_client
        repo.put_inventory_item(_raw("hold-1", cost_basis="20.00", current_market_value="60.00"))
        repo.put_inventory_item(_raw("hold-2", cost_basis="10.00", current_market_value="25.00"))
        # Available item should NOT appear
        repo.put_inventory_item(_raw("avail-1", status=ItemStatus.AVAILABLE))

        resp = client.get("/admin/vault", headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"]["total_items"] == 2
        ids = {i["item_id"] for i in data["items"]}
        assert "hold-1" in ids
        assert "hold-2" in ids
        assert "avail-1" not in ids

    def test_vault_pnl_calculation(self, admin_client):
        client, repo, token = admin_client
        # Cost $20, market $60 → +$40, +200%
        repo.put_inventory_item(_raw("hold-1", cost_basis="20.00", current_market_value="60.00"))

        resp = client.get("/admin/vault", headers=_auth(token))
        data = resp.json()
        item = data["items"][0]
        assert item["dollar_net"] == "40.00"
        assert item["percent_net"] == "200.0"

    def test_vault_negative_pnl(self, admin_client):
        client, repo, token = admin_client
        # Cost $50, market $30 → -$20, -40%
        repo.put_inventory_item(_raw("hold-1", cost_basis="50.00", current_market_value="30.00"))

        resp = client.get("/admin/vault", headers=_auth(token))
        data = resp.json()
        item = data["items"][0]
        assert item["dollar_net"] == "-20.00"
        assert item["percent_net"] == "-40.0"

    def test_vault_summary_totals(self, admin_client):
        client, repo, token = admin_client
        repo.put_inventory_item(_raw("hold-1", cost_basis="20.00", current_market_value="60.00"))
        repo.put_inventory_item(_raw("hold-2", cost_basis="30.00", current_market_value="45.00"))

        resp = client.get("/admin/vault", headers=_auth(token))
        data = resp.json()
        summary = data["summary"]
        assert summary["total_cost_basis"] == "50.00"
        assert summary["total_market_value"] == "105.00"
        assert summary["total_dollar_gain"] == "55.00"
        assert summary["total_percent_gain"] == "110.0"

    def test_vault_includes_sticker_price(self, admin_client):
        client, repo, token = admin_client
        repo.put_inventory_item(_raw("hold-1", sticker_price="35.00"))

        resp = client.get("/admin/vault", headers=_auth(token))
        data = resp.json()
        assert data["items"][0]["sticker_price"] == "35.00"

    def test_vault_reports_consigned_flag(self, admin_client):
        client, repo, token = admin_client
        owned = _raw("hold-owned")
        consigned = _raw("hold-consigned")
        consigned = consigned.model_copy(
            update={
                "consignment": ConsignmentTerms(
                    consignor_id="consignor-1", split_percent=Decimal("0.20")
                )
            }
        )
        repo.put_inventory_item(owned)
        repo.put_inventory_item(consigned)

        resp = client.get("/admin/vault", headers=_auth(token))
        data = resp.json()
        by_id = {i["item_id"]: i for i in data["items"]}
        assert by_id["hold-owned"]["consigned"] is False
        assert by_id["hold-consigned"]["consigned"] is True


# ===========================================================================
# Move to Vault
# ===========================================================================

class TestMoveToVault:
    def test_hold_available_item(self, admin_client):
        client, repo, token = admin_client
        repo.put_inventory_item(_raw("card-1", status=ItemStatus.AVAILABLE))

        resp = client.post("/admin/vault/card-1/hold", headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["status"] == "on_hold"

        # Verify in DB
        item = repo.get_inventory_item("card-1")
        assert item.status == ItemStatus.ON_HOLD

    def test_hold_already_held_is_idempotent(self, admin_client):
        client, repo, token = admin_client
        repo.put_inventory_item(_raw("card-1", status=ItemStatus.ON_HOLD))

        resp = client.post("/admin/vault/card-1/hold", headers=_auth(token))
        assert resp.status_code == 200
        assert "Already in vault" in resp.json()["message"]

    def test_hold_sold_item_returns_409(self, admin_client):
        client, repo, token = admin_client
        repo.put_inventory_item(_raw("card-1", status=ItemStatus.SOLD))

        resp = client.post("/admin/vault/card-1/hold", headers=_auth(token))
        assert resp.status_code == 409

    def test_hold_nonexistent_returns_404(self, admin_client):
        client, _, token = admin_client
        resp = client.post("/admin/vault/fake-id/hold", headers=_auth(token))
        assert resp.status_code == 404


# ===========================================================================
# Release from Vault
# ===========================================================================

class TestReleaseFromVault:
    def test_release_held_item(self, admin_client):
        client, repo, token = admin_client
        repo.put_inventory_item(_raw("card-1", status=ItemStatus.ON_HOLD))

        resp = client.post("/admin/vault/card-1/release", headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["status"] == "available"

        # Verify in DB
        item = repo.get_inventory_item("card-1")
        assert item.status == ItemStatus.AVAILABLE

    def test_release_available_item_returns_409(self, admin_client):
        client, repo, token = admin_client
        repo.put_inventory_item(_raw("card-1", status=ItemStatus.AVAILABLE))

        resp = client.post("/admin/vault/card-1/release", headers=_auth(token))
        assert resp.status_code == 409

    def test_release_nonexistent_returns_404(self, admin_client):
        client, _, token = admin_client
        resp = client.post("/admin/vault/fake-id/release", headers=_auth(token))
        assert resp.status_code == 404
