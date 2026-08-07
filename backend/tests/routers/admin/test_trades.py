"""Tests for the admin trades router (``/admin/trades/...``).

Covers the full trade lifecycle: create, add outgoing/incoming legs,
cash component, balance calculation, customer view, confirm, cancel.
"""

from datetime import date
from decimal import Decimal


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

# ``admin_client`` now comes from ``conftest.py`` in this package; the identical
# copy that used to sit here was one of sixteen.


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

        # 3.0: cash requires manual basis mode
        client.patch(f"/admin/trades/{trade_id}", json={
            "basis_mode": "manual",
            "manual_basis": "20.00",
        }, headers=_auth(token))

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
        # 3.0: manual basis mode — operator set total basis to 20.00
        assert new_items[0].cost_basis == Decimal("20.00")

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


# ===========================================================================
# A1: Advanced Trade Engine — Multi-asset cash_components + margin_split
# ===========================================================================

class TestTradeCashComponents:
    """PUT /admin/trades/{id}/cash with cash_components (multi-asset)."""

    def test_set_cash_components_multiple_methods(self, admin_client):
        """cash_components supports multiple payment methods."""
        client, repo, token = admin_client
        create = client.post("/admin/trades", json={}, headers=_auth(token))
        trade_id = create.json()["trade_id"]

        resp = client.put(f"/admin/trades/{trade_id}/cash", json={
            "cash_components": [
                {"direction": "they_pay", "amount": "50.00", "payment_method": "venmo"},
                {"direction": "we_pay", "amount": "10.00", "payment_method": "cash"},
            ]
        }, headers=_auth(token))
        assert resp.status_code == 200
        session = resp.json()
        assert "cash_components" in session
        assert len(session["cash_components"]) == 2
        assert session["cash_components"][0]["payment_method"] == "venmo"
        assert session["cash_components"][1]["payment_method"] == "cash"

    def test_set_cash_components_single(self, admin_client):
        """Single cash component in the list."""
        client, repo, token = admin_client
        create = client.post("/admin/trades", json={}, headers=_auth(token))
        trade_id = create.json()["trade_id"]

        resp = client.put(f"/admin/trades/{trade_id}/cash", json={
            "cash_components": [
                {"direction": "they_pay", "amount": "25.00", "payment_method": "zelle"},
            ]
        }, headers=_auth(token))
        assert resp.status_code == 200
        session = resp.json()
        assert len(session["cash_components"]) == 1

    def test_legacy_cash_still_works(self, admin_client):
        """Old-style single cash dict is still accepted for backward compat."""
        client, repo, token = admin_client
        create = client.post("/admin/trades", json={}, headers=_auth(token))
        trade_id = create.json()["trade_id"]

        resp = client.put(f"/admin/trades/{trade_id}/cash", json={
            "direction": "they_pay",
            "amount": "15.00",
            "payment_method": "cash",
        }, headers=_auth(token))
        assert resp.status_code == 200
        session = resp.json()
        # Should still have a cash key for backward compat
        assert session.get("cash") is not None or session.get("cash_components") is not None


