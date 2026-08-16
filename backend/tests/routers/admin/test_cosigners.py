"""Tests for the admin cosigners router (``/admin/cosigners/...``).

A2: Cosigner Management — CRUD + asset linking + analytics.

RFC 0010 T2 adds three groups below, all driven by one owner report: *"editing
one of the consignors in this case harry creates a duplicate harry with whatever
you edited as different … Also I cant delete the extra name from this menu and
when i tried to it set the new 85% one to 'Sold'"*.

``TestCosignerStorageIsUpsert`` pins the STORAGE shape, the same way
``test_shows.py`` does for shows — ``put_consignor`` writes
``SK=CONSIGNOR#{id}``, suffixed with the import generation while an import is
running. That suffix survives ``finalize_import``, and an admin edit runs with no
generation, so "write the consignor again" is only an upsert when the generation
has not moved. The one-time import only ever created, so it never hit this;
``PATCH`` does, on the most ordinary edit there is.
"""

from datetime import date
from decimal import Decimal

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

# ``admin_client`` now comes from ``conftest.py`` in this package; the identical
# copy that used to sit here was one of sixteen.


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _create(client, token, **overrides) -> dict:
    """POST a cosigner and return the created body (asserting it worked)."""
    body = {"name": "Alice"}
    body.update(overrides)
    resp = client.post("/admin/cosigners", json=body, headers=_auth(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _listing(client, token, *, include_archived=None, sort=None) -> list[dict]:
    params = {}
    if include_archived is not None:
        params["include_archived"] = include_archived
    if sort is not None:
        params["sort"] = sort
    resp = client.get("/admin/cosigners", params=params, headers=_auth(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _rows_for(repo, consignor_id: str) -> list[Consignor]:
    return [c for c in repo.list_consignors() if c.consignor_id == consignor_id]


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
        # Rewritten for RFC 0010 T2: was ``data["active"] is True``. Same fact,
        # under the name CLAUDE.md's archiving contract already established.
        assert data["archived"] is False
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


class TestCosignerListSort:
    """RFC 0013 T4d — ``?sort=`` on ``GET /admin/cosigners``, via
    ``services.consignors_sort``."""

    def test_sort_by_name_ascending(self, admin_client):
        client, _repo, token = admin_client
        _create(client, token, name="Beaverton Cards")
        _create(client, token, name="Albany Cards")

        names = [c["name"] for c in _listing(client, token, sort="name_asc")]
        assert names == ["Albany Cards", "Beaverton Cards"]

    def test_sort_by_payout_percent_descending(self, admin_client):
        client, _repo, token = admin_client
        _create(client, token, name="Low", payout_percent="30")
        _create(client, token, name="High", payout_percent="70")

        names = [
            c["name"] for c in _listing(client, token, sort="payout_percent_desc")
        ]
        assert names == ["High", "Low"]

    def test_unknown_sort_field_is_422(self, admin_client):
        client, _repo, token = admin_client
        _create(client, token)

        resp = client.get(
            "/admin/cosigners", params={"sort": "created_at_asc"}, headers=_auth(token)
        )
        assert resp.status_code == 422

    def test_unknown_direction_is_422(self, admin_client):
        client, _repo, token = admin_client
        _create(client, token)

        resp = client.get(
            "/admin/cosigners", params={"sort": "name_sideways"}, headers=_auth(token)
        )
        assert resp.status_code == 422


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
    def test_delete_archives(self, admin_client):
        """DELETE archives the cosigner rather than hard deleting.

        Rewritten for RFC 0010 T2: this asserted ``active is False``, and
        ``active`` no longer exists as a writable field — a second boolean
        meaning what ``archived`` already means is how the next reader
        introduces a bug. The behaviour it guards (DELETE never destroys) is
        unchanged and is asserted harder in ``TestArchiveCosigner``.
        """
        client, repo, token = admin_client
        create = client.post("/admin/cosigners", json={"name": "Alice"}, headers=_auth(token))
        cid = create.json()["consignor_id"]

        resp = client.delete(f"/admin/cosigners/{cid}", headers=_auth(token))
        assert resp.status_code == 200

        get_resp = client.get(f"/admin/cosigners/{cid}", headers=_auth(token))
        assert get_resp.json()["archived"] is True


# ===========================================================================
# Storage shape — editing must not fork the consignor into two rows
# ===========================================================================

class TestCosignerStorageIsUpsert:
    """The owner's bug. ``put_consignor`` generation-scopes its SK, so a
    consignor the spreadsheet import wrote lives at ``CONSIGNOR#{id}#{gen}``
    while an admin edit — which runs with no generation — writes
    ``CONSIGNOR#{id}``. A different sort key in the same partition: the row is
    not updated, a second one appears.

    ``put_show`` documents and fixes this exact pattern (RFC 0008 T7). The
    consignor id is NOT the fork axis — ``import_consignments`` assigns a
    deterministic id, so re-importing Harry re-uses Harry's id. Only the
    generation moves.
    """

    def test_editing_an_imported_cosigner_does_not_duplicate_it(self, admin_client):
        client, repo, token = admin_client

        repo.set_import_generation("gen-1")
        repo.put_consignor(Consignor(consignor_id="harry-1", name="Harry",
                                     payout_percent=Decimal("70")))
        repo.set_import_generation(None)

        resp = client.patch("/admin/cosigners/harry-1",
                            json={"payout_percent": "85"}, headers=_auth(token))
        assert resp.status_code == 200, resp.text

        rows = _rows_for(repo, "harry-1")
        assert len(rows) == 1, f"editing an imported cosigner left {len(rows)} rows"

    def test_the_surviving_row_carries_the_edited_values(self, admin_client):
        client, repo, token = admin_client

        repo.set_import_generation("gen-1")
        repo.put_consignor(Consignor(consignor_id="harry-1", name="Harry",
                                     payout_percent=Decimal("70")))
        repo.set_import_generation(None)

        client.patch("/admin/cosigners/harry-1",
                     json={"payout_percent": "85", "name": "Harry Potter"},
                     headers=_auth(token))

        rows = _rows_for(repo, "harry-1")
        assert len(rows) == 1
        assert rows[0].payout_percent == Decimal("85")
        assert rows[0].name == "Harry Potter"

    def test_import_generations_still_coexist(self, admin_client):
        """The sweep must NOT reach across generations: load-then-swap relies on
        the prior generation's copy surviving until ``finalize_import`` decides
        commit or rollback (dynamodb.py BLOCKING-1b)."""
        _client, repo, _token = admin_client

        repo.set_import_generation("gen-1")
        repo.put_consignor(Consignor(consignor_id="dual-1", name="Gen One"))
        repo.set_import_generation("gen-2")
        repo.put_consignor(Consignor(consignor_id="dual-1", name="Gen Two"))
        repo.set_import_generation(None)

        assert len(_rows_for(repo, "dual-1")) == 2, \
            "the prior generation's copy must survive the load phase"

    def test_the_list_shows_one_entry_per_cosigner_after_an_edit(self, admin_client):
        """The symptom the owner actually saw: two Harrys in the menu."""
        client, repo, token = admin_client

        repo.set_import_generation("gen-1")
        repo.put_consignor(Consignor(consignor_id="harry-1", name="Harry"))
        repo.set_import_generation(None)

        client.patch("/admin/cosigners/harry-1",
                     json={"payout_percent": "85"}, headers=_auth(token))

        listing = _listing(client, token)
        assert [c["consignor_id"] for c in listing].count("harry-1") == 1


# ===========================================================================
# Duplicate-name guard (409) — the owner asked for this explicitly
# ===========================================================================

class TestCosignerNameGuard:
    def test_creating_a_cosigner_with_an_existing_name_is_rejected(self, admin_client):
        client, _repo, token = admin_client
        _create(client, token, name="Harry")

        resp = client.post("/admin/cosigners", json={"name": "Harry"},
                           headers=_auth(token))
        assert resp.status_code == 409, resp.text
        assert "Harry" in resp.json()["detail"]

    def test_the_match_ignores_case_and_surrounding_whitespace(self, admin_client):
        client, _repo, token = admin_client
        _create(client, token, name="Harry")

        resp = client.post("/admin/cosigners", json={"name": "  harry "},
                           headers=_auth(token))
        assert resp.status_code == 409, resp.text

    def test_renaming_onto_another_cosigner_is_rejected(self, admin_client):
        client, _repo, token = admin_client
        _create(client, token, name="Harry")
        bob = _create(client, token, name="Bob")

        resp = client.patch(f"/admin/cosigners/{bob['consignor_id']}",
                            json={"name": "Harry"}, headers=_auth(token))
        assert resp.status_code == 409, resp.text

    def test_a_patch_that_does_not_move_the_name_is_allowed(self, admin_client):
        """Scoped to *another* consignor, so re-saving Harry as "Harry" — or a
        PATCH that never touches the name — is not an error."""
        client, _repo, token = admin_client
        harry = _create(client, token, name="Harry")

        untouched = client.patch(f"/admin/cosigners/{harry['consignor_id']}",
                                 json={"payout_percent": "85"}, headers=_auth(token))
        assert untouched.status_code == 200, untouched.text

        resaved = client.patch(f"/admin/cosigners/{harry['consignor_id']}",
                               json={"name": "Harry"}, headers=_auth(token))
        assert resaved.status_code == 200, resaved.text

    def test_an_archived_cosigner_still_counts_as_a_collision(self, admin_client):
        """Otherwise two live rows appear the moment it is unarchived."""
        client, _repo, token = admin_client
        harry = _create(client, token, name="Harry")
        client.delete(f"/admin/cosigners/{harry['consignor_id']}", headers=_auth(token))

        resp = client.post("/admin/cosigners", json={"name": "Harry"},
                           headers=_auth(token))
        assert resp.status_code == 409, resp.text


# ===========================================================================
# Archive / unarchive — /admin/shows is the reference implementation
# ===========================================================================

class TestArchiveCosigner:
    """Owner decision, 2026-08-10: *"If a cosignor is deleted, then it is okay to
    archive them, but those cosignors should be hidden by default, and their
    value should be displayed as archived instead of sold."*

    Nothing is ever destroyed, so there is no hard-delete route and — exactly as
    for shows — no 409 in-use guard: a consignor with real consignment history
    archives like any other, and nothing dangles because nothing is removed.
    """

    def test_archive_sets_the_flag_without_destroying_the_row(self, admin_client):
        client, repo, token = admin_client
        harry = _create(client, token, name="Harry")

        resp = client.delete(f"/admin/cosigners/{harry['consignor_id']}",
                             headers=_auth(token))

        assert resp.status_code == 200, resp.text
        stored = repo.get_consignor(harry["consignor_id"])
        assert stored is not None, "archive must never delete the consignor"
        assert stored.archived is True

    def test_archived_cosigners_are_hidden_from_the_default_listing(self, admin_client):
        client, _repo, token = admin_client
        harry = _create(client, token, name="Harry")
        bob = _create(client, token, name="Bob")
        client.delete(f"/admin/cosigners/{harry['consignor_id']}", headers=_auth(token))

        ids = [c["consignor_id"] for c in _listing(client, token)]
        assert harry["consignor_id"] not in ids
        assert bob["consignor_id"] in ids

    def test_include_archived_brings_them_back(self, admin_client):
        client, _repo, token = admin_client
        harry = _create(client, token, name="Harry")
        client.delete(f"/admin/cosigners/{harry['consignor_id']}", headers=_auth(token))

        listing = _listing(client, token, include_archived=True)
        entry = next(c for c in listing if c["consignor_id"] == harry["consignor_id"])
        assert entry["archived"] is True

    def test_unarchive_returns_it_to_the_default_listing(self, admin_client):
        client, _repo, token = admin_client
        harry = _create(client, token, name="Harry")
        client.delete(f"/admin/cosigners/{harry['consignor_id']}", headers=_auth(token))

        resp = client.post(f"/admin/cosigners/{harry['consignor_id']}/unarchive",
                           headers=_auth(token))
        assert resp.status_code == 200, resp.text

        ids = [c["consignor_id"] for c in _listing(client, token)]
        assert harry["consignor_id"] in ids

    def test_a_legacy_row_with_active_false_reads_as_archived(self, admin_client):
        """THE PRODUCTION-DATA GATE. The owner has already soft-deleted a Harry,
        so at least one live row carries ``active: False`` and no ``archived``
        attribute. It must render as archived, not as active and not as a 500."""
        client, repo, token = admin_client
        repo._table.put_item(Item={
            "PK": "CONSIGNORLIST",
            "SK": "CONSIGNOR#legacy-harry",
            "entity": "consignor",
            "consignor_id": "legacy-harry",
            "name": "Harry",
            "payout_percent": "85",
            "active": False,
        })

        assert repo.get_consignor("legacy-harry").archived is True
        assert "legacy-harry" not in [c["consignor_id"] for c in _listing(client, token)]
        entry = next(c for c in _listing(client, token, include_archived=True)
                     if c["consignor_id"] == "legacy-harry")
        assert entry["archived"] is True

    def test_archiving_a_cosigner_with_linked_inventory_succeeds(self, admin_client):
        """No in-use guard, by design — shows deliberately have none either."""
        client, repo, token = admin_client
        harry = _create(client, token, name="Harry")
        repo.put_inventory_item(_raw(item_id="item-1", consignment=ConsignmentTerms(
            consignor_id=harry["consignor_id"], split_percent=Decimal("0.5"))))

        resp = client.delete(f"/admin/cosigners/{harry['consignor_id']}",
                             headers=_auth(token))
        assert resp.status_code == 200, resp.text
        assert repo.get_inventory_item("item-1").consignment is not None


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


class TestCosignerLinkErrors:
    def test_link_reports_failed_item_ids(self, admin_client):
        client, repo, token = admin_client
        cosigner_resp = client.post("/admin/cosigners", json={"name": "Alice"}, headers=_auth(token))
        consignor_id = cosigner_resp.json()["consignor_id"]
        repo.put_inventory_item(_raw(item_id="item-1"))

        resp = client.post(
            f"/admin/cosigners/{consignor_id}/link",
            json={"item_ids": ["item-1", "does-not-exist"]},
            headers=_auth(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["linked"] == 1
        assert data["failed_item_ids"] == ["does-not-exist"]

    def test_link_non_numeric_split_percent_is_422(self, admin_client):
        """A garbage split_percent must 422, never propagate to an uncaught 500."""
        client, repo, token = admin_client
        cosigner_resp = client.post("/admin/cosigners", json={"name": "Alice"}, headers=_auth(token))
        consignor_id = cosigner_resp.json()["consignor_id"]
        repo.put_inventory_item(_raw(item_id="item-1"))

        resp = client.post(
            f"/admin/cosigners/{consignor_id}/link",
            json={"item_ids": ["item-1"], "split_percent": "not-a-number"},
            headers=_auth(token),
        )
        assert resp.status_code == 422

    def test_link_out_of_range_split_percent_is_422(self, admin_client):
        """split_percent is stored as a 0-1 fraction; 20 (a raw percent, not /100'd) must 422."""
        client, repo, token = admin_client
        cosigner_resp = client.post("/admin/cosigners", json={"name": "Alice"}, headers=_auth(token))
        consignor_id = cosigner_resp.json()["consignor_id"]
        repo.put_inventory_item(_raw(item_id="item-1"))

        resp = client.post(
            f"/admin/cosigners/{consignor_id}/link",
            json={"item_ids": ["item-1"], "split_percent": "20"},
            headers=_auth(token),
        )
        assert resp.status_code == 422


class TestCosignerUnlink:
    def test_unlink_clears_consignment(self, admin_client):
        client, repo, token = admin_client
        cosigner_resp = client.post("/admin/cosigners", json={"name": "Alice"}, headers=_auth(token))
        consignor_id = cosigner_resp.json()["consignor_id"]
        repo.put_inventory_item(_raw(
            item_id="item-1",
            consignment=ConsignmentTerms(consignor_id=consignor_id, split_percent=Decimal("0.5")),
        ))

        resp = client.delete(
            f"/admin/cosigners/{consignor_id}/assets/item-1",
            headers=_auth(token),
        )
        assert resp.status_code == 200
        assert repo.get_inventory_item("item-1").consignment is None

    def test_unlink_nonexistent_item_returns_404(self, admin_client):
        client, repo, token = admin_client
        cosigner_resp = client.post("/admin/cosigners", json={"name": "Alice"}, headers=_auth(token))
        consignor_id = cosigner_resp.json()["consignor_id"]

        resp = client.delete(
            f"/admin/cosigners/{consignor_id}/assets/no-such-item",
            headers=_auth(token),
        )
        assert resp.status_code == 404

    def test_unlink_item_linked_to_a_different_consignor_returns_404(self, admin_client):
        client, repo, token = admin_client
        alice = client.post("/admin/cosigners", json={"name": "Alice"}, headers=_auth(token)).json()
        bob = client.post("/admin/cosigners", json={"name": "Bob"}, headers=_auth(token)).json()
        repo.put_inventory_item(_raw(
            item_id="item-1",
            consignment=ConsignmentTerms(consignor_id=alice["consignor_id"], split_percent=Decimal("0.5")),
        ))

        resp = client.delete(
            f"/admin/cosigners/{bob['consignor_id']}/assets/item-1",
            headers=_auth(token),
        )
        assert resp.status_code == 404
        # Alice's link must be untouched.
        assert repo.get_inventory_item("item-1").consignment.consignor_id == alice["consignor_id"]


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
