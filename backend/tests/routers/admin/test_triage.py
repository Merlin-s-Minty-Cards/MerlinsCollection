"""T11 — Triage queue: backend RED tests.

Triage IS the ``needs_review`` queue (docs/plans/rfc-0008/t11-triage-tab.md). No
second flag is invented here. What is added is the two things the bare boolean is
missing — a *reason* and a *cleared-at stamp* — plus the two derived filters and
the count endpoint the sidebar badge reads.

The contract these tests pin, stated once so the GREEN phase has no guesswork:

* ``review_reason: str | None`` on ``_ItemBase``. Bounded (500) and blank-is-None,
  mirroring ``display_name_override`` — it is free text an admin types, and an
  unbounded string rides into a DynamoDB item that has a 400 KB ceiling.
  Deliberately **not** in ``_CUSTOMER_ITEM_FIELDS``: it is internal, unlike
  ``value_note`` which is customer-visible by design.
* ``reviewed_at: datetime | None`` on ``_ItemBase``, stamped by the SERVER when an
  admin clears the flag. The client never sends it.
* ``MACHINE_REVIEW_REASONS`` — the fixed vocabulary the automated setters use.

**Why the re-flag guard keys off the reason vocabulary.** The task doc asks that
"automation must not re-flag an item whose ``reviewed_at`` is newer than the data
it is reacting to", with a documented fallback of "automation never re-flags an
item with a non-null ``reviewed_at``". Neither is directly expressible today:
verified 2026-08-06, **no code path writes ``needs_review=True`` onto an existing
row**. Both setters mint a fresh ULID and create a new item
(``spreadsheet_import.import_singles``, ``purchases.confirm_buy_session``), and
``run_singles_only_import`` sweeps the prior generation outright. A guard written
against "the import path" would therefore be unreachable code with a vacuous test.

So the guard lives on the one writer of existing rows — ``PUT
/admin/inventory/{item_id}`` — and the automated/human distinction is carried by
the reason itself: a write supplying a reason from ``MACHINE_REVIEW_REASONS`` is
automation and must not re-flag a reviewed item; a human "Send to Triage" (free
text, or no reason) always may, and clears ``reviewed_at`` when it does. That is
the task doc's fallback rule, expressed where a future in-place re-matcher will
actually hit it.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from merlins_collection.models.catalog import CardImages, CatalogCard
from merlins_collection.models.inventory import (
    Condition,
    GradedInventoryItem,
    GradingCompany,
    InventoryItemAdapter,
    ItemStatus,
    Language,
    RawInventoryItem,
    SealedInventoryItem,
    SealedProductType,
)


# ---- helpers ----

def _raw(*, item_id=None, card_id="en:sv1-1", language=Language.EN, location="glass",
         status=ItemStatus.AVAILABLE, **extra):
    kw = dict(
        card_id=card_id,
        language=language,
        finish="normal",
        condition=Condition.NM,
        location=location,
        status=status,
        cost_basis=Decimal("10.00"),
        acquired_at=date(2025, 1, 1),
    )
    if item_id:
        kw["item_id"] = item_id
    kw.update(extra)
    return RawInventoryItem(**kw)


def _graded(*, item_id=None, card_id="en:sv1-2", **extra):
    kw = dict(
        card_id=card_id,
        location="glass",
        status=ItemStatus.AVAILABLE,
        cost_basis=Decimal("30.00"),
        acquired_at=date(2025, 1, 1),
        company=GradingCompany.PSA,
        grade=Decimal("9"),
        cert_number="12345678",
    )
    if item_id:
        kw["item_id"] = item_id
    kw.update(extra)
    return GradedInventoryItem(**kw)


def _sealed(*, item_id=None, **extra):
    """A kind with NO ``card_id`` attribute at all.

    Present in every fixture that exercises the "unlinked" filter on purpose: a
    naive ``i.card_id is None`` comprehension raises ``AttributeError`` on sealed
    and bulk items and turns the whole search into a 500. The filter has to reach
    for the attribute defensively.
    """
    kw = dict(
        product_name="Obsidian Flames ETB",
        product_type=SealedProductType.ETB,
        location="glass",
        status=ItemStatus.AVAILABLE,
        cost_basis=Decimal("40.00"),
        acquired_at=date(2025, 1, 1),
    )
    if item_id:
        kw["item_id"] = item_id
    kw.update(extra)
    return SealedInventoryItem(**kw)


def _catalog(card_id="en:sv1-1", name="Pikachu"):
    return CatalogCard(
        card_id=card_id,
        name=name,
        set_id="sv1",
        set_name="Scarlet & Violet",
        number="001",
        rarity="Common",
        images=CardImages(
            small="https://example.com/s.webp", large="https://example.com/l.webp",
        ),
        last_synced_at=datetime.now(tz=timezone.utc),
        prices={},
    )


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---- fixtures ----

@pytest.fixture
def admin_client(cognito_config, jwks, dynamo_repo, mint_token):
    """Overrides the package fixture to add a NON-admin token as a 4th element.

    ``TestAuthGate`` needs both sides of the gate. The wiring comes from
    ``conftest.build_admin_client``; only the token shape differs.
    """
    from .conftest import build_admin_client, clear_overrides

    client = build_admin_client(cognito_config, jwks, dynamo_repo)
    yield (
        client,
        dynamo_repo,
        mint_token(claims={"cognito:groups": ["admin"]}),
        mint_token(claims={"cognito:groups": []}),
    )
    clear_overrides()


# ===========================================================================
# 1-2 — the reason and the cleared-at stamp
# ===========================================================================

class TestFlagAndClear:

    def test_send_to_triage_stores_a_free_text_reason(self, admin_client):
        """RED 1 — ``review_reason`` does not exist on the model today."""
        client, repo, admin, _ = admin_client
        repo.put_inventory_item(_raw(item_id="item-1"))

        resp = client.put(
            "/admin/inventory/item-1",
            json={"needs_review": True, "review_reason": "back looks trimmed"},
            headers=_auth(admin),
        )

        assert resp.status_code == 200
        assert resp.json()["needs_review"] is True
        assert resp.json()["review_reason"] == "back looks trimmed"
        # Durable, not just echoed back off the request body.
        assert repo.get_inventory_item("item-1").review_reason == "back looks trimmed"

    def test_send_to_triage_without_a_note_leaves_the_reason_empty(self, admin_client):
        """The note is optional — flagging with no reason must not 422."""
        client, repo, admin, _ = admin_client
        repo.put_inventory_item(_raw(item_id="item-1"))

        resp = client.put(
            "/admin/inventory/item-1", json={"needs_review": True}, headers=_auth(admin),
        )

        assert resp.status_code == 200
        assert resp.json()["needs_review"] is True
        assert resp.json()["review_reason"] is None

    def test_clearing_review_stamps_reviewed_at_server_side(self, admin_client):
        """RED 2 — the stamp is what stops the queue rotting, and the SERVER owns it.

        The client sends only ``needs_review: false``; it never supplies a
        timestamp of its own (a clock it controls is not evidence of review).
        """
        client, repo, admin, _ = admin_client
        repo.put_inventory_item(
            _raw(item_id="item-1", needs_review=True, review_reason="manual_entry"),
        )
        before = datetime.now(tz=timezone.utc)

        resp = client.put(
            "/admin/inventory/item-1", json={"needs_review": False}, headers=_auth(admin),
        )

        assert resp.status_code == 200
        assert resp.json()["needs_review"] is False

        stored = repo.get_inventory_item("item-1")
        assert stored.reviewed_at is not None, "clearing review must stamp reviewed_at"
        # Round-trips through DynamoDB as an ISO string and back to an aware
        # datetime — a naive value here would make every later comparison raise.
        assert stored.reviewed_at.tzinfo is not None
        assert before - timedelta(seconds=5) <= stored.reviewed_at

    def test_review_reason_is_bounded_and_blank_means_none(self, admin_client):
        """Free text an admin types goes into a DynamoDB item with a 400 KB ceiling.

        Mirrors ``display_name_override``: trimmed, blank normalized to None,
        over-length rejected rather than stored.
        """
        client, repo, admin, _ = admin_client
        repo.put_inventory_item(_raw(item_id="item-1"))

        blank = client.put(
            "/admin/inventory/item-1",
            json={"needs_review": True, "review_reason": "   "},
            headers=_auth(admin),
        )
        assert blank.status_code == 200
        assert blank.json()["review_reason"] is None

        too_long = client.put(
            "/admin/inventory/item-1",
            json={"needs_review": True, "review_reason": "x" * 501},
            headers=_auth(admin),
        )
        assert too_long.status_code == 422


# ===========================================================================
# 3 — the guard that stops the queue rotting
# ===========================================================================

class TestReFlagGuard:
    """See the module docstring for why the guard keys off the reason vocabulary."""

    def test_a_machine_reason_does_not_re_flag_a_reviewed_item(self, admin_client):
        """RED 3 — the test that stops the queue from rotting.

        An admin inspected this item and passed it. A later automated write
        reacting to the same stale signal (low match confidence, manual entry)
        must leave it cleared, or the tab fills back up with cards a human has
        already looked at and the whole feature becomes noise.
        """
        from merlins_collection.models.inventory import MACHINE_REVIEW_REASONS

        client, repo, admin, _ = admin_client
        repo.put_inventory_item(
            _raw(
                item_id="item-1",
                needs_review=False,
                reviewed_at=datetime(2026, 8, 5, tzinfo=timezone.utc),
            ),
        )

        for reason in sorted(MACHINE_REVIEW_REASONS):
            resp = client.put(
                "/admin/inventory/item-1",
                json={"needs_review": True, "review_reason": reason},
                headers=_auth(admin),
            )
            assert resp.status_code == 200
            assert resp.json()["needs_review"] is False, (
                f"machine reason {reason!r} re-flagged an item a human already cleared"
            )
            assert repo.get_inventory_item("item-1").reviewed_at is not None

    def test_a_machine_reason_still_flags_an_item_nobody_has_reviewed(self, admin_client):
        """The guard must be narrow — it protects reviewed items, not all items."""
        client, repo, admin, _ = admin_client
        repo.put_inventory_item(_raw(item_id="item-1"))  # reviewed_at is None

        resp = client.put(
            "/admin/inventory/item-1",
            json={"needs_review": True, "review_reason": "low_match_confidence"},
            headers=_auth(admin),
        )

        assert resp.status_code == 200
        assert resp.json()["needs_review"] is True

    def test_a_human_send_to_triage_re_flags_a_reviewed_item_and_clears_the_stamp(
        self, admin_client,
    ):
        """A human overrules an earlier human. Otherwise a card cleared once could
        never be sent back to Triage — and the owner's requirement is that ANY
        card can be sent there from anywhere.
        """
        client, repo, admin, _ = admin_client
        repo.put_inventory_item(
            _raw(
                item_id="item-1",
                needs_review=False,
                reviewed_at=datetime(2026, 8, 5, tzinfo=timezone.utc),
            ),
        )

        resp = client.put(
            "/admin/inventory/item-1",
            json={"needs_review": True, "review_reason": "set symbol is wrong"},
            headers=_auth(admin),
        )

        assert resp.status_code == 200
        assert resp.json()["needs_review"] is True
        # Stale stamp cleared: it now says "reviewed and passed" about an item
        # that is back in the queue, and would suppress the next automated flag.
        assert repo.get_inventory_item("item-1").reviewed_at is None


# ===========================================================================
# 4 — leak guard
# ===========================================================================

class TestCustomerLeakGuard:

    def test_review_reason_never_reaches_the_customer_search(self, admin_client, mint_token):
        """RED 4 — an internal note must never reach a buyer.

        ``value_note`` is customer-visible by design (Phase 19); ``review_reason``
        is the opposite and must stay out of ``_CUSTOMER_ITEM_FIELDS``. An admin
        typing "consignor wants $400 minimum" into a triage note must not publish
        it.
        """
        client, repo, _, _ = admin_client
        repo.batch_upsert_catalog_cards([_catalog()])
        repo.put_inventory_item(
            _raw(
                item_id="item-1",
                listed_price=Decimal("10.00"),
                needs_review=True,
                review_reason="consignor wants $400 minimum",
                reviewed_at=datetime(2026, 8, 5, tzinfo=timezone.utc),
            ),
        )

        resp = client.get(
            "/inventory/search", headers=_auth(mint_token()),
        )

        assert resp.status_code == 200
        items = resp.json()["items"]
        assert items, "fixture item must be visible to the customer for this to prove anything"
        for item in items:
            assert "review_reason" not in item
            assert "reviewed_at" not in item
            assert "needs_review" not in item
        assert "consignor wants $400 minimum" not in resp.text

    def test_review_reason_is_not_in_the_customer_field_allowlist(self):
        """Pinned at the allowlist itself, not only at one response.

        The response assertion above passes for the wrong reason if the field is
        merely absent from the fixture; this one fails the moment someone adds
        the key to the set.
        """
        from merlins_collection.routers.inventory import _CUSTOMER_ITEM_FIELDS

        assert "review_reason" not in _CUSTOMER_ITEM_FIELDS
        assert "reviewed_at" not in _CUSTOMER_ITEM_FIELDS


# ===========================================================================
# 5 — migration safety
# ===========================================================================

class TestMigrationSafety:

    def test_a_row_written_before_these_fields_existed_still_loads(self, admin_client):
        """RED 5 — all 266 live rows predate every field this task adds.

        A required field, or a validator that assumes one is present, bricks the
        entire inventory on deploy. Defaults must absorb their absence.
        """
        client, repo, admin, _ = admin_client
        legacy = {
            "kind": "raw",
            "item_id": "legacy-1",
            "card_id": "en:sv1-1",
            "finish": "normal",
            "condition": "NM",
            "location": "glass",
            "status": "available",
            "cost_basis": "10.00",
            "acquired_at": "2025-01-01",
        }

        item = InventoryItemAdapter.validate_python(legacy)

        assert item.needs_review is False
        assert item.review_reason is None
        assert item.reviewed_at is None

        repo.put_inventory_item(item)
        resp = client.get("/admin/inventory/legacy-1", headers=_auth(admin))
        assert resp.status_code == 200
        assert resp.json()["review_reason"] is None
        assert resp.json()["reviewed_at"] is None


# ===========================================================================
# 6-7 — the derived filters
# ===========================================================================

class TestDerivedFilters:

    def test_filters_to_items_with_no_catalog_link(self, admin_client):
        """RED 6 — 13 live items have never matched a catalog row.

        The sealed item in this fixture is load-bearing: ``SealedInventoryItem``
        and ``BulkInventoryItem`` have no ``card_id`` attribute at all, so a
        naive ``i.card_id is None`` raises ``AttributeError`` and 500s the search
        before any assertion below is reached.
        """
        client, repo, admin, _ = admin_client
        repo.put_inventory_item(_raw(item_id="linked", card_id="en:sv1-1"))
        repo.put_inventory_item(_raw(item_id="unlinked", card_id=None))
        repo.put_inventory_item(_graded(item_id="unlinked-slab", card_id=None))
        repo.put_inventory_item(_sealed(item_id="sealed-1"))

        resp = client.get(
            "/admin/inventory/search?missing_card_id=true", headers=_auth(admin),
        )

        assert resp.status_code == 200
        ids = {i["item_id"] for i in resp.json()["items"]}
        assert ids == {"unlinked", "unlinked-slab"}, (
            "a card-linkable item with no card_id qualifies; a sealed product, "
            "which has no catalog link by design, does not"
        )

    def test_filters_to_japanese_items_with_no_english_name(self, admin_client):
        """RED 7 — 17 live JP items, 9 of them catalog-linked to a JP-script row.

        Self-healing by construction: assign the override and the row leaves the
        list on its own, with no flag to clear.
        """
        client, repo, admin, _ = admin_client
        repo.put_inventory_item(_raw(item_id="jp-unnamed", language=Language.JP, card_id="ja:M4-084"))
        repo.put_inventory_item(
            _raw(
                item_id="jp-named",
                language=Language.JP,
                card_id="ja:M4-085",
                display_name_override="Chespin",
            ),
        )
        repo.put_inventory_item(_raw(item_id="en-1", language=Language.EN))

        resp = client.get(
            "/admin/inventory/search?missing_english_name=true", headers=_auth(admin),
        )

        assert resp.status_code == 200
        ids = {i["item_id"] for i in resp.json()["items"]}
        assert ids == {"jp-unnamed"}

    def test_triage_returns_the_union_of_every_reason(self, admin_client):
        """One list, not parallel queues.

        Every other filter on this endpoint is AND-combined, which cannot express
        "flagged OR unlinked OR unnamed". ``triage=true`` is the one OR, and it
        lives on this endpoint rather than a parallel list route so the Triage
        page inherits sorting, catalog joins and every existing filter for free.
        """
        client, repo, admin, _ = admin_client
        repo.put_inventory_item(_raw(item_id="flagged", needs_review=True))
        repo.put_inventory_item(_raw(item_id="unlinked", card_id=None))
        repo.put_inventory_item(
            _raw(item_id="jp-unnamed", language=Language.JP, card_id="ja:M4-084"),
        )
        repo.put_inventory_item(_raw(item_id="clean"))
        repo.put_inventory_item(_sealed(item_id="sealed-1"))

        resp = client.get("/admin/inventory/search?triage=true", headers=_auth(admin))

        assert resp.status_code == 200
        ids = {i["item_id"] for i in resp.json()["items"]}
        assert ids == {"flagged", "unlinked", "jp-unnamed"}

    def test_triage_lists_a_multi_reason_item_exactly_once(self, admin_client):
        """The whole reason for one list with chips instead of a tab per reason."""
        client, repo, admin, _ = admin_client
        repo.put_inventory_item(
            _raw(
                item_id="both",
                card_id=None,
                needs_review=True,
                language=Language.JP,
            ),
        )
        # A clean item so an IGNORED ``triage`` param cannot pass this test by
        # accident — without it, "everything" and "just the one item" are the
        # same list.
        repo.put_inventory_item(_raw(item_id="clean"))

        resp = client.get("/admin/inventory/search?triage=true", headers=_auth(admin))

        assert resp.status_code == 200
        ids = [i["item_id"] for i in resp.json()["items"]]
        assert ids == ["both"]

    def test_triage_rows_carry_the_joined_catalog_card(self, admin_client):
        """The admin must see the EFFECTIVE name — what the customer sees.

        T10's precedence is ``display_name_override -> card.name -> display_name``,
        so a row with no catalog join can only ever render the fallback, and an
        admin "fixing" a name would be working blind against the one field that
        actually outranks theirs. Scoped to ``triage=true`` so the ordinary admin
        search keeps its current payload and cost.
        """
        client, repo, admin, _ = admin_client
        repo.batch_upsert_catalog_cards([_catalog(card_id="ja:M4-084", name="ハリマロン")])
        repo.put_inventory_item(
            _raw(item_id="jp-unnamed", language=Language.JP, card_id="ja:M4-084"),
        )

        resp = client.get("/admin/inventory/search?triage=true", headers=_auth(admin))

        assert resp.status_code == 200
        row = resp.json()["items"][0]
        assert row["card"]["name"] == "ハリマロン"

    def test_derived_filters_compose_with_the_stored_flag(self, admin_client):
        """Filters are AND-combined like every other filter on this endpoint —
        the Triage page narrows by reason on top of them.
        """
        client, repo, admin, _ = admin_client
        repo.put_inventory_item(_raw(item_id="both", card_id=None, needs_review=True))
        repo.put_inventory_item(_raw(item_id="only-unlinked", card_id=None))
        repo.put_inventory_item(_raw(item_id="only-flagged", needs_review=True))

        resp = client.get(
            "/admin/inventory/search?missing_card_id=true&needs_review=true",
            headers=_auth(admin),
        )

        assert resp.status_code == 200
        ids = {i["item_id"] for i in resp.json()["items"]}
        assert ids == {"both"}


# ===========================================================================
# 8 — re-pointing a mismatched card
# ===========================================================================

class TestRepointCardId:

    def test_update_accepts_a_card_id_change_and_persists_it(self, admin_client):
        """RED 8 — the dangerous write. ``card_id`` drives pricing, images, set
        and rarity, so permitting it here is a DELIBERATE decision, recorded as a
        contract test rather than left to the fact that ``admin_update_item``
        happens to merge the whole body today (follow-ups.md, T10 row 4).

        NOTE: expected to pass on the first run — there is no allowlist on this
        endpoint. It is a pin, not a red-to-green step: it fails the day someone
        adds one without thinking about Triage.

        The TARGET must now exist in the catalog (see
        ``TestCardIdIsValidatedAgainstTheCatalog``), so this seeds it. The rule
        being pinned here is unchanged — ``card_id`` is writable — only the
        target has to be a real card rather than any string.
        """
        client, repo, admin, _ = admin_client
        repo.batch_upsert_catalog_cards([_catalog(card_id="en:sv1-99", name="Rayquaza")])
        repo.put_inventory_item(_raw(item_id="item-1", card_id="en:sv1-1"))

        resp = client.put(
            "/admin/inventory/item-1", json={"card_id": "en:sv1-99"}, headers=_auth(admin),
        )

        assert resp.status_code == 200
        assert resp.json()["card_id"] == "en:sv1-99"
        assert repo.get_inventory_item("item-1").card_id == "en:sv1-99"

    def test_assigning_a_display_name_never_touches_card_id(self, admin_client):
        """The owner's core requirement, pinned server-side as well as in the UI.

        Copying an English name off a catalog card is choosing a *name*, not
        re-linking the item.
        """
        client, repo, admin, _ = admin_client
        repo.put_inventory_item(
            _raw(item_id="item-1", card_id="ja:M4-084", language=Language.JP),
        )

        resp = client.put(
            "/admin/inventory/item-1",
            json={"display_name_override": "Chespin"},
            headers=_auth(admin),
        )

        assert resp.status_code == 200
        assert resp.json()["display_name_override"] == "Chespin"
        assert repo.get_inventory_item("item-1").card_id == "ja:M4-084"


# ===========================================================================
# 9 — the sidebar badge's count endpoint
# ===========================================================================

class TestTriageCounts:

    def test_counts_are_reported_per_reason(self, admin_client):
        """RED 9 — ``GET /admin/triage/counts``.

        ``total`` counts CARDS, not reasons: an item qualifying under two reasons
        is one thing to fix, and a badge that double-counts it sends the admin
        looking for a card that is not there.
        """
        client, repo, admin, _ = admin_client
        repo.put_inventory_item(_raw(item_id="flagged", needs_review=True))
        repo.put_inventory_item(_raw(item_id="unlinked", card_id=None))
        repo.put_inventory_item(
            _raw(item_id="jp-unnamed", language=Language.JP, card_id="ja:M4-084"),
        )
        # Qualifies under BOTH "flagged" and "unlinked".
        repo.put_inventory_item(_raw(item_id="both", card_id=None, needs_review=True))
        repo.put_inventory_item(_raw(item_id="clean"))
        repo.put_inventory_item(_sealed(item_id="sealed-1"))

        resp = client.get("/admin/triage/counts", headers=_auth(admin))

        assert resp.status_code == 200
        body = resp.json()
        assert body["reasons"] == {
            "flagged": 2,
            "missing_card_id": 2,
            "missing_english_name": 1,
        }
        assert body["total"] == 4, "distinct items needing attention, not reason hits"

    def test_counts_are_zero_when_nothing_needs_review(self, admin_client):
        """The empty state the badge has to render as "no badge", not "0"."""
        client, repo, admin, _ = admin_client
        repo.put_inventory_item(_raw(item_id="clean"))

        resp = client.get("/admin/triage/counts", headers=_auth(admin))

        assert resp.status_code == 200
        assert resp.json()["total"] == 0


# ===========================================================================
# 10 — auth gate on every new/changed route
# ===========================================================================

class TestAuthGate:

    @pytest.mark.parametrize(
        "method,path,body",
        [
            ("get", "/admin/triage/counts", None),
            ("get", "/admin/inventory/search?missing_card_id=true", None),
            ("get", "/admin/inventory/search?missing_english_name=true", None),
            ("put", "/admin/inventory/item-1", {"needs_review": True}),
            # T3's bulk mutation. A route that clears flags across the whole
            # table gets the same gate as everything else here.
            ("post", "/admin/inventory/bulk-clear-review", {}),
        ],
    )
    def test_non_admin_is_rejected(self, admin_client, method, path, body):
        client, repo, _, user = admin_client
        repo.put_inventory_item(_raw(item_id="item-1"))

        resp = getattr(client, method)(
            path, headers=_auth(user), **({"json": body} if body is not None else {}),
        )

        assert resp.status_code == 403

    @pytest.mark.parametrize(
        "path",
        ["/admin/triage/counts", "/admin/inventory/search?missing_card_id=true"],
    )
    def test_unauthenticated_is_rejected(self, admin_client, path):
        client, *_ = admin_client
        assert client.get(path).status_code == 401


class TestCardIdIsValidatedAgainstTheCatalog:
    """Re-pointing an item must land on a card that actually exists.

    T11 makes editing ``card_id`` a first-class, encouraged flow (the "wrong
    card" repair tool), but ``PUT /admin/inventory/{id}`` has no allowlist and
    did no validation, so a stale or hand-crafted id linked an item to a phantom
    card. The importer already guards exactly this (``spreadsheet_import``
    validates the composite against the catalog index before storing it); this
    path did not.

    An item pointing at a nonexistent card resolves no price, no image and no
    set — so it comes back to Triage looking UNLINKED while actually carrying a
    bad id, which is more confusing than the null it replaced.
    """

    def test_repointing_to_a_nonexistent_card_is_rejected(self, admin_client):
        client, repo, admin, _ = admin_client
        repo.put_inventory_item(_raw(item_id="item-1", card_id="en:sv1-1"))

        resp = client.put(
            "/admin/inventory/item-1",
            json={"card_id": "totally-made-up-999"},
            headers=_auth(admin),
        )

        assert resp.status_code == 422
        assert "catalog" in resp.json()["detail"].lower()
        # And nothing was written.
        assert repo.get_inventory_item("item-1").card_id == "en:sv1-1"

    def test_repointing_to_a_real_card_still_works(self, admin_client):
        client, repo, admin, _ = admin_client
        repo.batch_upsert_catalog_cards([_catalog(card_id="en:sv1-25", name="Pikachu")])
        repo.put_inventory_item(_raw(item_id="item-1", card_id="en:sv1-1"))

        resp = client.put(
            "/admin/inventory/item-1",
            json={"card_id": "en:sv1-25"},
            headers=_auth(admin),
        )

        assert resp.status_code == 200
        assert repo.get_inventory_item("item-1").card_id == "en:sv1-25"

    def test_clearing_the_card_id_is_still_allowed(self, admin_client):
        """Unlinking is a legitimate repair — an item whose match was simply
        wrong, with no right answer known yet, belongs in Triage as unlinked."""
        client, repo, admin, _ = admin_client
        repo.put_inventory_item(_raw(item_id="item-1", card_id="en:sv1-1"))

        resp = client.put(
            "/admin/inventory/item-1",
            json={"card_id": None},
            headers=_auth(admin),
        )

        assert resp.status_code == 200
        assert repo.get_inventory_item("item-1").card_id is None

    def test_an_untouched_card_id_is_not_revalidated(self, admin_client):
        """Editing an unrelated field on an item whose (pre-existing) card_id is
        not in the catalog must not start failing. Validation applies to what the
        request is CHANGING, not to data already on the row — otherwise one bad
        legacy row becomes uneditable, including from Triage itself."""
        client, repo, admin, _ = admin_client
        repo.put_inventory_item(_raw(item_id="item-1", card_id="legacy-orphan-1"))

        resp = client.put(
            "/admin/inventory/item-1",
            json={"sticker_notes": "top shelf"},
            headers=_auth(admin),
        )

        assert resp.status_code == 200


class TestAutomationStatesItsReason:
    """Whatever flags an item must say WHY.

    ``MACHINE_REVIEW_REASONS`` was pinned by test and consumed by the re-flag
    guard, but nothing actually WROTE one: the importer and the Buy flow both set
    the bare boolean. So Triage showed a queue of cards with an unexplained
    "flagged" chip — which the task doc calls "not a worklist", since the admin
    cannot tell what needs fixing (follow-ups.md, T11 row 8).

    Rows written BEFORE the field existed cannot be backfilled — the data no
    longer distinguishes the cases — so those keep the bare chip. This only fixes
    it going forward.
    """

    def test_buy_flow_records_manual_entry_as_the_reason(self, admin_client):
        from merlins_collection.routers.admin.purchases import _review_reason_for_buy

        assert _review_reason_for_buy({"manual_entry": True, "card_id": "en:sv1-1"}) == (
            "manual_entry"
        )

    def test_buy_flow_records_a_missing_catalog_link(self, admin_client):
        from merlins_collection.routers.admin.purchases import _review_reason_for_buy

        assert _review_reason_for_buy({"card_id": None}) == "no_catalog_link"

    def test_buy_flow_records_nothing_for_a_clean_item(self, admin_client):
        from merlins_collection.routers.admin.purchases import _review_reason_for_buy

        assert _review_reason_for_buy({"card_id": "en:sv1-1"}) is None

    def test_manual_entry_outranks_a_missing_link(self, admin_client):
        """An item can qualify twice; the reason column holds one string. Manual
        entry is the more actionable of the two — it tells the admin a human
        typed this rather than that a matcher failed."""
        from merlins_collection.routers.admin.purchases import _review_reason_for_buy

        assert _review_reason_for_buy({"manual_entry": True, "card_id": None}) == (
            "manual_entry"
        )

    def test_every_reason_written_is_in_the_machine_vocabulary(self, admin_client):
        """The re-flag guard distinguishes automation from a human by checking
        membership in MACHINE_REVIEW_REASONS. A writer emitting anything outside
        that set would be treated as a human and silently defeat the guard."""
        from merlins_collection.models.inventory import MACHINE_REVIEW_REASONS
        from merlins_collection.routers.admin.purchases import _review_reason_for_buy
        from merlins_collection.services.spreadsheet_import import _review_reason_for_row

        produced = {
            _review_reason_for_buy({"manual_entry": True}),
            _review_reason_for_buy({"card_id": None}),
            _review_reason_for_row(card_id=None, confidence="high", blank_condition=False),
            _review_reason_for_row(card_id="x", confidence="low", blank_condition=False),
            _review_reason_for_row(card_id="x", confidence="high", blank_condition=True),
        }
        produced.discard(None)
        assert produced <= MACHINE_REVIEW_REASONS
        assert produced  # and it actually produced some

    def test_import_reasons_cover_the_three_cases(self, admin_client):
        from merlins_collection.services.spreadsheet_import import _review_reason_for_row

        assert _review_reason_for_row(
            card_id=None, confidence="high", blank_condition=False,
        ) == "no_catalog_link"
        assert _review_reason_for_row(
            card_id="x", confidence="low", blank_condition=False,
        ) == "low_match_confidence"
        assert _review_reason_for_row(
            card_id="x", confidence="high", blank_condition=True,
        ) == "blank_condition"
        assert _review_reason_for_row(
            card_id="x", confidence="high", blank_condition=False,
        ) is None


# ===========================================================================
# RFC 0010 T3 — the server says WHY, one filter narrows, the queue can drain
# ===========================================================================
#
# The premise, measured against the live table on 2026-08-11 before any of this
# was written: the query is NOT broken and never was. 27 of 284 rows qualify —
# 17 flagged-and-unlinked, 10 flagged-only — and `missing_english_name` and
# `blank_condition` are both at ZERO. What is wrong is that the reason chips are
# recomputed in TypeScript from a hand-mirrored copy of these rules, that the
# filter narrows by a stored boolean instead of by the predicate that produced
# the chip, and that a `sold` card's data quality sits in a worklist forever.
#
# The imports are LOCAL to each test on purpose: during RED these symbols do not
# exist, and a module-level import would collect-error the whole file instead of
# failing the tests that actually describe the new behaviour.


class TestReasonsFor:
    """`needs_triage` and the chips must be the same answer, not two answers."""

    def test_an_ordinary_linked_english_item_has_no_reasons(self, admin_client):
        from merlins_collection.services.triage import reasons_for

        assert reasons_for(_raw()) == []

    def test_an_unlinked_japanese_item_carries_both_derived_reasons(self, admin_client):
        from merlins_collection.services.triage import reasons_for

        item = _raw(card_id=None, language=Language.JP)

        assert set(reasons_for(item)) == {"missing_card_id", "missing_english_name"}

    def test_reasons_come_back_in_triage_reasons_order(self, admin_client):
        """The chip order is the declared order, not dict-comprehension luck.

        The counts payload and the filter dropdown both restate this order; a
        row whose chips come back shuffled makes them look like different lists.
        """
        from merlins_collection.services.triage import TRIAGE_REASONS, reasons_for

        item = _raw(card_id=None, language=Language.JP, needs_review=True)

        assert reasons_for(item) == list(TRIAGE_REASONS)

    def test_needs_triage_is_exactly_bool_of_reasons_for(self, admin_client):
        """THE invariant. A row in the list with no chip is the owner's report."""
        from merlins_collection.services.triage import needs_triage, reasons_for

        probes = [
            _raw(),                                                   # EN, linked
            _raw(card_id=None),                                       # unlinked
            _raw(language=Language.JP, card_id="ja:M4-084"),           # JP, unnamed
            _raw(language=Language.JP, display_name_override="Chespin"),
            _raw(needs_review=True),
            _raw(status=ItemStatus.SOLD),
            _sealed(),                                                # no card_id attr
            _graded(),
            _graded(card_id=None),
        ]

        for item in probes:
            assert needs_triage(item) == bool(reasons_for(item)), (
                f"{item.kind} item disagrees: "
                f"needs_triage={needs_triage(item)} reasons={reasons_for(item)}"
            )


class TestSearchEmitsTheReasonsItUsed:

    def test_every_triage_row_carries_a_non_empty_triage_reasons(self, admin_client):
        client, repo, admin, _ = admin_client
        repo.put_inventory_item(_raw(item_id="flagged", needs_review=True))
        repo.put_inventory_item(_raw(item_id="unlinked", card_id=None))
        repo.put_inventory_item(_raw(item_id="clean"))

        resp = client.get("/admin/inventory/search?triage=true", headers=_auth(admin))

        assert resp.status_code == 200
        rows = resp.json()["items"]
        assert len(rows) == 2
        for row in rows:
            assert row["triage_reasons"], (
                f"{row['item_id']} is in the list with no stated reason — "
                "the exact defect this field exists to make impossible"
            )

    def test_an_ordinary_admin_search_does_not_carry_the_key(self, admin_client):
        """Payload cost. The join beside it is scoped the same way.

        NOTE: passes before the change (the key does not exist yet). Kept as the
        guard that the new field is scoped rather than sprayed onto every admin
        search response.
        """
        client, repo, admin, _ = admin_client
        repo.put_inventory_item(_raw(item_id="flagged", needs_review=True))

        resp = client.get("/admin/inventory/search", headers=_auth(admin))

        assert resp.status_code == 200
        for row in resp.json()["items"]:
            assert "triage_reasons" not in row

    def test_the_array_is_exactly_what_reasons_for_returns(self, admin_client):
        from merlins_collection.services.triage import reasons_for

        client, repo, admin, _ = admin_client
        item = _raw(item_id="both", card_id=None, needs_review=True, language=Language.JP)
        repo.put_inventory_item(item)

        resp = client.get("/admin/inventory/search?triage=true", headers=_auth(admin))

        assert resp.status_code == 200
        assert resp.json()["items"][0]["triage_reasons"] == reasons_for(item)


class TestTriageReasonFilter:
    """One parameter, validated against the predicate set that built the union."""

    @pytest.fixture
    def seeded(self, admin_client):
        client, repo, admin, _ = admin_client
        repo.put_inventory_item(_raw(item_id="flagged-only", needs_review=True))
        repo.put_inventory_item(_raw(item_id="unlinked-only", card_id=None))
        repo.put_inventory_item(
            _raw(item_id="jp-only", language=Language.JP, card_id="ja:M4-084"),
        )
        repo.put_inventory_item(_raw(item_id="both", card_id=None, needs_review=True))
        repo.put_inventory_item(_raw(item_id="clean"))
        return client, admin

    def test_flagged_returns_only_flagged_items(self, seeded):
        client, admin = seeded

        resp = client.get(
            "/admin/inventory/search?triage=true&triage_reason=flagged",
            headers=_auth(admin),
        )

        assert resp.status_code == 200
        assert {i["item_id"] for i in resp.json()["items"]} == {"flagged-only", "both"}

    def test_missing_card_id_returns_only_unlinked_items(self, seeded):
        client, admin = seeded

        resp = client.get(
            "/admin/inventory/search?triage=true&triage_reason=missing_card_id",
            headers=_auth(admin),
        )

        assert resp.status_code == 200
        assert {i["item_id"] for i in resp.json()["items"]} == {"unlinked-only", "both"}

    def test_an_item_with_two_reasons_appears_under_both_filters(self, seeded):
        """It is one card with two problems, not two cards.

        The old dropdown narrowed `flagged` by the stored boolean rather than by
        the predicate that produced the chip; this is the assertion that pins the
        two to the same answer.
        """
        client, admin = seeded

        # The exclusions are asserted alongside the inclusion on purpose: an
        # IGNORED `triage_reason` returns the whole union, in which "both" also
        # appears — so the membership check alone passes without the filter
        # existing at all.
        expected = {
            "flagged": {"flagged-only", "both"},
            "missing_card_id": {"unlinked-only", "both"},
        }
        for reason, ids in expected.items():
            resp = client.get(
                f"/admin/inventory/search?triage=true&triage_reason={reason}",
                headers=_auth(admin),
            )
            assert resp.status_code == 200
            assert {i["item_id"] for i in resp.json()["items"]} == ids, reason

    def test_an_unknown_reason_key_is_rejected(self, seeded):
        """422, never a silent no-op — a filter that quietly does nothing looks
        exactly like a list that is pulling everything, which is the report."""
        client, admin = seeded

        resp = client.get(
            "/admin/inventory/search?triage=true&triage_reason=needs_sticker",
            headers=_auth(admin),
        )

        assert resp.status_code == 422
        assert "needs_sticker" in resp.json()["detail"]


class TestTriageStatusScope:
    """A sold card's data quality is not a worklist item."""

    def test_a_terminal_item_is_absent_by_default_and_present_with_the_flag(
        self, admin_client,
    ):
        client, repo, admin, _ = admin_client
        repo.put_inventory_item(_raw(item_id="live", needs_review=True))
        repo.put_inventory_item(
            _raw(item_id="sold", needs_review=True, status=ItemStatus.SOLD),
        )

        default = client.get("/admin/inventory/search?triage=true", headers=_auth(admin))
        assert default.status_code == 200
        assert {i["item_id"] for i in default.json()["items"]} == {"live"}

        widened = client.get(
            "/admin/inventory/search?triage=true&include_terminal=true",
            headers=_auth(admin),
        )
        assert widened.status_code == 200
        assert {i["item_id"] for i in widened.json()["items"]} == {"live", "sold"}

    def test_the_counts_endpoint_agrees_with_the_list_under_the_same_scope(
        self, admin_client,
    ):
        """A badge that counts differently from the page it links to is worse
        than no badge — and scoping the list without scoping the count is the
        easiest possible way to reintroduce exactly that.

        NOTE: passes before the change, because nothing is scoped yet and the two
        trivially agree. It is a pin, not a red-to-green step — it goes red the
        moment someone narrows one of the two and forgets the other.
        """
        client, repo, admin, _ = admin_client
        repo.put_inventory_item(_raw(item_id="live", needs_review=True))
        repo.put_inventory_item(
            _raw(item_id="sold", needs_review=True, status=ItemStatus.SOLD),
        )
        repo.put_inventory_item(
            _raw(item_id="lost", card_id=None, status=ItemStatus.LOST),
        )

        for suffix in ("", "&include_terminal=true"):
            listed = client.get(
                f"/admin/inventory/search?triage=true{suffix}", headers=_auth(admin),
            )
            counted = client.get(
                f"/admin/triage/counts?{suffix.lstrip('&')}", headers=_auth(admin),
            )
            assert listed.status_code == 200
            assert counted.status_code == 200
            assert counted.json()["total"] == len(listed.json()["items"]), suffix


class TestBulkClearMachineFlags:
    """Narrow by construction: only a flag automation set, and never the money one."""

    def test_clears_an_item_whose_only_reason_is_a_machine_flag(self, admin_client):
        client, repo, admin, _ = admin_client
        repo.put_inventory_item(
            _raw(item_id="machine", needs_review=True, review_reason="manual_entry"),
        )

        resp = client.post(
            "/admin/inventory/bulk-clear-review", json={}, headers=_auth(admin),
        )

        assert resp.status_code == 200
        stored = repo.get_inventory_item("machine")
        assert stored.needs_review is False
        assert stored.review_reason is None

    def test_never_clears_a_flag_a_human_typed(self, admin_client):
        """The whole safety property. An admin's own note is not machine noise,
        and a bulk button that eats it destroys the one thing in this queue that
        a person deliberately recorded."""
        client, repo, admin, _ = admin_client
        repo.put_inventory_item(
            _raw(item_id="human", needs_review=True, review_reason="back looks trimmed"),
        )
        repo.put_inventory_item(
            _raw(item_id="noteless", needs_review=True, review_reason=None),
        )

        resp = client.post(
            "/admin/inventory/bulk-clear-review", json={}, headers=_auth(admin),
        )

        assert resp.status_code == 200
        assert repo.get_inventory_item("human").needs_review is True
        assert repo.get_inventory_item("human").review_reason == "back looks trimmed"
        # A bare flag carries no evidence it was automation, so it is not
        # clearable either — absence of a reason is not a machine reason.
        assert repo.get_inventory_item("noteless").needs_review is True

    def test_never_clears_a_blank_condition_item_because_it_is_a_money_bug(
        self, admin_client,
    ):
        """`blank_condition` means the importer stored NM — the MOST EXPENSIVE
        tier — for a card whose condition nobody recorded, and every customer
        price scales down from it (LP is listed at 1.22x, MP at 1.72x). Clearing
        it in bulk silently ratifies that price on every unchecked card.

        Measured 2026-08-11: zero such rows survive in the live table. The
        exclusion stays anyway — the importer's flag is historical, but the rule
        is what stops a future bulk button from re-creating the defect.
        """
        client, repo, admin, _ = admin_client
        repo.put_inventory_item(
            _raw(item_id="money", needs_review=True, review_reason="blank_condition"),
        )

        resp = client.post(
            "/admin/inventory/bulk-clear-review", json={}, headers=_auth(admin),
        )

        assert resp.status_code == 200
        assert resp.json()["cleared"] == 0
        assert repo.get_inventory_item("money").needs_review is True

    def test_an_item_with_another_problem_is_left_completely_alone(self, admin_client):
        """Clearing a flag on a row that stays in the list anyway is pure loss.

        The task doc states the rule twice and the two readings differ: "clears
        only items whose ONLY reason is flagged" versus "an item that is also
        unlinked keeps its other reasons and stays in the list". The first is
        what is built, and it is the safer one — clearing the flag here would
        destroy the stored ``review_reason`` while the row remains in the queue
        (so the queue is no shorter), and would stamp ``reviewed_at`` on an item
        nobody actually reviewed, suppressing the next automated flag.
        """
        client, repo, admin, _ = admin_client
        repo.put_inventory_item(
            _raw(
                item_id="also-unlinked",
                card_id=None,
                needs_review=True,
                review_reason="no_catalog_link",
            ),
        )

        resp = client.post(
            "/admin/inventory/bulk-clear-review", json={}, headers=_auth(admin),
        )
        assert resp.status_code == 200
        assert resp.json()["cleared"] == 0

        stored = repo.get_inventory_item("also-unlinked")
        assert stored.needs_review is True
        assert stored.review_reason == "no_catalog_link"
        assert stored.reviewed_at is None

        listed = client.get("/admin/inventory/search?triage=true", headers=_auth(admin))
        row = listed.json()["items"][0]
        assert row["item_id"] == "also-unlinked"
        assert row["triage_reasons"] == ["flagged", "missing_card_id"]
        assert row["bulk_clearable"] is False

    def test_clearing_in_bulk_stamps_reviewed_at(self, admin_client):
        """The bulk path inherits the anti-rot guarantee rather than bypassing
        it — without the stamp, automation re-flags what this just cleared."""
        client, repo, admin, _ = admin_client
        repo.put_inventory_item(
            _raw(item_id="machine", needs_review=True, review_reason="manual_entry"),
        )
        before = datetime.now(tz=timezone.utc)

        resp = client.post(
            "/admin/inventory/bulk-clear-review", json={}, headers=_auth(admin),
        )

        assert resp.status_code == 200
        stamped = repo.get_inventory_item("machine").reviewed_at
        assert stamped is not None
        assert stamped.tzinfo is not None
        assert before - timedelta(seconds=5) <= stamped

    def test_returns_the_count_cleared(self, admin_client):
        """The UI confirms with this exact number before firing — never a bare
        "Clear all"."""
        client, repo, admin, _ = admin_client
        for n in range(3):
            repo.put_inventory_item(
                _raw(item_id=f"machine-{n}", needs_review=True,
                     review_reason="low_match_confidence"),
            )
        repo.put_inventory_item(
            _raw(item_id="human", needs_review=True, review_reason="looks off"),
        )

        resp = client.post(
            "/admin/inventory/bulk-clear-review", json={}, headers=_auth(admin),
        )

        assert resp.status_code == 200
        assert resp.json()["cleared"] == 3

    def test_it_clears_only_what_the_admin_is_looking_at(self, admin_client):
        """"Clear what I am looking at" is the whole reason it takes the search's
        own filter arguments rather than a bare "everything"."""
        client, repo, admin, _ = admin_client
        repo.put_inventory_item(
            _raw(item_id="flagged-only", needs_review=True, review_reason="manual_entry"),
        )
        repo.put_inventory_item(
            _raw(
                item_id="also-unlinked",
                card_id=None,
                needs_review=True,
                review_reason="manual_entry",
            ),
        )

        resp = client.post(
            "/admin/inventory/bulk-clear-review",
            json={"triage_reason": "missing_card_id"},
            headers=_auth(admin),
        )

        assert resp.status_code == 200
        assert resp.json()["cleared"] == 0, (
            "an item that is also unlinked is not clearable, so a filter scoped "
            "to the unlinked queue clears nothing"
        )
        assert repo.get_inventory_item("flagged-only").needs_review is True


# ===========================================================================
# RFC 0011 T5 — `no_catalog_match`, the stored answer a derived reason cannot hold
# ===========================================================================
#
# `is_missing_card_id` is DERIVED — recomputed on every read — so a card TCGdex
# simply does not carry sits in Triage permanently, and a queue whose stated goal
# is zero has a floor it can never get under. The fix is a suppression inside the
# existing predicate, NOT a fourth reason: a new reason would keep the card in
# Triage, which is the opposite of the ask.

class TestNoCatalogMatch:
    """RFC 0011 §C — the stored answer a derived reason cannot hold."""

    def test_a_parked_item_leaves_the_missing_card_id_reason(self):
        from merlins_collection.services.triage import is_missing_card_id, reasons_for

        item = _raw(card_id=None, no_catalog_match=True)
        assert is_missing_card_id(item) is False
        assert "missing_card_id" not in reasons_for(item)

    def test_an_unparked_unlinked_item_still_has_the_reason(self):
        from merlins_collection.services.triage import is_missing_card_id

        assert is_missing_card_id(_raw(card_id=None)) is True

    def test_a_parked_item_with_no_other_problem_leaves_triage(self):
        """The whole point: the queue can now reach zero."""
        from merlins_collection.services.triage import needs_triage

        assert needs_triage(_raw(card_id=None, no_catalog_match=True)) is False

    def test_a_parked_item_that_is_also_flagged_stays_in_triage(self):
        """Parking answers ONE question. A human's flag is a different, real problem."""
        from merlins_collection.services.triage import needs_triage, reasons_for

        item = _raw(card_id=None, no_catalog_match=True, needs_review=True)
        assert needs_triage(item) is True
        assert reasons_for(item) == ["flagged"]

    def test_a_parked_jp_item_with_no_english_name_stays_in_triage(self):
        from merlins_collection.services.triage import reasons_for

        item = _raw(card_id=None, no_catalog_match=True,
                    language=Language.JP, display_name_override=None)
        assert "missing_english_name" in reasons_for(item)

    def test_a_sealed_item_is_unaffected_either_way(self):
        """Sealed product has no ``card_id`` attribute at all, so it was never in
        the reason and cannot be parked out of it."""
        from merlins_collection.services.triage import is_missing_card_id

        assert is_missing_card_id(_sealed()) is False

    def test_the_list_and_the_counts_agree_about_parked_items(self, admin_client):
        """One predicate, two consumers. A badge that counts differently from the
        list it links to is worse than no badge."""
        client, repo, admin, _ = admin_client
        repo.put_inventory_item(
            _raw(item_id="parked", card_id=None, no_catalog_match=True),
        )
        repo.put_inventory_item(_raw(item_id="open", card_id=None))

        listed = client.get(
            "/admin/inventory/search", params={"triage": "true"}, headers=_auth(admin),
        )
        counts = client.get("/admin/triage/counts", headers=_auth(admin))

        assert [i["item_id"] for i in listed.json()["items"]] == ["open"]
        assert counts.json()["total"] == 1
        assert counts.json()["reasons"]["missing_card_id"] == 1