class TestTradeMarginSplit:
    """PATCH /admin/trades/{id} — margin_split for vendor mode."""

    def test_set_vendor_mode_with_margin_split(self, admin_client):
        """Setting mode=vendor with margin_split stores the split."""
        client, repo, token = admin_client
        create = client.post("/admin/trades", json={"mode": "vendor"}, headers=_auth(token))
        trade_id = create.json()["trade_id"]

        resp = client.patch(f"/admin/trades/{trade_id}", json={
            "margin_split": {"enabled": True, "percent": "15"},
        }, headers=_auth(token))
        assert resp.status_code == 200
        session = resp.json()
        assert session["margin_split"]["enabled"] is True
        assert session["margin_split"]["percent"] == "15"

    def test_margin_split_defaults_to_none(self, admin_client):
        """New sessions have no margin_split."""
        client, repo, token = admin_client
        create = client.post("/admin/trades", json={}, headers=_auth(token))
        trade_id = create.json()["trade_id"]

        resp = client.get(f"/admin/trades/{trade_id}", headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json().get("margin_split") is None


class TestTradeBalanceMultiCash:
    """GET /admin/trades/{id}/balance — with multi-asset cash components."""

    def test_balance_with_cash_components(self, admin_client):
        """Balance computes net from multiple cash components."""
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="our-1", cost_basis="20.00",
                                     current_market_value="50.00"))

        create = client.post("/admin/trades", json={}, headers=_auth(token))
        trade_id = create.json()["trade_id"]

        client.post(f"/admin/trades/{trade_id}/outgoing", json={
            "item_id": "our-1", "agreed_value": "50.00",
        }, headers=_auth(token))
        client.post(f"/admin/trades/{trade_id}/incoming", json={
            "name": "Their card", "agreed_value": "30.00",
        }, headers=_auth(token))

        # Multi-cash: they pay $15 Venmo + $5 cash = $20 total they pay
        client.put(f"/admin/trades/{trade_id}/cash", json={
            "cash_components": [
                {"direction": "they_pay", "amount": "15.00", "payment_method": "venmo"},
                {"direction": "they_pay", "amount": "5.00", "payment_method": "cash"},
            ]
        }, headers=_auth(token))

        resp = client.get(f"/admin/trades/{trade_id}/balance", headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_out_value"] == "50.00"
        assert data["total_in_value"] == "30.00"
        # Cash net: +15 + 5 = 20 (they pay)
        assert data["cash_components_net"] == "20.00"
        assert data["is_balanced"] is True

    def test_balance_with_mixed_directions(self, admin_client):
        """Cash components with mixed directions are netted correctly."""
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="our-1", cost_basis="20.00",
                                     current_market_value="50.00"))

        create = client.post("/admin/trades", json={}, headers=_auth(token))
        trade_id = create.json()["trade_id"]

        client.post(f"/admin/trades/{trade_id}/outgoing", json={
            "item_id": "our-1", "agreed_value": "50.00",
        }, headers=_auth(token))
        client.post(f"/admin/trades/{trade_id}/incoming", json={
            "name": "Their card", "agreed_value": "40.00",
        }, headers=_auth(token))

        # They pay $15, we pay $5 = net +10 (they pay)
        client.put(f"/admin/trades/{trade_id}/cash", json={
            "cash_components": [
                {"direction": "they_pay", "amount": "15.00", "payment_method": "venmo"},
                {"direction": "we_pay", "amount": "5.00", "payment_method": "cash"},
            ]
        }, headers=_auth(token))

        resp = client.get(f"/admin/trades/{trade_id}/balance", headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["cash_components_net"] == "10.00"
        assert data["is_balanced"] is True

    def test_balance_with_margin_split(self, admin_client):
        """Balance reports legacy error when margin_split.enabled is True (3.0)."""
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="our-1", cost_basis="20.00",
                                     current_market_value="50.00"))

        create = client.post("/admin/trades", json={"mode": "vendor"}, headers=_auth(token))
        trade_id = create.json()["trade_id"]

        client.patch(f"/admin/trades/{trade_id}", json={
            "margin_split": {"enabled": True, "percent": "15"},
        }, headers=_auth(token))

        client.post(f"/admin/trades/{trade_id}/outgoing", json={
            "item_id": "our-1", "agreed_value": "50.00",
        }, headers=_auth(token))
        client.post(f"/admin/trades/{trade_id}/incoming", json={
            "name": "Their card", "agreed_value": "50.00",
        }, headers=_auth(token))

        resp = client.get(f"/admin/trades/{trade_id}/balance", headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert "margin_split_applied" not in data
        assert data["basis_mode_error"] == (
            "This trade uses the retired percent-based margin split; "
            "choose a basis mode"
        )


class TestTradeConfirmMultiCash:
    """POST /admin/trades/{id}/confirm with cash_components."""

    def test_confirm_creates_transactions_for_each_cash_component(self, admin_client):
        """Confirm creates separate transactions per cash component.
        3.0: cash requires manual basis mode.
        """
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="our-1", cost_basis="20.00",
                                     current_market_value="50.00"))

        create = client.post("/admin/trades", json={}, headers=_auth(token))
        trade_id = create.json()["trade_id"]

        client.patch(f"/admin/trades/{trade_id}", json={
            "basis_mode": "manual",
            "manual_basis": "20.00",
        }, headers=_auth(token))

        client.post(f"/admin/trades/{trade_id}/outgoing", json={
            "item_id": "our-1", "agreed_value": "50.00",
        }, headers=_auth(token))
        client.post(f"/admin/trades/{trade_id}/incoming", json={
            "name": "Their card", "agreed_value": "30.00",
        }, headers=_auth(token))

        client.put(f"/admin/trades/{trade_id}/cash", json={
            "cash_components": [
                {"direction": "they_pay", "amount": "15.00", "payment_method": "venmo"},
                {"direction": "they_pay", "amount": "5.00", "payment_method": "cash"},
            ]
        }, headers=_auth(token))

        resp = client.post(f"/admin/trades/{trade_id}/confirm", headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "confirmed"
        # 1 outgoing sale + 1 incoming purchase + 2 cash transactions = 4
        assert data["transactions_created"] == 4


# ===========================================================================
# 2.2: Trade engine — cost-basis deferral, margin split, lineage, timeline
# ===========================================================================

def _new_available_items(repo, exclude: set[str]):
    """Every AVAILABLE item not in ``exclude`` — i.e. the incoming items."""
    return [
        i for i in repo.list_inventory()
        if i.status == ItemStatus.AVAILABLE and i.item_id not in exclude
    ]


def _build_trade(client, token, *, out_legs=(), in_legs=(), cash_components=None,
                 margin_split=None, basis_mode=None, manual_basis=None):
    """Create a draft trade with the given legs and return its trade_id."""
    trade_id = client.post("/admin/trades", json={}, headers=_auth(token)).json()["trade_id"]
    patch_body: dict = {}
    if margin_split is not None:
        patch_body["margin_split"] = margin_split
    if basis_mode is not None:
        patch_body["basis_mode"] = basis_mode
    if manual_basis is not None:
        patch_body["manual_basis"] = manual_basis
    if patch_body:
        client.patch(f"/admin/trades/{trade_id}", json=patch_body,
                     headers=_auth(token))
    for item_id, agreed in out_legs:
        r = client.post(f"/admin/trades/{trade_id}/outgoing",
                        json={"item_id": item_id, "agreed_value": agreed},
                        headers=_auth(token))
        assert r.status_code == 200, r.text
    for name, agreed in in_legs:
        r = client.post(f"/admin/trades/{trade_id}/incoming",
                        json={"name": name, "agreed_value": agreed, "condition": "NM"},
                        headers=_auth(token))
        assert r.status_code == 200, r.text
    if cash_components:
        r = client.put(f"/admin/trades/{trade_id}/cash",
                       json={"cash_components": cash_components}, headers=_auth(token))
        assert r.status_code == 200, r.text
    return trade_id


class TestTradeCostBasisAllocation:
    """Incoming cost basis defers outgoing basis (spec §1 Cost Basis Logic)."""

    def test_incoming_basis_defers_outgoing_basis(self, admin_client):
        # out: cost_basis 15, agreed 20; in: one leg agreed 25; no cash.
        # deferred_pool = 15, no margin split -> incoming basis 15.00
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="our-1", cost_basis="15.00",
                                     current_market_value="20.00"))

        trade_id = _build_trade(client, token,
                                out_legs=[("our-1", "20.00")],
                                in_legs=[("Their Card", "25.00")])
        resp = client.post(f"/admin/trades/{trade_id}/confirm", headers=_auth(token))
        assert resp.status_code == 200, resp.text

        new_items = _new_available_items(repo, {"our-1"})
        assert len(new_items) == 1
        assert new_items[0].cost_basis == Decimal("15.00")

    def test_cash_adjusts_basis_pool(self, admin_client):
        # was: we pay $5 -> pool 15 + 5 = 20.00
        # 3.0: transfer (default) + cash -> 422 rejection
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="our-1", cost_basis="15.00",
                                     current_market_value="20.00"))
        trade_id = _build_trade(
            client, token,
            out_legs=[("our-1", "20.00")],
            in_legs=[("Their Card", "25.00")],
            cash_components=[{"direction": "we_pay", "amount": "5.00",
                              "payment_method": "cash"}],
        )
        resp = client.post(f"/admin/trades/{trade_id}/confirm", headers=_auth(token))
        assert resp.status_code == 422
        assert resp.json()["detail"] == "Cash components require Manual basis mode"

    def test_cash_they_pay_reduces_basis_pool(self, admin_client):
        # was: they pay $5 -> pool 15 - 5 = 10.00
        # 3.0: transfer (default) + cash -> 422 rejection
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="our-2", cost_basis="15.00",
                                     current_market_value="20.00"))
        trade_id = _build_trade(
            client, token,
            out_legs=[("our-2", "20.00")],
            in_legs=[("Their Card", "25.00")],
            cash_components=[{"direction": "they_pay", "amount": "5.00",
                              "payment_method": "cash"}],
        )
        resp = client.post(f"/admin/trades/{trade_id}/confirm", headers=_auth(token))
        assert resp.status_code == 422
        assert resp.json()["detail"] == "Cash components require Manual basis mode"

    def test_margin_split_raises_basis(self, admin_client):
        # was: margin split 50% recognizes part of profit
        # 3.0: legacy margin_split.enabled=True without basis_mode -> 422
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="our-1", cost_basis="15.00",
                                     current_market_value="20.00"))
        trade_id = _build_trade(client, token,
                                out_legs=[("our-1", "20.00")],
                                in_legs=[("Their Card", "25.00")],
                                margin_split={"enabled": True, "percent": "50"})
        resp = client.post(f"/admin/trades/{trade_id}/confirm", headers=_auth(token))
        assert resp.status_code == 422
        assert resp.json()["detail"] == (
            "This trade uses the retired percent-based margin split; "
            "choose a basis mode"
        )

    def test_margin_split_full_percent_makes_basis_equal_agreed_value(self, admin_client):
        # was: 100% split -> basis == agreed value
        # 3.0: legacy margin_split.enabled=True without basis_mode -> 422
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="our-1", cost_basis="15.00",
                                     current_market_value="20.00"))
        trade_id = _build_trade(client, token,
                                out_legs=[("our-1", "20.00")],
                                in_legs=[("Their Card", "25.00")],
                                margin_split={"enabled": True, "percent": "100"})
        resp = client.post(f"/admin/trades/{trade_id}/confirm", headers=_auth(token))
        assert resp.status_code == 422
        assert resp.json()["detail"] == (
            "This trade uses the retired percent-based margin split; "
            "choose a basis mode"
        )

    def test_margin_split_ignored_when_trade_is_a_loss(self, admin_client):
        # was: loss -> margin split ignored -> pool = out basis
        # 3.0: legacy margin_split.enabled=True without basis_mode -> 422
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="our-1", cost_basis="15.00",
                                     current_market_value="20.00"))
        trade_id = _build_trade(client, token,
                                out_legs=[("our-1", "20.00")],
                                in_legs=[("Their Card", "10.00")],
                                margin_split={"enabled": True, "percent": "50"})
        resp = client.post(f"/admin/trades/{trade_id}/confirm", headers=_auth(token))
        assert resp.status_code == 422
        assert resp.json()["detail"] == (
            "This trade uses the retired percent-based margin split; "
            "choose a basis mode"
        )

    def test_multi_incoming_pro_rata_with_rounding(self, admin_client):
        # pool 10.00 across agreed 10 & 20 -> 3.33 and 6.67, summing exactly
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="our-1", cost_basis="10.00",
                                     current_market_value="30.00"))
        trade_id = _build_trade(client, token,
                                out_legs=[("our-1", "30.00")],
                                in_legs=[("Card A", "10.00"), ("Card B", "20.00")])
        resp = client.post(f"/admin/trades/{trade_id}/confirm", headers=_auth(token))
        assert resp.status_code == 200, resp.text

        new_items = _new_available_items(repo, {"our-1"})
        assert len(new_items) == 2
        # Key on the leg, not on a sorted list: sorting would let an inverted
        # allocation (the 10.00 card getting 6.67) pass unnoticed.
        by_name = {i.display_name: i.cost_basis for i in new_items}
        assert by_name["Card A"] == Decimal("3.33")   # agreed 10 -> 10/30 of 10.00
        assert by_name["Card B"] == Decimal("6.67")   # agreed 20 -> 20/30 of 10.00
        assert sum(by_name.values()) == Decimal("10.00")

    def test_allocation_never_goes_negative(self, admin_client):
        """A near-zero pool across many legs must not hand any leg a negative basis.

        Rounding each leg half-up independently overspends a 0.04 pool across
        agreed [1,1,1,1,1,1,2] and the remainder-on-last-leg fix-up lands on
        -0.02, which would persist as a negative book cost.
        3.0: cash requires manual mode; operator enters 0.04 as the basis.
        """
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="our-1", cost_basis="100.04",
                                     current_market_value="120.00"))
        in_legs = [(f"Card {i}", "1.00") for i in range(6)] + [("Card 6", "2.00")]
        trade_id = _build_trade(
            client, token,
            out_legs=[("our-1", "120.00")],
            in_legs=in_legs,
            cash_components=[{"direction": "they_pay", "amount": "100.00",
                              "payment_method": "cash"}],
            basis_mode="manual",
            manual_basis="0.04",
        )
        resp = client.post(f"/admin/trades/{trade_id}/confirm", headers=_auth(token))
        assert resp.status_code == 200, resp.text

        new_items = _new_available_items(repo, {"our-1"})
        assert len(new_items) == 7
        bases = [i.cost_basis for i in new_items]
        assert all(b >= Decimal("0") for b in bases), bases
        # And the pool is still conserved exactly.
        assert sum(bases) == Decimal("0.04")

    def test_basis_pool_floors_at_zero(self, admin_client):
        # 3.0: cash requires manual mode; operator enters 0.00 as the basis
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="our-1", cost_basis="5.00",
                                     current_market_value="20.00"))
        trade_id = _build_trade(
            client, token,
            out_legs=[("our-1", "20.00")],
            in_legs=[("Their Card", "25.00")],
            cash_components=[{"direction": "they_pay", "amount": "50.00",
                              "payment_method": "cash"}],
            basis_mode="manual",
            manual_basis="0.00",
        )
        resp = client.post(f"/admin/trades/{trade_id}/confirm", headers=_auth(token))
        assert resp.status_code == 200, resp.text
        new_items = _new_available_items(repo, {"our-1"})
        assert new_items[0].cost_basis == Decimal("0.00")


