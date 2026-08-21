"""Tests for the admin purchases router (``/admin/purchases/...``).

Covers full buy session lifecycle: create, add items, confirm, cancel.
"""

from datetime import date
from decimal import Decimal


from merlins_collection.models.business import ItemCategory
from merlins_collection.models.inventory import GradingCompany, ItemStatus


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

    def test_add_graded_item_persists_slab_fields(self, admin_client):
        client, repo, token = admin_client
        create = client.post("/admin/purchases", json={}, headers=_auth(token))
        buy_id = create.json()["buy_id"]

        resp = client.post(f"/admin/purchases/{buy_id}/items", json={
            "kind": "graded", "name": "Gengar VMAX", "buy_price": 900,
            "company": "PSA", "grade": 9.5, "cert_number": "89787279",
            "grade_label": "MINT 9.5", "card_id": "en:swsh8-271",
        }, headers=_auth(token))

        assert resp.status_code == 200
        item = resp.json()["items"][0]
        assert item["kind"] == "graded"
        assert item["company"] == "PSA"
        assert item["cert_number"] == "89787279"
        assert item["grade_label"] == "MINT 9.5"

    def test_add_item_defaults_to_raw_when_kind_absent(self, admin_client):
        client, repo, token = admin_client
        create = client.post("/admin/purchases", json={}, headers=_auth(token))
        buy_id = create.json()["buy_id"]

        resp = client.post(f"/admin/purchases/{buy_id}/items", json={
            "name": "Pikachu", "buy_price": "5.00",
        }, headers=_auth(token))

        assert resp.status_code == 200
        assert resp.json()["items"][0]["kind"] == "raw"

    def test_graded_item_without_cert_is_rejected_and_session_survives(self, admin_client):
        client, repo, token = admin_client
        create = client.post("/admin/purchases", json={}, headers=_auth(token))
        buy_id = create.json()["buy_id"]
        client.post(f"/admin/purchases/{buy_id}/items", json={
            "name": "Pikachu", "buy_price": "5.00",
        }, headers=_auth(token))

        resp = client.post(f"/admin/purchases/{buy_id}/items", json={
            "kind": "graded", "name": "Gengar VMAX", "buy_price": 900,
            "company": "PSA", "grade": 9.5,
        }, headers=_auth(token))

        assert resp.status_code == 422
        assert "cert_number" in resp.json()["detail"]
        # The previously-added item must survive a rejected sibling: losing the
        # staged batch is the failure the batch design exists to prevent.
        session = client.get(f"/admin/purchases/{buy_id}", headers=_auth(token)).json()
        assert len(session["items"]) == 1


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


