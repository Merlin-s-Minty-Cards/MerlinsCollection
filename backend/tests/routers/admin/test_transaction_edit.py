"""RFC 0024 T3 — a typo in the ledger has a correction path distinct from void.

``PATCH /admin/transactions/{txn_id}``. A void says "this did not happen";
this says "this happened, I typed it wrong" — see CLAUDE.md's "THE LEDGER HAS
A CORRECTION PATH" section.

Money is sent as a JSON **number** in every test here, never a string — the
suite's habit of sending strings is exactly why a production 500 on a bare
float went unnoticed for months (CLAUDE.md, "Never write a bare float to
DynamoDB").
"""

from datetime import date
from decimal import Decimal

from merlins_collection.models.business import (
    ItemCategory,
    Show,
    Transaction,
    TransactionType,
)
from merlins_collection.models.inventory import InventoryItemAdapter


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _item(item_id: str, *, status: str = "available", cost: str = "10.00"):
    return InventoryItemAdapter.validate_python({
        "kind": "raw",
        "item_id": item_id,
        "status": status,
        "finish": "holofoil",
        "condition": "NM",
        "cost_basis": cost,
        "acquired_at": date(2026, 1, 1).isoformat(),
    })


def _txn(txn_type, item_id, day, amount, **kw) -> Transaction:
    return Transaction(
        type=txn_type, item_id=item_id, category=ItemCategory.RAW,
        date=day, amount=Decimal(amount), payment_method="cash", **kw,
    )


def _seed_purchase(repo, item_id="item-1", day=None, amount="32.00", **kw):
    day = day or date.today()
    repo.put_inventory_item(_item(item_id, cost=amount))
    txn = _txn(TransactionType.PURCHASE, item_id, day, amount, **kw)
    repo.put_transaction(txn)
    return txn


def _seed_sale(repo, item_id="item-1", day=None, amount="40.00", **kw):
    day = day or date.today()
    repo.put_inventory_item(_item(item_id, status="sold"))
    txn = _txn(TransactionType.SALE, item_id, day, amount, **kw)
    repo.put_transaction(txn)
    return txn


class TestRefusals:
    def test_editing_a_voided_transaction_is_409(self, admin_client):
        client, repo, token = admin_client
        txn = _seed_sale(repo)
        client.post(f"/admin/transactions/{txn.txn_id}/void",
                    json={"reason": "oops"}, headers=_auth(token))

        resp = client.patch(f"/admin/transactions/{txn.txn_id}",
                            json={"amount": 45}, headers=_auth(token))
        assert resp.status_code == 409

    def test_editing_a_trade_leg_is_400(self, admin_client):
        client, repo, token = admin_client
        txn = _seed_sale(repo, trade_id="trade-1", batch_id="trade-1")

        resp = client.patch(f"/admin/transactions/{txn.txn_id}",
                            json={"amount": 45}, headers=_auth(token))
        assert resp.status_code == 400
        assert "trade" in resp.json()["detail"].lower()

    def test_unknown_txn_id_is_404(self, admin_client):
        client, repo, token = admin_client
        resp = client.patch("/admin/transactions/nope", json={"amount": 45},
                            headers=_auth(token))
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Transaction not found"

    def test_a_disallowed_field_is_422(self, admin_client):
        client, repo, token = admin_client
        txn = _seed_sale(repo)
        resp = client.patch(f"/admin/transactions/{txn.txn_id}",
                            json={"item_id": "somewhere-else"}, headers=_auth(token))
        assert resp.status_code == 422

    def test_type_is_disallowed(self, admin_client):
        client, repo, token = admin_client
        txn = _seed_sale(repo)
        resp = client.patch(f"/admin/transactions/{txn.txn_id}",
                            json={"type": "purchase"}, headers=_auth(token))
        assert resp.status_code == 422

    def test_clearing_amount_to_null_is_422(self, admin_client):
        client, repo, token = admin_client
        txn = _seed_sale(repo)
        resp = client.patch(f"/admin/transactions/{txn.txn_id}",
                            json={"amount": None}, headers=_auth(token))
        assert resp.status_code == 422