class TestTradeLineage:
    def test_lineage_written_on_confirm(self, admin_client):
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="our-1", cost_basis="15.00",
                                     current_market_value="20.00"))
        trade_id = _build_trade(client, token,
                                out_legs=[("our-1", "20.00")],
                                in_legs=[("Their Card", "25.00")])
        resp = client.post(f"/admin/trades/{trade_id}/confirm", headers=_auth(token))
        assert resp.status_code == 200, resp.text

        new_items = _new_available_items(repo, {"our-1"})
        assert len(new_items) == 1
        new_item = new_items[0]
        old_item = repo.get_inventory_item("our-1")

        assert new_item.predecessor_item_id == "our-1"
        assert new_item.lineage_id is not None
        assert old_item.lineage_id == new_item.lineage_id
        assert old_item.status == ItemStatus.SOLD

        chain = client.get(f"/admin/inventory/{new_item.item_id}/lineage",
                           headers=_auth(token)).json()
        assert [c["item_id"] for c in chain["chain"]] == ["our-1", new_item.item_id]

    def test_multi_outgoing_shares_lineage_without_predecessor(self, admin_client):
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="our-1", cost_basis="10.00",
                                     current_market_value="20.00"))
        repo.put_inventory_item(_raw(item_id="our-2", card_id="sv1-2",
                                     cost_basis="10.00",
                                     current_market_value="20.00"))
        trade_id = _build_trade(client, token,
                                out_legs=[("our-1", "20.00"), ("our-2", "20.00")],
                                in_legs=[("Their Card", "40.00")])
        resp = client.post(f"/admin/trades/{trade_id}/confirm", headers=_auth(token))
        assert resp.status_code == 200, resp.text

        new_items = _new_available_items(repo, {"our-1", "our-2"})
        assert len(new_items) == 1
        new_item = new_items[0]
        assert new_item.predecessor_item_id is None
        assert new_item.lineage_id is not None
        assert repo.get_inventory_item("our-1").lineage_id == new_item.lineage_id
        assert repo.get_inventory_item("our-2").lineage_id == new_item.lineage_id

    def test_existing_lineage_id_is_reused(self, admin_client):
        client, repo, token = admin_client
        item = _raw(item_id="our-1", cost_basis="15.00", current_market_value="20.00")
        item.lineage_id = "root-lineage"
        repo.put_inventory_item(item)

        trade_id = _build_trade(client, token,
                                out_legs=[("our-1", "20.00")],
                                in_legs=[("Their Card", "25.00")])
        resp = client.post(f"/admin/trades/{trade_id}/confirm", headers=_auth(token))
        assert resp.status_code == 200, resp.text

        new_items = _new_available_items(repo, {"our-1"})
        assert new_items[0].lineage_id == "root-lineage"

    def test_outgoing_items_from_different_lineages_are_not_merged(self, admin_client):
        """Trading two already-chained cards must not rewrite either chain.

        W is in lineage L1. X is in lineage L2 and succeeds P (also L2).
        Adopting one id for both would drop P out of X's chain and strand it.
        """
        client, repo, token = admin_client

        # P: X's predecessor, already sold in the earlier trade that produced X.
        p = _raw(item_id="pred-p", card_id="sv1-p", cost_basis="5.00",
                 status=ItemStatus.SOLD)
        p.lineage_id = "L2"
        repo.put_inventory_item(p)

        x = _raw(item_id="our-x", card_id="sv1-x", cost_basis="10.00",
                 current_market_value="20.00")
        x.lineage_id = "L2"
        x.predecessor_item_id = "pred-p"
        repo.put_inventory_item(x)

        w = _raw(item_id="our-w", card_id="sv1-w", cost_basis="10.00",
                 current_market_value="20.00")
        w.lineage_id = "L1"
        repo.put_inventory_item(w)

        trade_id = _build_trade(client, token,
                                out_legs=[("our-w", "20.00"), ("our-x", "20.00")],
                                in_legs=[("Their Card", "40.00")])
        resp = client.post(f"/admin/trades/{trade_id}/confirm", headers=_auth(token))
        assert resp.status_code == 200, resp.text

        # Neither pre-existing chain was rewritten.
        assert repo.get_inventory_item("our-w").lineage_id == "L1"
        assert repo.get_inventory_item("our-x").lineage_id == "L2"
        assert repo.get_inventory_item("pred-p").lineage_id == "L2"

        # P is still reachable from X's chain, and X from P's.
        x_chain = client.get("/admin/inventory/our-x/lineage",
                             headers=_auth(token)).json()
        assert x_chain["lineage_id"] == "L2"
        assert [c["item_id"] for c in x_chain["chain"]] == ["pred-p", "our-x"]

        p_chain = client.get("/admin/inventory/pred-p/lineage",
                             headers=_auth(token)).json()
        assert [c["item_id"] for c in p_chain["chain"]] == ["pred-p", "our-x"]

        # The new card gets its own fresh lineage rather than hijacking either.
        new_items = _new_available_items(repo, {"our-w", "our-x", "pred-p"})
        assert len(new_items) == 1
        assert new_items[0].lineage_id not in {"L1", "L2", None}


