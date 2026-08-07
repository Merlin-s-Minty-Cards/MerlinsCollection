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
