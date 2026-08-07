"""Tests for the admin purchases router (``/admin/purchases/...``).

Covers full buy session lifecycle: create, add items, confirm, cancel.
"""

from datetime import date


from merlins_collection.models.inventory import ItemStatus


# ---- fixtures ----

# ``admin_client`` now comes from ``conftest.py`` in this package; the identical
# copy that used to sit here was one of sixteen.


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


# ===========================================================================
# Task 2.1: transaction date, manual-entry flag, timeline events
# ===========================================================================

class TestPurchaseDateAndReview:
    def test_confirm_uses_purchase_date(self, admin_client):
        client, repo, token = admin_client
        create = client.post("/admin/purchases", json={"payment_method": "cash"}, headers=_auth(token))
        buy_id = create.json()["buy_id"]

        client.patch(f"/admin/purchases/{buy_id}", json={"purchase_date": "2026-07-04"}, headers=_auth(token))
        client.post(f"/admin/purchases/{buy_id}/items", json={
            "name": "Pikachu #25", "buy_price": "15.00",
        }, headers=_auth(token))

        resp = client.post(f"/admin/purchases/{buy_id}/confirm", headers=_auth(token))
        assert resp.status_code == 200

        all_items = repo.list_inventory()
        assert len(all_items) == 1
        assert all_items[0].acquired_at == date(2026, 7, 4)

        txns = repo.list_transactions(date(2026, 7, 1), date(2026, 7, 31))
        purchase_txns = [t for t in txns if t.item_id == all_items[0].item_id]
        assert len(purchase_txns) == 1
        assert purchase_txns[0].date == date(2026, 7, 4)

    def test_patch_rejects_bad_date(self, admin_client):
        client, repo, token = admin_client
        create = client.post("/admin/purchases", json={}, headers=_auth(token))
        buy_id = create.json()["buy_id"]

        resp = client.patch(f"/admin/purchases/{buy_id}", json={"purchase_date": "July 4th"}, headers=_auth(token))
        assert resp.status_code == 422

    def test_manual_entry_sets_needs_review(self, admin_client):
        client, repo, token = admin_client
        create = client.post("/admin/purchases", json={}, headers=_auth(token))
        buy_id = create.json()["buy_id"]

        client.post(f"/admin/purchases/{buy_id}/items", json={
            "name": "Mystery Card", "buy_price": "5.00", "manual_entry": True,
        }, headers=_auth(token))

        client.post(f"/admin/purchases/{buy_id}/confirm", headers=_auth(token))
        all_items = repo.list_inventory()
        assert len(all_items) == 1
        assert all_items[0].needs_review is True

    def test_manual_entry_via_missing_card_id_sets_needs_review(self, admin_client):
        client, repo, token = admin_client
        create = client.post("/admin/purchases", json={}, headers=_auth(token))
        buy_id = create.json()["buy_id"]

        client.post(f"/admin/purchases/{buy_id}/items", json={
            "name": "Mystery Card", "buy_price": "5.00",
        }, headers=_auth(token))

        client.post(f"/admin/purchases/{buy_id}/confirm", headers=_auth(token))
        all_items = repo.list_inventory()
        assert len(all_items) == 1
        assert all_items[0].needs_review is True

    def test_catalog_match_not_flagged(self, admin_client):
        client, repo, token = admin_client
        create = client.post("/admin/purchases", json={}, headers=_auth(token))
        buy_id = create.json()["buy_id"]

        client.post(f"/admin/purchases/{buy_id}/items", json={
            "name": "Charizard", "buy_price": "80.00", "card_id": "en:base1-4",
        }, headers=_auth(token))

        client.post(f"/admin/purchases/{buy_id}/confirm", headers=_auth(token))
        all_items = repo.list_inventory()
        assert len(all_items) == 1
        assert all_items[0].needs_review is False

    def test_item_rejects_unknown_location(self, admin_client):
        client, repo, token = admin_client
        create = client.post("/admin/purchases", json={}, headers=_auth(token))
        buy_id = create.json()["buy_id"]

        resp = client.post(f"/admin/purchases/{buy_id}/items", json={
            "name": "Pikachu", "buy_price": "5.00", "location": "narnia",
        }, headers=_auth(token))
        assert resp.status_code == 422

    def test_confirm_writes_purchase_timeline_event(self, admin_client):
        client, repo, token = admin_client
        create = client.post("/admin/purchases", json={"payment_method": "venmo"}, headers=_auth(token))
        buy_id = create.json()["buy_id"]

        client.post(f"/admin/purchases/{buy_id}/items", json={
            "name": "Pikachu #25", "buy_price": "15.00",
        }, headers=_auth(token))
        client.post(f"/admin/purchases/{buy_id}/confirm", headers=_auth(token))

        all_items = repo.list_inventory()
        assert len(all_items) == 1
        new_item_id = all_items[0].item_id

        resp = client.get(f"/admin/inventory/{new_item_id}/timeline", headers=_auth(token))
        assert resp.status_code == 200
        events = resp.json()["events"]
        purchase_events = [e for e in events if e.get("type") == "purchase"]
        assert len(purchase_events) == 1
        assert purchase_events[0]["amount"] == "15.00"
        assert purchase_events[0]["payment_method"] == "venmo"


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


# ===========================================================================
# A6: Condition Modifier support in buy flow
# ===========================================================================

class TestConditionModifierInPurchase:
    def test_add_item_with_condition_modifier(self, admin_client):
        """Items can be added with a condition_modifier (LP+, LP-)."""
        client, repo, token = admin_client
        create = client.post("/admin/purchases", json={}, headers=_auth(token))
        buy_id = create.json()["buy_id"]

        resp = client.post(f"/admin/purchases/{buy_id}/items", json={
            "name": "Pikachu #25",
            "buy_price": "15.00",
            "condition": "LP",
            "condition_modifier": "+",
            "finish": "holofoil",
        }, headers=_auth(token))
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert items[0]["condition"] == "LP"
        assert items[0]["condition_modifier"] == "+"

    def test_confirm_with_condition_modifier_creates_item(self, admin_client):
        """Confirmed buy creates inventory item preserving the modifier."""
        client, repo, token = admin_client
        create = client.post("/admin/purchases", json={}, headers=_auth(token))
        buy_id = create.json()["buy_id"]

        client.post(f"/admin/purchases/{buy_id}/items", json={
            "name": "Dragonair",
            "buy_price": "20.00",
            "condition": "LP",
            "condition_modifier": "-",
            "finish": "normal",
        }, headers=_auth(token))

        resp = client.post(f"/admin/purchases/{buy_id}/confirm", headers=_auth(token))
        assert resp.status_code == 200

        # Verify the inventory item has the modifier
        from merlins_collection.models.inventory import ConditionModifier
        all_items = repo.list_inventory()
        assert len(all_items) == 1
        item = all_items[0]
        assert item.condition_modifier is ConditionModifier.MINUS

    def test_confirm_without_modifier_defaults_none(self, admin_client):
        """Items without a modifier default to None (no modifier)."""
        client, repo, token = admin_client
        create = client.post("/admin/purchases", json={}, headers=_auth(token))
        buy_id = create.json()["buy_id"]

        client.post(f"/admin/purchases/{buy_id}/items", json={
            "name": "Bulbasaur",
            "buy_price": "5.00",
            "condition": "NM",
            "finish": "normal",
        }, headers=_auth(token))

        client.post(f"/admin/purchases/{buy_id}/confirm", headers=_auth(token))
        all_items = repo.list_inventory()
        assert len(all_items) == 1
        assert all_items[0].condition_modifier is None