class TestTradeInTimeline:
    def test_trade_in_timeline_event(self, admin_client):
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="our-1", cost_basis="15.00",
                                     current_market_value="20.00"))
        trade_id = _build_trade(client, token,
                                out_legs=[("our-1", "20.00")],
                                in_legs=[("Their Card", "25.00")])
        resp = client.post(f"/admin/trades/{trade_id}/confirm", headers=_auth(token))
        assert resp.status_code == 200, resp.text

        new_items = _new_available_items(repo, {"our-1"})
        new_id = new_items[0].item_id

        events = repo.get_timeline_events(new_id)
        trade_ins = [e for e in events if e.get("type") == "trade_in"]
        assert len(trade_ins) == 1
        evt = trade_ins[0]
        assert evt["counterpart_item_id"] == "our-1"
        assert evt["trade_id"] == trade_id
        assert evt["amount"] == "25.00"
        assert evt["payment_method"] == "trade"
        assert evt["txn_id"]


class TestTradeCashValidation:
    def test_cash_payment_method_validated(self, admin_client):
        client, repo, token = admin_client
        trade_id = client.post("/admin/trades", json={},
                               headers=_auth(token)).json()["trade_id"]

        bad = client.put(f"/admin/trades/{trade_id}/cash", json={
            "cash_components": [
                {"direction": "they_pay", "amount": "10.00", "payment_method": "paypal"},
            ]
        }, headers=_auth(token))
        assert bad.status_code == 422

        good = client.put(f"/admin/trades/{trade_id}/cash", json={
            "cash_components": [
                {"direction": "they_pay", "amount": "10.00", "payment_method": "zelle"},
            ]
        }, headers=_auth(token))
        assert good.status_code == 200

    def test_legacy_cash_payment_method_validated(self, admin_client):
        client, repo, token = admin_client
        trade_id = client.post("/admin/trades", json={},
                               headers=_auth(token)).json()["trade_id"]

        bad = client.put(f"/admin/trades/{trade_id}/cash", json={
            "direction": "they_pay", "amount": "10.00", "payment_method": "paypal",
        }, headers=_auth(token))
        assert bad.status_code == 422

        good = client.put(f"/admin/trades/{trade_id}/cash", json={
            "direction": "they_pay", "amount": "10.00", "payment_method": "venmo",
        }, headers=_auth(token))
        assert good.status_code == 200