class TestConfirmGraded:
    def _graded_session(self, client, token, **overrides):
        create = client.post("/admin/purchases", json={}, headers=_auth(token))
        buy_id = create.json()["buy_id"]
        payload = {
            "kind": "graded", "name": "Gengar VMAX", "buy_price": 900.50,
            "company": "PSA", "grade": 9.5, "cert_number": "89787279",
            "card_id": "en:swsh8-271", "location": "toploader",
        }
        payload.update(overrides)
        client.post(f"/admin/purchases/{buy_id}/items", json=payload,
                    headers=_auth(token))
        return buy_id

    def test_confirm_creates_graded_inventory_item(self, admin_client):
        client, repo, token = admin_client
        buy_id = self._graded_session(client, token)

        resp = client.post(f"/admin/purchases/{buy_id}/confirm", headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["items_created"] == 1

        items = repo.list_inventory()
        item = next(i for i in items if getattr(i, "cert_number", None) == "89787279")
        assert item.kind == "graded"
        assert item.company.value == "PSA"
        assert item.grade == Decimal("9.5")
        # Money must survive a JSON float exactly -- not 900.4999999...
        assert item.cost_basis == Decimal("900.50")

    def test_graded_transaction_uses_graded_category(self, admin_client):
        client, repo, token = admin_client
        buy_id = self._graded_session(client, token)
        client.post(f"/admin/purchases/{buy_id}/confirm", headers=_auth(token))

        # `list_transactions` takes a date RANGE -- there is no no-arg form.
        today = date.today()
        txns = repo.list_transactions(today, today)
        assert txns[0].category == ItemCategory.GRADED

    def test_cert_pointer_row_exists_after_confirm(self, admin_client):
        client, repo, token = admin_client
        buy_id = self._graded_session(client, token)
        client.post(f"/admin/purchases/{buy_id}/confirm", headers=_auth(token))

        assert repo.get_item_id_by_cert(GradingCompany.PSA, "89787279") is not None

    def test_catalog_matched_slab_is_not_flagged_for_review(self, admin_client):
        """The core of the manual-first pivot: a hand-typed slab that resolved to
        a catalog card is NOT review-flagged. Flagging every slab would make
        Triage noise, and `cert_lookup_failed` means automation tried and failed
        -- a human typing a slab in is the opposite of that."""
        client, repo, token = admin_client
        buy_id = self._graded_session(client, token)
        client.post(f"/admin/purchases/{buy_id}/confirm", headers=_auth(token))

        item = next(i for i in repo.list_inventory()
                    if getattr(i, "cert_number", None) == "89787279")
        assert item.needs_review is False
        assert item.review_reason is None

    def test_slab_without_catalog_match_is_flagged_no_catalog_link(self, admin_client):
        client, repo, token = admin_client
        buy_id = self._graded_session(client, token, card_id=None)
        client.post(f"/admin/purchases/{buy_id}/confirm", headers=_auth(token))

        item = next(i for i in repo.list_inventory()
                    if getattr(i, "cert_number", None) == "89787279")
        assert item.needs_review is True
        assert item.review_reason == "no_catalog_link"

    def test_raw_and_graded_in_one_session_both_confirm(self, admin_client):
        client, repo, token = admin_client
        buy_id = self._graded_session(client, token)
        client.post(f"/admin/purchases/{buy_id}/items", json={
            "name": "Pikachu", "buy_price": "5.00",
        }, headers=_auth(token))

        resp = client.post(f"/admin/purchases/{buy_id}/confirm", headers=_auth(token))
        assert resp.json()["items_created"] == 2
        assert resp.json()["total_cost"] == "905.50"
        kinds = sorted(i.kind for i in repo.list_inventory())
        assert kinds == ["graded", "raw"]


# ===========================================================================
# RFC 0010 T0: a bad money value is rejected at ADD, and a batch never
# half-commits.
#
# The failure this covers: `Number("1,300")` is NaN, which JSON-serialises to
# `null`, which `add_buy_item` accepted with a 200 because it only checked
# `"buy_price" not in body`. `confirm_buy_session` then hit
# `Decimal(str(None))` on row 3 of a 5-row batch -- after rows 1-2 already had
# real inventory items, real PURCHASE transactions and real timeline events
# written, with no rollback and the session still `draft`. The UI said
# "Nothing was created; the batch is intact", which was false, and pressing
# Commit again duplicated rows 1-2.
# ===========================================================================

class TestAddBuyItemMoneyGuard:
    def _session(self, client, token) -> str:
        return client.post("/admin/purchases", json={}, headers=_auth(token)).json()["buy_id"]

    def test_null_buy_price_is_rejected_and_nothing_is_staged(self, admin_client):
        client, repo, token = admin_client
        buy_id = self._session(client, token)

        resp = client.post(f"/admin/purchases/{buy_id}/items", json={
            "name": "Gengar VMAX", "buy_price": None,
        }, headers=_auth(token))

        assert resp.status_code == 422
        assert "buy_price" in resp.json()["detail"]
        session = client.get(f"/admin/purchases/{buy_id}", headers=_auth(token)).json()
        assert session["items"] == []

    def test_absent_buy_price_is_rejected(self, admin_client):
        client, repo, token = admin_client
        buy_id = self._session(client, token)

        resp = client.post(f"/admin/purchases/{buy_id}/items", json={
            "name": "Gengar VMAX",
        }, headers=_auth(token))
        assert resp.status_code == 422

    def test_unreadable_buy_price_string_is_rejected(self, admin_client):
        """The backend is the last line, not a mirror of one form's habits --
        MCP and curl are real clients and can send anything."""
        client, repo, token = admin_client
        buy_id = self._session(client, token)

        resp = client.post(f"/admin/purchases/{buy_id}/items", json={
            "name": "Gengar VMAX", "buy_price": "1,300",
        }, headers=_auth(token))
        assert resp.status_code == 422

    def test_non_finite_buy_price_is_rejected(self, admin_client):
        """`Decimal("NaN")` and `Decimal("Infinity")` both PARSE. A try/except
        around the coercion is not enough on its own."""
        client, repo, token = admin_client
        buy_id = self._session(client, token)

        for value in ("NaN", "Infinity", "-Infinity"):
            resp = client.post(f"/admin/purchases/{buy_id}/items", json={
                "name": "Gengar VMAX", "buy_price": value,
            }, headers=_auth(token))
            assert resp.status_code == 422, value

    def test_numeric_string_buy_price_is_accepted(self, admin_client):
        client, repo, token = admin_client
        buy_id = self._session(client, token)

        resp = client.post(f"/admin/purchases/{buy_id}/items", json={
            "name": "Gengar VMAX", "buy_price": "1300",
        }, headers=_auth(token))
        assert resp.status_code == 200

    def test_json_number_buy_price_is_accepted(self, admin_client):
        client, repo, token = admin_client
        buy_id = self._session(client, token)

        resp = client.post(f"/admin/purchases/{buy_id}/items", json={
            "name": "Gengar VMAX", "buy_price": 1300,
        }, headers=_auth(token))
        assert resp.status_code == 200


class TestConfirmNeverHalfWrites:
    """Confirm validates the WHOLE batch before the first write.

    These seed the session through the repo rather than through
    ``POST /items``: the add-time guard above now blocks a bad row from being
    staged that way, and a session written by an older build (or another
    client) is exactly the case this pre-validation exists for.
    """

    def _seed(self, repo, items: list[dict]) -> str:
        from datetime import datetime, timezone

        from merlins_collection.models.inventory import new_ulid

        buy_id = new_ulid()
        repo.put_buy_session({
            "buy_id": buy_id,
            "status": "draft",
            "show_id": None,
            "created_at": datetime.now(tz=timezone.utc).isoformat(),
            "created_by": "admin",
            "items": items,
            "total_cost": None,
            "payment_method": "cash",
            "counterparty": None,
            "notes": None,
        })
        return buy_id

    @staticmethod
    def _row(n: int, **over) -> dict:
        row = {
            "card_id": "en:base1-4", "name": f"Card {n}", "set_name": None,
            "number": None, "condition": "NM", "condition_modifier": None,
            "finish": "normal", "language": "EN", "market_value": None,
            "buy_price": "10.00", "buy_pct": None, "location": "toploader",
            "manual_entry": False, "kind": "raw", "company": None,
            "grade": None, "cert_number": None, "grade_label": None,
            "cert_verified_at": None, "cert_image_url": None,
            "price_source_id": None,
        }
        row.update(over)
        return row

    def test_bad_row_three_writes_nothing_at_all(self, admin_client):
        """THE partial-write test. Five rows, row 3 unusable: zero inventory
        items, zero transactions, and a 422 that names the row."""
        client, repo, token = admin_client
        buy_id = self._seed(repo, [
            self._row(1), self._row(2), self._row(3, buy_price=None),
            self._row(4), self._row(5),
        ])

        resp = client.post(f"/admin/purchases/{buy_id}/confirm", headers=_auth(token))

        assert resp.status_code == 422
        # 1-based for a human standing at the table, matching the staging table.
        assert "3" in str(resp.json()["detail"])
        assert repo.list_inventory() == []
        today = date.today()
        assert repo.list_transactions(today, today) == []

    def test_rejected_batch_stays_draft_with_its_items_intact(self, admin_client):
        client, repo, token = admin_client
        buy_id = self._seed(repo, [
            self._row(1), self._row(2), self._row(3, buy_price=None),
        ])

        client.post(f"/admin/purchases/{buy_id}/confirm", headers=_auth(token))

        session = client.get(f"/admin/purchases/{buy_id}", headers=_auth(token)).json()
        assert session["status"] == "draft"
        assert len(session["items"]) == 3

    def test_corrected_retry_commits_the_whole_batch(self, admin_client):
        client, repo, token = admin_client
        buy_id = self._seed(repo, [
            self._row(1), self._row(2), self._row(3, buy_price=None),
        ])
        client.post(f"/admin/purchases/{buy_id}/confirm", headers=_auth(token))

        # The operator fixes row 3 and presses Commit again.
        client.delete(f"/admin/purchases/{buy_id}/items/2", headers=_auth(token))
        client.post(f"/admin/purchases/{buy_id}/items", json={
            "name": "Card 3", "buy_price": 1300, "card_id": "en:base1-4",
        }, headers=_auth(token))

        resp = client.post(f"/admin/purchases/{buy_id}/confirm", headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["items_created"] == 3
        assert resp.json()["total_cost"] == "1320.00"
        assert len(repo.list_inventory()) == 3

    def test_a_fully_valid_batch_still_commits_all_five(self, admin_client):
        """The regression gate: a batch that commits today must still commit."""
        client, repo, token = admin_client
        buy_id = self._seed(repo, [self._row(n) for n in range(1, 6)])

        resp = client.post(f"/admin/purchases/{buy_id}/confirm", headers=_auth(token))

        assert resp.status_code == 200
        assert resp.json()["items_created"] == 5
        assert resp.json()["total_cost"] == "50.00"
        assert len(repo.list_inventory()) == 5

    def test_other_numeric_fields_are_pre_validated_too(self, admin_client):
        """`buy_price` was the trigger, not the class. Every numeric field on a
        staged row is coerced before the first write, or the next one to arrive
        malformed reproduces the same partial commit."""
        client, repo, token = admin_client

        for field, bad in (
            ("market_value", "1,300"),
            ("buy_pct", "seventy"),
        ):
            buy_id = self._seed(repo, [self._row(1), self._row(2, **{field: bad})])
            resp = client.post(f"/admin/purchases/{buy_id}/confirm", headers=_auth(token))
            assert resp.status_code == 422, field
            assert repo.list_inventory() == [], field

    def test_a_bad_non_numeric_field_also_writes_nothing(self, admin_client):
        """`buy_price` was the door, not the room. A row that fails pydantic —
        a bad condition, company or status — reproduced the identical partial
        commit through `InventoryItemAdapter` inside the write loop. Confirm
        builds every row before it writes any, so this fails with nothing
        written too."""
        client, repo, token = admin_client
        buy_id = self._seed(repo, [
            self._row(1), self._row(2, condition="MINTISH"), self._row(3),
        ])

        resp = client.post(f"/admin/purchases/{buy_id}/confirm", headers=_auth(token))

        assert resp.status_code == 422
        assert "2" in str(resp.json()["detail"])
        assert repo.list_inventory() == []
        today = date.today()
        assert repo.list_transactions(today, today) == []

    def test_a_graded_row_with_an_unusable_grade_writes_nothing(self, admin_client):
        client, repo, token = admin_client
        buy_id = self._seed(repo, [
            self._row(1),
            self._row(2, kind="graded", company="PSA", grade="MINT",
                      cert_number="89787279"),
        ])

        resp = client.post(f"/admin/purchases/{buy_id}/confirm", headers=_auth(token))

        assert resp.status_code == 422
        assert repo.list_inventory() == []


# ===========================================================================
# RFC 0010 T10 — one real transaction renders as one line
# ===========================================================================

class TestPurchaseBatchId:
    """A five-card purchase is five ledger rows sharing only a date and a
    payment method. ``batch_id`` is the key that makes them one transaction."""

    def _buy_two(self, client, token):
        buy_id = client.post(
            "/admin/purchases", json={"payment_method": "cash"}, headers=_auth(token)
        ).json()["buy_id"]
        for name, price in (("Pikachu #25", "15.00"), ("Charizard #4", "80.00")):
            client.post(f"/admin/purchases/{buy_id}/items", json={
                "name": name, "buy_price": price, "condition": "NM",
            }, headers=_auth(token))
        client.post(f"/admin/purchases/{buy_id}/confirm", headers=_auth(token))
        return buy_id

    def test_confirm_stamps_every_row_with_the_buy_id(self, admin_client):
        client, repo, token = admin_client
        buy_id = self._buy_two(client, token)

        txns = repo.list_transactions(date(2000, 1, 1), date(2100, 1, 1))
        assert len(txns) == 2
        assert {t.batch_id for t in txns} == {buy_id}

    def test_two_sessions_produce_different_batch_ids(self, admin_client):
        client, repo, token = admin_client
        first = self._buy_two(client, token)
        second = self._buy_two(client, token)
        assert first != second

        txns = repo.list_transactions(date(2000, 1, 1), date(2100, 1, 1))
        assert len(txns) == 4
        assert {t.batch_id for t in txns} == {first, second}

    def test_batch_id_survives_the_dynamodb_round_trip(self, admin_client):
        # These routers persist raw request JSON in places, and `_serialize` is
        # the only thing that coerces a type DynamoDB rejects. A plain string is
        # safe, but "it will be fine" is what the float landmine was too.
        client, repo, token = admin_client
        buy_id = self._buy_two(client, token)

        reloaded = repo.list_transactions(date(2000, 1, 1), date(2100, 1, 1))
        assert all(isinstance(t.batch_id, str) for t in reloaded)
        assert all(t.batch_id == buy_id for t in reloaded)

    def test_a_transaction_with_no_batch_id_still_validates(self):
        # The backward-compatibility gate. Every historical row predates this
        # field and is deliberately NOT backfilled.
        from merlins_collection.models.business import Transaction

        txn = Transaction.model_validate({
            "txn_id": "txn-legacy",
            "type": "sale",
            "item_id": "item-1",
            "category": "raw",
            "date": "2026-01-01",
            "amount": "40.00",
            "payment_method": "cash",
        })
        assert txn.batch_id is None

    def test_transactions_archive_exposes_batch_id(self, admin_client):
        client, repo, token = admin_client
        buy_id = self._buy_two(client, token)

        resp = client.get("/admin/transactions", params={
            "start": "2000-01-01", "end": "2100-01-01",
        }, headers=_auth(token))
        assert resp.status_code == 200
        rows = resp.json()["items"]
        assert len(rows) == 2
        assert all(r["batch_id"] == buy_id for r in rows)


class TestConfirmReturnsCreatedItemIds:
    """RFC 0010 T12 — the confirm response has to say WHAT it created.

    Slab intake prices the batch immediately after committing, scoped to the
    items it just made. Without the ids the only alternatives are a second
    pricing path or an unscoped refresh that spends the whole day's 50-lookup
    budget re-checking the shelf.
    """

    def test_confirm_reports_the_ids_it_created(self, admin_client):
        client, repo, token = admin_client
        session = client.post("/admin/purchases", json={},
                              headers=_auth(token)).json()
        buy_id = session["buy_id"]
        for cert in ("1001", "1002"):
            client.post(f"/admin/purchases/{buy_id}/items", json={
                "kind": "graded", "name": "Gengar VMAX", "company": "PSA",
                "grade": 9.5, "cert_number": cert, "buy_price": 100,
                "location": "toploader",
            }, headers=_auth(token))

        resp = client.post(f"/admin/purchases/{buy_id}/confirm", json={},
                           headers=_auth(token))
        assert resp.status_code == 200
        body = resp.json()
        assert body["items_created"] == 2
        assert len(body["item_ids"]) == 2
        for item_id in body["item_ids"]:
            assert repo.get_inventory_item(item_id) is not None
