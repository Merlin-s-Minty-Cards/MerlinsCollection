"""RFC 0010 T11 — an accidental sale can be undone.

``POST /admin/transactions/{txn_id}/void`` and ``/restore``.

**The safety property this file exists to pin:** a void honoured by some
aggregates and not others produces two disagreeing sets of books, which is worse
than having no void at all. There is exactly ONE countability predicate
(``services.ledger.is_countable``) and every reader calls it. The eight
per-reader tests at the bottom are the point of the task — do not collapse them
into one parameterised case that a later refactor can silently narrow.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from merlins_collection.models.business import (
    ItemCategory,
    Show,
    Transaction,
    TransactionType,
)
from merlins_collection.models.inventory import InventoryItemAdapter


# A real ``datetime``, not an ISO string: assignment is unvalidated on this
# model, and a string here makes every ``model_dump`` emit a serializer
# warning while quietly testing a shape the API never produces.
_VOIDED_AT = datetime(2026, 8, 11, tzinfo=timezone.utc)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _item(item_id: str, *, status: str = "available",
          acquired: date | None = None, cost: str = "10.00",
          market: str | None = None):
    data = {
        "kind": "raw",
        "item_id": item_id,
        "status": status,
        "finish": "holofoil",
        "condition": "NM",
        "cost_basis": cost,
        "acquired_at": (acquired or date(2026, 1, 1)).isoformat(),
    }
    if market is not None:
        data["current_market_value"] = market
    return InventoryItemAdapter.validate_python(data)


def _txn(txn_type, item_id, day, amount, **kw) -> Transaction:
    return Transaction(
        type=txn_type, item_id=item_id, category=ItemCategory.RAW,
        date=day, amount=Decimal(amount), payment_method="cash", **kw,
    )


def _sold_sale(repo, item_id="item-1", day=None, amount="40.00", **kw):
    """Seed a sold item plus the SALE that sold it. Returns the transaction."""
    day = day or date.today()
    repo.put_inventory_item(_item(item_id, status="sold"))
    txn = _txn(TransactionType.SALE, item_id, day, amount, **kw)
    repo.put_transaction(txn)
    return txn


# ===========================================================================
# The ONE predicate
# ===========================================================================

class TestIsCountable:
    def test_ordinary_transaction_counts(self):
        from merlins_collection.services.ledger import is_countable

        assert is_countable(_txn(
            TransactionType.SALE, "i1", date(2026, 8, 10), "40.00")) is True

    def test_voided_transaction_does_not_count(self):
        from merlins_collection.services.ledger import is_countable

        txn = _txn(TransactionType.SALE, "i1", date(2026, 8, 10), "40.00")
        txn.voided_at = _VOIDED_AT
        assert is_countable(txn) is False


# ===========================================================================
# POST /admin/transactions/{txn_id}/void
# ===========================================================================

class TestVoidTransaction:
    def test_void_stamps_fields_and_returns_item_to_stock(self, admin_client):
        """The two halves of a sale are reversed together."""
        client, repo, token = admin_client
        txn = _sold_sale(repo)

        resp = client.post(
            f"/admin/transactions/{txn.txn_id}/void",
            json={"reason": "Rang up the wrong card"},
            headers=_auth(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["voided_at"] is not None
        assert body["voided_by"]
        assert body["void_reason"] == "Rang up the wrong card"

        assert repo.get_inventory_item("item-1").status == "available"
        [stored] = [t for t in repo.list_transactions(txn.date, txn.date)
                    if t.txn_id == txn.txn_id]
        assert stored.voided_at is not None
        assert stored.void_reason == "Rang up the wrong card"

    def test_voided_by_is_the_authenticated_principal_not_the_body(self, admin_client):
        """A client's claim about who voided a sale is not evidence."""
        client, repo, token = admin_client
        txn = _sold_sale(repo)

        resp = client.post(
            f"/admin/transactions/{txn.txn_id}/void",
            json={"reason": "oops", "voided_by": "somebody-else"},
            headers=_auth(token),
        )
        assert resp.status_code == 200
        assert resp.json()["voided_by"] != "somebody-else"
        # The admin_client token carries username "merlin" and no email.
        assert resp.json()["voided_by"] == "merlin"

    def test_voiding_an_already_voided_transaction_is_409(self, admin_client):
        client, repo, token = admin_client
        txn = _sold_sale(repo)

        first = client.post(f"/admin/transactions/{txn.txn_id}/void",
                            json={"reason": "oops"}, headers=_auth(token))
        assert first.status_code == 200

        second = client.post(f"/admin/transactions/{txn.txn_id}/void",
                             json={"reason": "again"}, headers=_auth(token))
        assert second.status_code == 409

    def test_void_fails_loudly_when_the_item_has_moved_on(self, admin_client):
        """Never resurrect a card somebody else now owns."""
        client, repo, token = admin_client
        txn = _sold_sale(repo, item_id="item-9")
        # It went back to its consignor after the sale; no longer ``sold``.
        repo.put_inventory_item(_item("item-9", status="returned_to_consignor"))

        resp = client.post(f"/admin/transactions/{txn.txn_id}/void",
                           json={"reason": "oops"}, headers=_auth(token))
        assert resp.status_code == 409

        [stored] = [t for t in repo.list_transactions(txn.date, txn.date)
                    if t.txn_id == txn.txn_id]
        assert stored.voided_at is None
        assert repo.get_inventory_item("item-9").status == "returned_to_consignor"

    def test_void_appends_a_timeline_event_and_the_sale_survives(self, admin_client):
        """The timeline is a history, and history includes the mistake."""
        client, repo, token = admin_client
        txn = _sold_sale(repo)
        repo.put_timeline_event("item-1", {
            "item_id": "item-1", "txn_id": txn.txn_id, "type": "sale",
            "date": txn.date.isoformat(), "amount": "40.00",
            "payment_method": "cash",
        })

        resp = client.post(f"/admin/transactions/{txn.txn_id}/void",
                           json={"reason": "wrong card"}, headers=_auth(token))
        assert resp.status_code == 200

        events = repo.get_timeline_events("item-1")
        types = [e["type"] for e in events]
        assert "sale" in types, "the original sale event must survive"
        assert "voided" in types
        void_event = next(e for e in events if e["type"] == "voided")
        assert void_event["voided_txn_id"] == txn.txn_id
        assert void_event["void_reason"] == "wrong card"

    def test_void_marks_the_affected_show_snapshot_stale(self, admin_client):
        """Snapshots are point-in-time records; a void leaves them wrong."""
        client, repo, token = admin_client
        repo.put_show(Show(show_id="show-1", name="Portland", date=date.today()))
        txn = _sold_sale(repo, show_id="show-1")

        gen = client.post("/admin/shows/show-1/analytics/generate",
                          headers=_auth(token))
        assert gen.status_code == 200
        assert gen.json()["stale"] is False

        client.post(f"/admin/transactions/{txn.txn_id}/void",
                    json={"reason": "oops"}, headers=_auth(token))

        snap = client.get("/admin/shows/show-1/analytics", headers=_auth(token))
        assert snap.status_code == 200
        assert snap.json()["stale"] is True

    def test_voiding_a_purchase_is_refused_with_a_clear_400(self, admin_client):
        """Sales only in the first cut — see progress.md's Decisions table."""
        client, repo, token = admin_client
        repo.put_inventory_item(_item("item-2"))
        txn = _txn(TransactionType.PURCHASE, "item-2", date.today(), "200.00")
        repo.put_transaction(txn)

        resp = client.post(f"/admin/transactions/{txn.txn_id}/void",
                           json={"reason": "oops"}, headers=_auth(token))
        assert resp.status_code == 400
        assert "purchase" in resp.json()["detail"].lower()
        assert repo.get_inventory_item("item-2").status == "available"

    def test_unknown_txn_id_is_404(self, admin_client):
        """Hardened: a bare ``404`` also describes a route that does not exist,
        so this asserts the *detail* — otherwise it passes against unfixed code
        and proves nothing."""
        client, repo, token = admin_client
        resp = client.post("/admin/transactions/nope/void",
                           json={"reason": "oops"}, headers=_auth(token))
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Transaction not found"

    def test_reason_is_required(self, admin_client):
        client, repo, token = admin_client
        txn = _sold_sale(repo)
        resp = client.post(f"/admin/transactions/{txn.txn_id}/void",
                           json={"reason": "   "}, headers=_auth(token))
        assert resp.status_code == 422