class TestTradeIncomingLocation:
    def test_incoming_leg_rejects_unknown_location(self, admin_client):
        client, repo, token = admin_client
        trade_id = client.post("/admin/trades", json={},
                               headers=_auth(token)).json()["trade_id"]

        resp = client.post(f"/admin/trades/{trade_id}/incoming", json={
            "name": "Their Card", "agreed_value": "25.00", "location": "under_the_bed",
        }, headers=_auth(token))
        assert resp.status_code == 422

    def test_incoming_leg_location_flows_to_created_item(self, admin_client):
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="our-1", cost_basis="15.00",
                                     current_market_value="20.00"))
        trade_id = client.post("/admin/trades", json={},
                               headers=_auth(token)).json()["trade_id"]
        client.post(f"/admin/trades/{trade_id}/outgoing", json={
            "item_id": "our-1", "agreed_value": "20.00",
        }, headers=_auth(token))
        resp = client.post(f"/admin/trades/{trade_id}/incoming", json={
            "name": "Their Card", "agreed_value": "25.00", "location": "binder",
        }, headers=_auth(token))
        assert resp.status_code == 200, resp.text

        client.post(f"/admin/trades/{trade_id}/confirm", headers=_auth(token))
        new_items = _new_available_items(repo, {"our-1"})
        assert new_items[0].location == "binder"