class TestSameDateAmountEdit:
    def test_amount_is_corrected_and_audited(self, admin_client):
        client, repo, token = admin_client
        txn = _seed_sale(repo, amount="150.00")

        resp = client.patch(f"/admin/transactions/{txn.txn_id}",
                            json={"amount": 105}, headers=_auth(token))
        assert resp.status_code == 200
        body = resp.json()
        assert body["amount"] == "105.00" or Decimal(body["amount"]) == Decimal("105")
        assert body["edited_at"] is not None
        assert body["edited_by"] == "merlin"
        [entry] = body["edit_history"]
        assert entry["by"] == "merlin"
        [change] = entry["changes"]
        assert change["field"] == "amount"
        assert change["old"] == "150.00"

        [stored] = [t for t in repo.list_transactions(txn.date, txn.date)
                    if t.txn_id == txn.txn_id]
        assert stored.amount == Decimal("105")
        assert stored.edited_by == "merlin"

    def test_edited_by_is_the_authenticated_principal_not_the_body(self, admin_client):
        client, repo, token = admin_client
        txn = _seed_sale(repo)
        resp = client.patch(f"/admin/transactions/{txn.txn_id}",
                            json={"amount": 99, "edited_by": "somebody-else"},
                            headers=_auth(token))
        # `edited_by` isn't in the allowed field set at all.
        assert resp.status_code == 422

    def test_a_value_matching_what_is_already_stored_is_a_no_op(self, admin_client):
        client, repo, token = admin_client
        txn = _seed_sale(repo, amount="40.00")
        resp = client.patch(f"/admin/transactions/{txn.txn_id}",
                            json={"amount": 40}, headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["edited_at"] is None
        assert resp.json()["edit_history"] == []


class TestCrossMonthDateEdit:
    def test_the_old_key_is_gone_and_the_new_one_exists(self, admin_client):
        client, repo, token = admin_client
        txn = _seed_sale(repo, day=date(2026, 1, 15), amount="40.00")

        resp = client.patch(f"/admin/transactions/{txn.txn_id}",
                            json={"date": "2026-03-01"}, headers=_auth(token))
        assert resp.status_code == 200

        jan = repo.list_transactions(date(2026, 1, 1), date(2026, 1, 31))
        assert all(t.txn_id != txn.txn_id for t in jan), "the old-month row must be gone"

        march = repo.list_transactions(date(2026, 3, 1), date(2026, 3, 31))
        [moved] = [t for t in march if t.txn_id == txn.txn_id]
        assert moved.date == date(2026, 3, 1)
        assert moved.amount == Decimal("40.00")


class TestCostBasisSync:
    def test_a_purchase_amount_edit_follows_the_items_cost_basis(self, admin_client):
        client, repo, token = admin_client
        txn = _seed_purchase(repo, item_id="item-9", amount="32.00")

        resp = client.patch(f"/admin/transactions/{txn.txn_id}",
                            json={"amount": 40}, headers=_auth(token))
        assert resp.status_code == 200
        body = resp.json()
        assert body["cost_basis_updated"] is True
        assert body["cost_basis_skipped_reason"] is None
        assert repo.get_inventory_item("item-9").cost_basis == Decimal("40")

    def test_a_sale_amount_edit_never_touches_cost_basis(self, admin_client):
        client, repo, token = admin_client
        txn = _seed_sale(repo, item_id="item-9", amount="40.00")
        repo.put_inventory_item(_item("item-9", status="sold", cost="12.00"))

        resp = client.patch(f"/admin/transactions/{txn.txn_id}",
                            json={"amount": 55}, headers=_auth(token))
        assert resp.status_code == 200
        body = resp.json()
        assert body["cost_basis_updated"] is False
        assert body["cost_basis_skipped_reason"] is None
        assert repo.get_inventory_item("item-9").cost_basis == Decimal("12.00")

    def test_cost_basis_sync_is_skipped_and_reported_when_hand_corrected_since(
            self, admin_client):
        client, repo, token = admin_client
        txn = _seed_purchase(repo, item_id="item-9", amount="32.00")
        # An admin corrected the item's cost basis by hand since the purchase.
        repo.put_inventory_item(_item("item-9", cost="99.00"))

        resp = client.patch(f"/admin/transactions/{txn.txn_id}",
                            json={"amount": 40}, headers=_auth(token))
        assert resp.status_code == 200
        body = resp.json()
        assert body["cost_basis_updated"] is False
        assert body["cost_basis_skipped_reason"] == "cost basis was changed manually since"
        # The hand correction survives untouched.
        assert repo.get_inventory_item("item-9").cost_basis == Decimal("99.00")
        # But the ledger edit itself still applied.
        [stored] = [t for t in repo.list_transactions(txn.date, txn.date)
                    if t.txn_id == txn.txn_id]
        assert stored.amount == Decimal("40")

    def test_cost_basis_sync_is_skipped_and_reported_when_the_item_is_gone(
            self, admin_client):
        client, repo, token = admin_client
        # Deliberately never seeded via `put_inventory_item` — a purchase
        # transaction pointing at an item that no longer exists (or never
        # did, in this synthetic case).
        txn = _txn(TransactionType.PURCHASE, "item-ghost", date.today(), "32.00")
        repo.put_transaction(txn)
        assert repo.get_inventory_item("item-ghost") is None

        resp = client.patch(f"/admin/transactions/{txn.txn_id}",
                            json={"amount": 40}, headers=_auth(token))
        assert resp.status_code == 200
        body = resp.json()
        assert body["cost_basis_updated"] is False
        assert body["cost_basis_skipped_reason"] == "item not found"


class TestTimelineAndStaleness:
    def test_edit_appends_a_timeline_event_keyed_to_avoid_the_sale_event(
            self, admin_client):
        client, repo, token = admin_client
        txn = _seed_sale(repo, amount="40.00")
        repo.put_timeline_event("item-1", {
            "item_id": "item-1", "txn_id": txn.txn_id, "type": "sale",
            "date": txn.date.isoformat(), "amount": "40.00",
            "payment_method": "cash",
        })

        resp = client.patch(f"/admin/transactions/{txn.txn_id}",
                            json={"amount": 45}, headers=_auth(token))
        assert resp.status_code == 200

        events = repo.get_timeline_events("item-1")
        types = [e["type"] for e in events]
        assert "sale" in types, "the original sale event must survive"
        assert "edited" in types
        edit_event = next(e for e in events if e["type"] == "edited")
        assert edit_event["edited_txn_id"] == txn.txn_id
        assert edit_event["txn_id"] == f"{txn.txn_id}#edit"

    def test_edit_marks_the_affected_show_snapshot_stale(self, admin_client):
        client, repo, token = admin_client
        repo.put_show(Show(show_id="show-1", name="Portland", date=date.today()))
        txn = _seed_sale(repo, show_id="show-1")

        gen = client.post("/admin/shows/show-1/analytics/generate",
                          headers=_auth(token))
        assert gen.status_code == 200
        assert gen.json()["stale"] is False

        client.patch(f"/admin/transactions/{txn.txn_id}",
                    json={"amount": 60}, headers=_auth(token))

        snap = client.get("/admin/shows/show-1/analytics", headers=_auth(token))
        assert snap.json()["stale"] is True

    def test_is_countable_is_unaffected_by_an_edit(self, admin_client):
        """`services.ledger.is_countable` has exactly one definition — an
        edited row is still countable, exactly like a non-voided row."""
        client, repo, token = admin_client
        from merlins_collection.services.ledger import is_countable

        txn = _seed_sale(repo, amount="40.00")
        client.patch(f"/admin/transactions/{txn.txn_id}",
                    json={"amount": 45}, headers=_auth(token))
        [stored] = [t for t in repo.list_transactions(txn.date, txn.date)
                    if t.txn_id == txn.txn_id]
        assert is_countable(stored) is True