# ===========================================================================
# POST /admin/transactions/{txn_id}/restore
# ===========================================================================

class TestRestoreTransaction:
    def test_restore_clears_the_fields_and_re_sells_the_item(self, admin_client):
        client, repo, token = admin_client
        txn = _sold_sale(repo)
        client.post(f"/admin/transactions/{txn.txn_id}/void",
                    json={"reason": "oops"}, headers=_auth(token))

        resp = client.post(f"/admin/transactions/{txn.txn_id}/restore",
                           headers=_auth(token))
        assert resp.status_code == 200
        body = resp.json()
        assert body["voided_at"] is None
        assert body["voided_by"] is None
        assert body["void_reason"] is None
        assert repo.get_inventory_item("item-1").status == "sold"

    def test_restoring_a_non_voided_transaction_is_409(self, admin_client):
        client, repo, token = admin_client
        txn = _sold_sale(repo)
        resp = client.post(f"/admin/transactions/{txn.txn_id}/restore",
                           headers=_auth(token))
        assert resp.status_code == 409

    def test_restore_fails_when_the_item_is_no_longer_available(self, admin_client):
        client, repo, token = admin_client
        txn = _sold_sale(repo)
        client.post(f"/admin/transactions/{txn.txn_id}/void",
                    json={"reason": "oops"}, headers=_auth(token))
        # Somebody else sold it in the meantime.
        repo.put_inventory_item(_item("item-1", status="sold"))

        resp = client.post(f"/admin/transactions/{txn.txn_id}/restore",
                           headers=_auth(token))
        assert resp.status_code == 409
        [stored] = [t for t in repo.list_transactions(txn.date, txn.date)
                    if t.txn_id == txn.txn_id]
        assert stored.voided_at is not None