# ===========================================================================
# 3.0: Trade basis MODES (transfer / split / manual)
# ===========================================================================

class TestTradeBasisModes:
    """3.0: Three named basis modes replace percent-based margin split."""

    def test_patch_accepts_basis_mode(self, admin_client):
        client, repo, token = admin_client
        trade_id = client.post("/admin/trades", json={},
                               headers=_auth(token)).json()["trade_id"]
        resp = client.patch(f"/admin/trades/{trade_id}", json={
            "basis_mode": "split",
        }, headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["basis_mode"] == "split"

    def test_patch_accepts_manual_basis(self, admin_client):
        client, repo, token = admin_client
        trade_id = client.post("/admin/trades", json={},
                               headers=_auth(token)).json()["trade_id"]
        resp = client.patch(f"/admin/trades/{trade_id}", json={
            "basis_mode": "manual",
            "manual_basis": "42.50",
        }, headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["basis_mode"] == "manual"
        assert resp.json()["manual_basis"] == "42.50"

    def test_transfer_mode_basis_equals_outgoing_cost(self, admin_client):
        """Transfer: incoming basis = total outgoing cost basis (owner's example)."""
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="our-1", cost_basis="15.00",
                                     current_market_value="20.00"))
        trade_id = _build_trade(client, token,
                                out_legs=[("our-1", "20.00")],
                                in_legs=[("Their Card", "25.00")])
        resp = client.post(f"/admin/trades/{trade_id}/confirm", headers=_auth(token))
        assert resp.status_code == 200
        new_items = _new_available_items(repo, {"our-1"})
        assert new_items[0].cost_basis == Decimal("15.00")

    def test_split_mode_basis_equals_midpoint(self, admin_client):
        """Split: basis = (out_basis + in_agreed) / 2.

        Owner's worked example: out cost $15, in agreed $25 -> (15+25)/2 = $20.
        """
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="our-1", cost_basis="15.00",
                                     current_market_value="20.00"))
        trade_id = _build_trade(client, token,
                                out_legs=[("our-1", "20.00")],
                                in_legs=[("Their Card", "25.00")],
                                basis_mode="split")
        resp = client.post(f"/admin/trades/{trade_id}/confirm", headers=_auth(token))
        assert resp.status_code == 200
        new_items = _new_available_items(repo, {"our-1"})
        assert new_items[0].cost_basis == Decimal("20.00")

    def test_manual_mode_uses_supplied_basis(self, admin_client):
        """Manual: incoming basis = operator-supplied value."""
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="our-1", cost_basis="15.00",
                                     current_market_value="20.00"))
        trade_id = _build_trade(client, token,
                                out_legs=[("our-1", "20.00")],
                                in_legs=[("Their Card", "25.00")],
                                basis_mode="manual",
                                manual_basis="18.00")
        resp = client.post(f"/admin/trades/{trade_id}/confirm", headers=_auth(token))
        assert resp.status_code == 200
        new_items = _new_available_items(repo, {"our-1"})
        assert new_items[0].cost_basis == Decimal("18.00")

    def test_transfer_mode_rejects_cash(self, admin_client):
        """Transfer + cash -> 422 (explicit basis_mode)."""
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="our-1", cost_basis="15.00",
                                     current_market_value="20.00"))
        trade_id = _build_trade(client, token,
                                out_legs=[("our-1", "20.00")],
                                in_legs=[("Their Card", "25.00")],
                                cash_components=[{"direction": "we_pay", "amount": "5.00",
                                                  "payment_method": "cash"}],
                                basis_mode="transfer")
        resp = client.post(f"/admin/trades/{trade_id}/confirm", headers=_auth(token))
        assert resp.status_code == 422
        assert resp.json()["detail"] == "Cash components require Manual basis mode"

    def test_split_mode_rejects_cash(self, admin_client):
        """Split + cash -> 422."""
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="our-1", cost_basis="15.00",
                                     current_market_value="20.00"))
        trade_id = _build_trade(client, token,
                                out_legs=[("our-1", "20.00")],
                                in_legs=[("Their Card", "25.00")],
                                cash_components=[{"direction": "they_pay", "amount": "5.00",
                                                  "payment_method": "cash"}],
                                basis_mode="split")
        resp = client.post(f"/admin/trades/{trade_id}/confirm", headers=_auth(token))
        assert resp.status_code == 422
        assert resp.json()["detail"] == "Cash components require Manual basis mode"

    def test_manual_mode_allows_cash(self, admin_client):
        """Manual + cash -> OK."""
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="our-1", cost_basis="15.00",
                                     current_market_value="20.00"))
        trade_id = _build_trade(client, token,
                                out_legs=[("our-1", "20.00")],
                                in_legs=[("Their Card", "25.00")],
                                cash_components=[{"direction": "we_pay", "amount": "5.00",
                                                  "payment_method": "cash"}],
                                basis_mode="manual",
                                manual_basis="20.00")
        resp = client.post(f"/admin/trades/{trade_id}/confirm", headers=_auth(token))
        assert resp.status_code == 200

    def test_manual_mode_rejects_null_basis(self, admin_client):
        """Manual without manual_basis -> 422."""
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="our-1", cost_basis="15.00",
                                     current_market_value="20.00"))
        trade_id = _build_trade(client, token,
                                out_legs=[("our-1", "20.00")],
                                in_legs=[("Their Card", "25.00")],
                                basis_mode="manual")
        resp = client.post(f"/admin/trades/{trade_id}/confirm", headers=_auth(token))
        assert resp.status_code == 422
        assert resp.json()["detail"] == (
            "Manual basis mode requires a total basis amount"
        )

    def test_legacy_margin_split_enabled_rejects_confirm(self, admin_client):
        """Legacy margin_split.enabled=True without explicit basis_mode -> 422."""
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="our-1", cost_basis="15.00",
                                     current_market_value="20.00"))
        trade_id = _build_trade(client, token,
                                out_legs=[("our-1", "20.00")],
                                in_legs=[("Their Card", "25.00")],
                                margin_split={"enabled": True, "percent": "50"})
        resp = client.post(f"/admin/trades/{trade_id}/confirm", headers=_auth(token))
        assert resp.status_code == 422
        assert resp.json()["detail"] == (
            "This trade uses the retired percent-based margin split; "
            "choose a basis mode"
        )

    def test_confirmed_session_stores_basis_mode(self, admin_client):
        """Confirmed session persists the basis_mode used."""
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="our-1", cost_basis="15.00",
                                     current_market_value="20.00"))
        trade_id = _build_trade(client, token,
                                out_legs=[("our-1", "20.00")],
                                in_legs=[("Their Card", "25.00")],
                                basis_mode="split")
        client.post(f"/admin/trades/{trade_id}/confirm", headers=_auth(token))
        session = client.get(f"/admin/trades/{trade_id}",
                             headers=_auth(token)).json()
        assert session["basis_mode"] == "split"


class TestTradeCardOnlyInvariant:
    """Invariant: for card-only trades, total outgoing sale amounts == total incoming bases."""

    def test_invariant_transfer_single_leg(self, admin_client):
        """1-out/1-in transfer: sale amount = out basis = incoming basis."""
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="our-1", cost_basis="15.00",
                                     current_market_value="20.00"))
        trade_id = _build_trade(client, token,
                                out_legs=[("our-1", "20.00")],
                                in_legs=[("Their Card", "25.00")])
        client.post(f"/admin/trades/{trade_id}/confirm", headers=_auth(token))

        # Check outgoing sale transaction amount via timeline
        out_events = repo.get_timeline_events("our-1")
        trade_outs = [e for e in out_events if e.get("type") == "trade_out"]
        assert len(trade_outs) == 1
        sale_amount = Decimal(trade_outs[0]["amount"])

        # Check incoming cost basis
        new_items = _new_available_items(repo, {"our-1"})
        assert len(new_items) == 1
        incoming_basis = new_items[0].cost_basis

        # Invariant: sale amount == incoming basis
        assert sale_amount == incoming_basis == Decimal("15.00")

    def test_invariant_split_mode(self, admin_client):
        """Split mode: sale amounts and incoming bases both sum to midpoint."""
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="our-1", cost_basis="15.00",
                                     current_market_value="20.00"))
        trade_id = _build_trade(client, token,
                                out_legs=[("our-1", "20.00")],
                                in_legs=[("Their Card", "25.00")],
                                basis_mode="split")
        client.post(f"/admin/trades/{trade_id}/confirm", headers=_auth(token))

        out_events = repo.get_timeline_events("our-1")
        trade_outs = [e for e in out_events if e.get("type") == "trade_out"]
        sale_amount = Decimal(trade_outs[0]["amount"])

        new_items = _new_available_items(repo, {"our-1"})
        incoming_basis = new_items[0].cost_basis

        # (15 + 25) / 2 = 20
        assert sale_amount == incoming_basis == Decimal("20.00")

    def test_invariant_manual_card_only(self, admin_client):
        """Manual mode (card-only): sale = incoming basis = manual_basis."""
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="our-1", cost_basis="15.00",
                                     current_market_value="20.00"))
        trade_id = _build_trade(client, token,
                                out_legs=[("our-1", "20.00")],
                                in_legs=[("Their Card", "25.00")],
                                basis_mode="manual",
                                manual_basis="18.00")
        client.post(f"/admin/trades/{trade_id}/confirm", headers=_auth(token))

        out_events = repo.get_timeline_events("our-1")
        trade_outs = [e for e in out_events if e.get("type") == "trade_out"]
        sale_amount = Decimal(trade_outs[0]["amount"])

        new_items = _new_available_items(repo, {"our-1"})
        incoming_basis = new_items[0].cost_basis

        assert sale_amount == incoming_basis == Decimal("18.00")

    def test_invariant_multi_leg(self, admin_client):
        """Multi-leg transfer: total sale amounts == total incoming bases."""
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="our-1", cost_basis="10.00",
                                     current_market_value="20.00"))
        repo.put_inventory_item(_raw(item_id="our-2", card_id="sv1-2",
                                     cost_basis="5.00",
                                     current_market_value="15.00"))
        trade_id = _build_trade(client, token,
                                out_legs=[("our-1", "20.00"), ("our-2", "15.00")],
                                in_legs=[("Card A", "10.00"), ("Card B", "25.00")])
        client.post(f"/admin/trades/{trade_id}/confirm", headers=_auth(token))

        # Sum outgoing sale amounts from timeline
        out1_events = repo.get_timeline_events("our-1")
        out2_events = repo.get_timeline_events("our-2")
        sale1 = Decimal([e for e in out1_events
                         if e.get("type") == "trade_out"][0]["amount"])
        sale2 = Decimal([e for e in out2_events
                         if e.get("type") == "trade_out"][0]["amount"])
        total_sale = sale1 + sale2

        # Sum incoming bases
        new_items = _new_available_items(repo, {"our-1", "our-2"})
        total_basis = sum(i.cost_basis for i in new_items)

        # Transfer: basis_pool = 10 + 5 = 15
        assert total_sale == total_basis == Decimal("15.00")