# ===========================================================================
# Every reader, exhaustively. One test per row of the task doc's table.
# ===========================================================================

class TestAggregateReaders:
    def test_reader_summarize_transactions_excludes_a_voided_row(self):
        from merlins_collection.routers.admin.analytics import summarize_transactions

        live = _txn(TransactionType.SALE, "i1", date(2026, 8, 10), "40.00")
        dead = _txn(TransactionType.SALE, "i2", date(2026, 8, 10), "60.00")
        dead.voided_at = _VOIDED_AT

        totals = summarize_transactions([live, dead])
        assert totals["total_sold"] == Decimal("40.00")
        assert totals["items_sold_count"] == 1

    def test_reader_sell_through_rate_excludes_a_voided_row(self):
        from merlins_collection.routers.admin.analytics import sell_through_rate

        live = _txn(TransactionType.SALE, "i1", date(2026, 8, 10), "40.00")
        dead = _txn(TransactionType.SALE, "i2", date(2026, 8, 10), "60.00")
        dead.voided_at = _VOIDED_AT

        rate = sell_through_rate([live, dead], {"i1", "i2", "i3", "i4"})
        assert rate == Decimal("0.25")

    def test_reader_starting_inventory_excludes_a_voided_sale(self, dynamo_repo):
        from merlins_collection.routers.admin.analytics import starting_inventory

        day = date.today() - timedelta(days=1)
        dynamo_repo.put_inventory_item(
            _item("i1", status="sold", acquired=day - timedelta(days=30), cost="10.00")
        )
        txn = _txn(TransactionType.SALE, "i1", day, "40.00")
        txn.voided_at = _VOIDED_AT
        dynamo_repo.put_transaction(txn)

        ids, total = starting_inventory(dynamo_repo, day)
        assert "i1" not in ids, (
            "a sold item whose only sale was voided was not on hand at the "
            "start of the day"
        )
        assert total == Decimal("0")

    def test_reader_daily_analytics_excludes_a_voided_row(self, admin_client):
        client, repo, token = admin_client
        day = date.today()
        repo.put_transaction(_txn(TransactionType.SALE, "i1", day, "40.00"))
        dead = _txn(TransactionType.SALE, "i2", day, "60.00")
        dead.voided_at = _VOIDED_AT
        repo.put_transaction(dead)

        resp = client.get("/admin/analytics/daily",
                          params={"date": day.isoformat()}, headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["total_sold"] == "40.00"
        assert resp.json()["items_sold_count"] == 1

    def test_reader_list_analytics_dates_skips_an_all_voided_day(self, admin_client):
        client, repo, token = admin_client
        live_day = date.today()
        dead_day = date.today() - timedelta(days=2)
        repo.put_transaction(_txn(TransactionType.SALE, "i1", live_day, "40.00"))
        dead = _txn(TransactionType.SALE, "i2", dead_day, "60.00")
        dead.voided_at = _VOIDED_AT
        repo.put_transaction(dead)

        resp = client.get("/admin/analytics/dates", headers=_auth(token))
        assert resp.status_code == 200
        dates = resp.json()["dates"]
        assert live_day.isoformat() in dates
        assert dead_day.isoformat() not in dates

    def test_reader_show_snapshot_generator_excludes_a_voided_row(self, admin_client):
        client, repo, token = admin_client
        day = date.today()
        repo.put_show(Show(show_id="show-1", name="Portland", date=day))
        repo.put_transaction(_txn(TransactionType.SALE, "i1", day, "40.00",
                                  show_id="show-1"))
        dead = _txn(TransactionType.SALE, "i2", day, "60.00", show_id="show-1")
        dead.voided_at = _VOIDED_AT
        repo.put_transaction(dead)

        resp = client.post("/admin/shows/show-1/analytics/generate",
                           headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["total_sold"] == "40.00"
        assert resp.json()["items_sold_count"] == 1

    def test_reader_dashboard_today_panel_excludes_a_voided_row(self, admin_client):
        """The dashboard's Today tile reads ``GET /analytics/daily`` for
        ``todayLocal()`` — the same endpoint, so the figure it renders must move
        with the void. Named separately because the reader table names it
        separately: if the dashboard ever grows its own sum, this goes red."""
        client, repo, token = admin_client
        day = date.today()
        repo.put_transaction(_txn(TransactionType.SALE, "i1", day, "25.00"))
        dead = _txn(TransactionType.SALE, "i2", day, "500.00")
        dead.voided_at = _VOIDED_AT
        repo.put_transaction(dead)

        resp = client.get("/admin/analytics/daily",
                          params={"date": day.isoformat()}, headers=_auth(token))
        assert resp.json()["total_sold"] == "25.00"
        assert resp.json()["items_sold_count"] == 1

    def test_reader_transaction_archive_SHOWS_the_void(self, admin_client):
        """The archive is the one reader that must NOT filter. It shows what
        was written, and a void is a thing that was written."""
        client, repo, token = admin_client
        day = date.today()
        dead = _txn(TransactionType.SALE, "i2", day, "60.00")
        dead.voided_at = _VOIDED_AT
        dead.voided_by = "merlin"
        dead.void_reason = "wrong card"
        repo.put_transaction(dead)

        resp = client.get("/admin/transactions",
                          params={"start": day.isoformat(), "end": day.isoformat()},
                          headers=_auth(token))
        assert resp.status_code == 200
        [row] = resp.json()["items"]
        assert row["txn_id"] == dead.txn_id
        assert row["voided_at"] is not None
        assert row["voided_by"] == "merlin"
        assert row["void_reason"] == "wrong card"


# ===========================================================================
# The model
# ===========================================================================

class TestTransactionVoidFields:
    def test_void_fields_default_to_none_so_every_existing_row_validates(self):
        txn = Transaction.model_validate({
            "type": "sale", "item_id": "i1", "category": "raw",
            "date": "2026-08-10", "amount": "40.00", "payment_method": "cash",
        })
        assert txn.voided_at is None
        assert txn.voided_by is None
        assert txn.void_reason is None

    def test_void_reason_is_bounded_at_500_chars(self):
        with pytest.raises(Exception):
            Transaction.model_validate({
                "type": "sale", "item_id": "i1", "category": "raw",
                "date": "2026-08-10", "amount": "40.00", "payment_method": "cash",
                "void_reason": "x" * 501,
            })


# ===========================================================================
# The whole transaction, keyed on T10's ``batch_id``
#
# A five-card sale is ONE thing the operator did, so voiding it must be one
# thing too — and it must not be able to half-happen. This is the same failure
# class T0 fixed in the buy confirm, arriving through a different door.
# ===========================================================================

class TestVoidWholeTransaction:
    def _batch(self, repo, n=3, batch_id="sell-1", day=None):
        day = day or date.today()
        txns = []
        for i in range(n):
            item_id = f"batch-item-{i}"
            repo.put_inventory_item(_item(item_id, status="sold"))
            txn = _txn(TransactionType.SALE, item_id, day, "40.00",
                       batch_id=batch_id)
            repo.put_transaction(txn)
            txns.append(txn)
        return txns

    def test_voiding_a_batch_voids_every_leg_and_returns_every_card(self, admin_client):
        client, repo, token = admin_client
        txns = self._batch(repo, n=3)

        resp = client.post("/admin/transactions/batch/sell-1/void",
                           json={"reason": "wrong customer"}, headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["voided"] == 3

        for txn in txns:
            [stored] = [t for t in repo.list_transactions(txn.date, txn.date)
                        if t.txn_id == txn.txn_id]
            assert stored.voided_at is not None
            assert stored.void_reason == "wrong customer"
            assert repo.get_inventory_item(txn.item_id).status == "available"

    def test_one_bad_leg_writes_NOTHING(self, admin_client):
        """The partial-write rule: a batch void either happens or it does not."""
        client, repo, token = admin_client
        txns = self._batch(repo, n=3)
        # The middle card has moved on since — its status is no longer `sold`.
        repo.put_inventory_item(_item(txns[1].item_id, status="returned_to_consignor"))

        resp = client.post("/admin/transactions/batch/sell-1/void",
                           json={"reason": "wrong customer"}, headers=_auth(token))
        assert resp.status_code == 409

        for txn in txns:
            [stored] = [t for t in repo.list_transactions(txn.date, txn.date)
                        if t.txn_id == txn.txn_id]
            assert stored.voided_at is None, "no leg may be voided"
        assert repo.get_inventory_item(txns[0].item_id).status == "sold"
        assert repo.get_inventory_item(txns[2].item_id).status == "sold"

    def test_unknown_batch_id_is_404(self, admin_client):
        client, repo, token = admin_client
        resp = client.post("/admin/transactions/batch/nope/void",
                           json={"reason": "oops"}, headers=_auth(token))
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Transaction not found"

    def test_a_batch_containing_a_purchase_is_refused(self, admin_client):
        """A trade's legs share one batch_id and one of them is a PURCHASE."""
        client, repo, token = admin_client
        self._batch(repo, n=1, batch_id="trade-1")
        repo.put_inventory_item(_item("bought-1"))
        repo.put_transaction(_txn(TransactionType.PURCHASE, "bought-1",
                                  date.today(), "20.00", batch_id="trade-1"))

        resp = client.post("/admin/transactions/batch/trade-1/void",
                           json={"reason": "oops"}, headers=_auth(token))
        assert resp.status_code == 400
        assert "purchase" in resp.json()["detail"].lower()

    def test_restoring_a_batch_re_sells_every_card(self, admin_client):
        client, repo, token = admin_client
        txns = self._batch(repo, n=2)
        client.post("/admin/transactions/batch/sell-1/void",
                    json={"reason": "oops"}, headers=_auth(token))

        resp = client.post("/admin/transactions/batch/sell-1/restore",
                           headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["restored"] == 2
        for txn in txns:
            [stored] = [t for t in repo.list_transactions(txn.date, txn.date)
                        if t.txn_id == txn.txn_id]
            assert stored.voided_at is None
            assert repo.get_inventory_item(txn.item_id).status == "sold"

    def test_a_batch_bigger_than_the_atomic_limit_is_refused_not_chunked(
            self, admin_client):
        """Chunking would reintroduce the partial write it exists to prevent."""
        client, repo, token = admin_client
        self._batch(repo, n=51, batch_id="huge")

        resp = client.post("/admin/transactions/batch/huge/void",
                           json={"reason": "oops"}, headers=_auth(token))
        assert resp.status_code == 422
        assert "one at a time" in resp.json()["detail"].lower()