class TestTradeBalanceBasisMode:
    """GET /admin/trades/{id}/balance -- basis mode fields (3.0)."""

    def test_balance_returns_basis_mode_fields(self, admin_client):
        """Balance response includes new basis mode fields, drops margin_split_applied."""
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="our-1", cost_basis="20.00",
                                     current_market_value="50.00"))
        trade_id = client.post("/admin/trades", json={},
                               headers=_auth(token)).json()["trade_id"]
        client.post(f"/admin/trades/{trade_id}/outgoing", json={
            "item_id": "our-1", "agreed_value": "50.00",
        }, headers=_auth(token))
        client.post(f"/admin/trades/{trade_id}/incoming", json={
            "name": "Their card", "agreed_value": "40.00",
        }, headers=_auth(token))

        resp = client.get(f"/admin/trades/{trade_id}/balance",
                          headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()

        assert data["basis_mode"] == "transfer"
        assert data["has_cash"] is False
        assert data["projected_basis_pool"] == "20.00"
        assert data["basis_mode_error"] is None
        assert "margin_split_applied" not in data

    def test_balance_projected_pool_split(self, admin_client):
        """Split mode: projected_basis_pool = (out_basis + in_agreed) / 2."""
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="our-1", cost_basis="20.00",
                                     current_market_value="50.00"))
        trade_id = client.post("/admin/trades", json={},
                               headers=_auth(token)).json()["trade_id"]
        client.patch(f"/admin/trades/{trade_id}", json={
            "basis_mode": "split",
        }, headers=_auth(token))
        client.post(f"/admin/trades/{trade_id}/outgoing", json={
            "item_id": "our-1", "agreed_value": "50.00",
        }, headers=_auth(token))
        client.post(f"/admin/trades/{trade_id}/incoming", json={
            "name": "Their card", "agreed_value": "40.00",
        }, headers=_auth(token))

        resp = client.get(f"/admin/trades/{trade_id}/balance",
                          headers=_auth(token))
        data = resp.json()
        # (20 + 40) / 2 = 30
        assert data["projected_basis_pool"] == "30.00"

    def test_balance_projected_pool_manual_with_value(self, admin_client):
        """Manual mode with value: projected_basis_pool = the value."""
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="our-1", cost_basis="20.00",
                                     current_market_value="50.00"))
        trade_id = client.post("/admin/trades", json={},
                               headers=_auth(token)).json()["trade_id"]
        client.patch(f"/admin/trades/{trade_id}", json={
            "basis_mode": "manual",
            "manual_basis": "35.00",
        }, headers=_auth(token))
        client.post(f"/admin/trades/{trade_id}/outgoing", json={
            "item_id": "our-1", "agreed_value": "50.00",
        }, headers=_auth(token))
        client.post(f"/admin/trades/{trade_id}/incoming", json={
            "name": "Their card", "agreed_value": "40.00",
        }, headers=_auth(token))

        resp = client.get(f"/admin/trades/{trade_id}/balance",
                          headers=_auth(token))
        data = resp.json()
        assert data["projected_basis_pool"] == "35.00"

    def test_balance_projected_pool_manual_without_value(self, admin_client):
        """Manual mode without value: projected_basis_pool = null, error set."""
        client, repo, token = admin_client
        trade_id = client.post("/admin/trades", json={},
                               headers=_auth(token)).json()["trade_id"]
        client.patch(f"/admin/trades/{trade_id}", json={
            "basis_mode": "manual",
        }, headers=_auth(token))

        resp = client.get(f"/admin/trades/{trade_id}/balance",
                          headers=_auth(token))
        data = resp.json()
        assert data["projected_basis_pool"] is None
        assert data["basis_mode_error"] == (
            "Manual basis mode requires a total basis amount"
        )

    def test_balance_has_cash_true(self, admin_client):
        """has_cash is true when cash components exist."""
        client, repo, token = admin_client
        trade_id = client.post("/admin/trades", json={},
                               headers=_auth(token)).json()["trade_id"]
        client.put(f"/admin/trades/{trade_id}/cash", json={
            "cash_components": [
                {"direction": "they_pay", "amount": "10.00",
                 "payment_method": "cash"},
            ]
        }, headers=_auth(token))

        resp = client.get(f"/admin/trades/{trade_id}/balance",
                          headers=_auth(token))
        data = resp.json()
        assert data["has_cash"] is True
        assert data["basis_mode_error"] == (
            "Cash components require Manual basis mode"
        )

    def test_balance_legacy_margin_split_error(self, admin_client):
        """Legacy margin_split.enabled=True reports error on balance."""
        client, repo, token = admin_client
        trade_id = client.post("/admin/trades", json={},
                               headers=_auth(token)).json()["trade_id"]
        client.patch(f"/admin/trades/{trade_id}", json={
            "margin_split": {"enabled": True, "percent": "15"},
        }, headers=_auth(token))

        resp = client.get(f"/admin/trades/{trade_id}/balance",
                          headers=_auth(token))
        data = resp.json()
        assert data["basis_mode_error"] == (
            "This trade uses the retired percent-based margin split; "
            "choose a basis mode"
        )
