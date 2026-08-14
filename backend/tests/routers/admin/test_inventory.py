"""Tests for the admin inventory CRUD router (``/admin/inventory/...``).

TDD RED: covers auth gate (403 for non-admin), full CRUD lifecycle, search
across all statuses, partial updates, soft/hard deletes, and item history.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from merlins_collection.models.business import Transaction, TransactionType, ItemCategory
from merlins_collection.models.catalog import CardImages, CatalogCard, FinishPrice
from merlins_collection.models.inventory import (
    Condition,
    ConditionModifier,
    GradedInventoryItem,
    GradingCompany,
    ItemStatus,
    RawInventoryItem,
    SealedInventoryItem,
    SealedProductType,
)


# ---- helpers ----

def _raw(card_id="sv1-1", *, item_id=None, condition=Condition.NM, finish="holofoil",
         location="glass", status=ItemStatus.AVAILABLE, cost_basis="10.00",
         current_market_value="50.00", **extra):
    kw = dict(
        card_id=card_id,
        finish=finish,
        condition=condition,
        location=location,
        status=status,
        cost_basis=Decimal(cost_basis),
        current_market_value=(
            None if current_market_value is None else Decimal(current_market_value)
        ),
        acquired_at=date(2025, 1, 1),
    )
    if item_id:
        kw["item_id"] = item_id
    kw.update(extra)
    return RawInventoryItem(**kw)


def _graded(card_id="sv1-2", *, item_id=None, status=ItemStatus.AVAILABLE,
            cost_basis="30.00", current_market_value="100.00", location="glass"):
    kw = dict(
        card_id=card_id,
        status=status,
        cost_basis=Decimal(cost_basis),
        current_market_value=Decimal(current_market_value),
        acquired_at=date(2025, 1, 1),
        company=GradingCompany.PSA,
        grade=Decimal("9"),
        cert_number="12345678",
        location=location,
    )
    if item_id:
        kw["item_id"] = item_id
    return GradedInventoryItem(**kw)


def _sealed(*, item_id=None, location="glass", status=ItemStatus.AVAILABLE):
    """A kind with NO ``card_id`` attribute at all — not a null one.

    Any filter that reaches for ``item.card_id`` directly raises
    ``AttributeError`` on the first sealed box and 500s the whole search.
    """
    kw = dict(
        product_name="Obsidian Flames ETB",
        product_type=SealedProductType.ETB,
        location=location,
        status=status,
        cost_basis=Decimal("40.00"),
        acquired_at=date(2025, 1, 1),
    )
    if item_id:
        kw["item_id"] = item_id
    return SealedInventoryItem(**kw)


def _catalog(card_id="sv1-1", name="Pikachu", **extra):
    defaults = dict(
        card_id=card_id,
        name=name,
        set_id="sv1",
        set_name="Scarlet & Violet",
        number="001",
        rarity="Common",
        images=CardImages(
            small="https://example.com/small.webp",
            large="https://example.com/large.webp",
        ),
        last_synced_at=datetime.now(tz=timezone.utc),
        prices={},
    )
    defaults.update(extra)
    return CatalogCard(**defaults)


# ---- fixtures ----

@pytest.fixture
def admin_client(cognito_config, jwks, dynamo_repo, mint_token):
    """Overrides the package fixture to add a NON-admin token as a 4th element.

    ``TestAdminAuthGate`` needs both sides of the gate — a token in the admin
    group and one without it — so this yields the pair. The wiring itself comes
    from ``conftest.build_admin_client``; only the token shape differs.
    """
    from .conftest import build_admin_client, clear_overrides

    client = build_admin_client(cognito_config, jwks, dynamo_repo)
    admin_token = mint_token(claims={"cognito:groups": ["admin"]})
    user_token = mint_token(claims={"cognito:groups": []})
    yield client, dynamo_repo, admin_token, user_token
    clear_overrides()


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ===========================================================================
# Auth gate tests
# ===========================================================================

class TestAdminAuthGate:
    """Admin endpoints must reject unauthenticated and non-admin users."""

    def test_unauthenticated_returns_401(self, admin_client):
        client, *_ = admin_client
        resp = client.get("/admin/health")
        assert resp.status_code == 401

    def test_non_admin_returns_403(self, admin_client):
        client, _, _, user_token = admin_client
        resp = client.get("/admin/health", headers=_auth_header(user_token))
        assert resp.status_code == 403

    def test_admin_passes(self, admin_client):
        client, _, admin_token, _ = admin_client
        resp = client.get("/admin/health", headers=_auth_header(admin_token))
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# ===========================================================================
# Admin Inventory Search
# ===========================================================================

class TestAdminInventorySearch:
    """GET /admin/inventory/search — all fields, all statuses, composable filters."""

    def test_returns_empty_when_no_items(self, admin_client):
        client, _, admin_token, _ = admin_client
        resp = client.get("/admin/inventory/search", headers=_auth_header(admin_token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_returns_all_statuses(self, admin_client):
        client, repo, admin_token, _ = admin_client
        repo.put_inventory_item(_raw(item_id="avail-1", status=ItemStatus.AVAILABLE))
        repo.put_inventory_item(_raw(item_id="sold-1", status=ItemStatus.SOLD))
        repo.put_inventory_item(_raw(item_id="lost-1", status=ItemStatus.LOST))

        resp = client.get("/admin/inventory/search", headers=_auth_header(admin_token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3

    def test_filter_by_status(self, admin_client):
        client, repo, admin_token, _ = admin_client
        repo.put_inventory_item(_raw(item_id="avail-1", status=ItemStatus.AVAILABLE))
        repo.put_inventory_item(_raw(item_id="sold-1", status=ItemStatus.SOLD))

        resp = client.get(
            "/admin/inventory/search?status=sold",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["item_id"] == "sold-1"

    def test_filter_by_name_substring(self, admin_client):
        client, repo, admin_token, _ = admin_client
        item = _raw(item_id="pika-1", display_name="Pikachu #25")
        repo.put_inventory_item(item)
        item2 = _raw(item_id="char-1", card_id="sv1-2", display_name="Charizard #4")
        repo.put_inventory_item(item2)

        resp = client.get(
            "/admin/inventory/search?name=pika",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["item_id"] == "pika-1"

    def test_filter_by_location(self, admin_client):
        client, repo, admin_token, _ = admin_client
        repo.put_inventory_item(_raw(item_id="glass-1", location="glass"))
        repo.put_inventory_item(_raw(item_id="binder-1", location="binder", card_id="sv1-2"))

        resp = client.get(
            "/admin/inventory/search?location=glass",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["item_id"] == "glass-1"

    def test_consignor_id_filter(self, admin_client):
        from merlins_collection.models.inventory import ConsignmentTerms

        client, repo, admin_token, _ = admin_client
        repo.put_inventory_item(_raw(item_id="owned-1"))
        consigned = _raw(item_id="consigned-1", card_id="sv1-2")
        consigned = consigned.model_copy(update={
            "consignment": ConsignmentTerms(
                consignor_id="cos-1", split_percent=Decimal("0.5"),
            ),
        })
        repo.put_inventory_item(consigned)

        resp = client.get(
            "/admin/inventory/search?consignor_id=cos-1",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["item_id"] == "consigned-1"

    def test_consignor_id_filter_matches_nothing_for_unknown_id_not_a_422(self, admin_client):
        client, repo, admin_token, _ = admin_client
        repo.put_inventory_item(_raw(item_id="owned-1"))

        resp = client.get(
            "/admin/inventory/search?consignor_id=no-such-cosigner",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert resp.json()["items"] == []

    def test_includes_cost_basis_in_response(self, admin_client):
        """Admin search MUST expose internal fields like cost_basis."""
        client, repo, admin_token, _ = admin_client
        repo.put_inventory_item(_raw(item_id="item-1", cost_basis="42.50"))

        resp = client.get("/admin/inventory/search", headers=_auth_header(admin_token))
        assert resp.status_code == 200
        item = resp.json()["items"][0]
        assert item["cost_basis"] == "42.50"

    def test_sort_by_price_desc(self, admin_client):
        client, repo, admin_token, _ = admin_client
        repo.put_inventory_item(
            _raw(item_id="cheap", current_market_value="10.00")
        )
        repo.put_inventory_item(
            _raw(item_id="expensive", card_id="sv1-2", current_market_value="100.00")
        )

        resp = client.get(
            "/admin/inventory/search?sort=price_desc",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert items[0]["item_id"] == "expensive"
        assert items[1]["item_id"] == "cheap"

    def test_sort_by_price_asc(self, admin_client):
        client, repo, admin_token, _ = admin_client
        repo.put_inventory_item(
            _raw(item_id="cheap", current_market_value="10.00")
        )
        repo.put_inventory_item(
            _raw(item_id="expensive", card_id="sv1-2", current_market_value="100.00")
        )

        resp = client.get(
            "/admin/inventory/search?sort=price_asc",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert items[0]["item_id"] == "cheap"
        assert items[1]["item_id"] == "expensive"

    # --- RFC 0011 T1: every column sorts, and an unknown one is LOUD -------

    def test_unknown_sort_field_is_a_422(self, admin_client):
        """A silently-unsorted list is indistinguishable from a column with no order.

        Before RFC 0011 this returned 200 and the table's natural order, which is why
        twenty-five dead headers went unnoticed.
        """
        client, _, admin_token, _ = admin_client

        resp = client.get(
            "/admin/inventory/search?sort=wibble_asc",
            headers=_auth_header(admin_token),
        )

        assert resp.status_code == 422
        assert "wibble_asc" in resp.json()["detail"]

    def test_unknown_sort_direction_is_a_422(self, admin_client):
        client, _, admin_token, _ = admin_client

        resp = client.get(
            "/admin/inventory/search?sort=cost_basis_sideways",
            headers=_auth_header(admin_token),
        )

        assert resp.status_code == 422

    def test_a_previously_unsortable_column_now_sorts(self, admin_client):
        """`notes` was one of the twenty-five that fell through to `return ""`."""
        client, repo, admin_token, _ = admin_client
        repo.put_inventory_item(_raw(item_id="zulu", notes="zulu"))
        repo.put_inventory_item(_raw(item_id="alpha", card_id="sv1-2", notes="alpha"))

        resp = client.get(
            "/admin/inventory/search?sort=notes_asc",
            headers=_auth_header(admin_token),
        )

        assert resp.status_code == 200
        assert [i["item_id"] for i in resp.json()["items"]] == ["alpha", "zulu"]

    def test_rows_with_no_value_sort_last_in_both_directions(self, admin_client):
        """The generalized missing-last rule, end to end through the endpoint."""
        client, repo, admin_token, _ = admin_client
        repo.put_inventory_item(_raw(item_id="has", notes="alpha"))
        repo.put_inventory_item(_raw(item_id="blank", card_id="sv1-2", notes=None))

        for direction in ("asc", "desc"):
            resp = client.get(
                f"/admin/inventory/search?sort=notes_{direction}",
                headers=_auth_header(admin_token),
            )
            assert [i["item_id"] for i in resp.json()["items"]][-1] == "blank"

    # --- RFC 0011 T3: the generic filter layer ----------------------------

    def test_unknown_filter_field_is_a_422(self, admin_client):
        client, _, admin_token, _ = admin_client

        resp = client.get(
            "/admin/inventory/search?filter=wibble:eq:x",
            headers=_auth_header(admin_token),
        )

        assert resp.status_code == 422
        assert "wibble" in resp.json()["detail"]

    def test_an_op_the_field_does_not_support_is_a_422(self, admin_client):
        """`status` is a select. `contains` on it is a caller mistake, not a wider
        match — the whole point of a closed list is that you pick from it."""
        client, _, admin_token, _ = admin_client

        resp = client.get(
            "/admin/inventory/search?filter=status:contains:avail",
            headers=_auth_header(admin_token),
        )

        assert resp.status_code == 422

    def test_an_unparseable_bound_is_a_422(self, admin_client):
        """Silently dropping every row looks exactly like "you own nothing"."""
        client, _, admin_token, _ = admin_client

        resp = client.get(
            "/admin/inventory/search?filter=acquired_at:gte:yesterday",
            headers=_auth_header(admin_token),
        )

        assert resp.status_code == 422

    def test_a_generic_filter_narrows(self, admin_client):
        client, repo, admin_token, _ = admin_client
        repo.put_inventory_item(_raw(item_id="foil", notes="signed FOIL promo"))
        repo.put_inventory_item(_raw(item_id="plain", card_id="sv1-2", notes="ordinary"))

        resp = client.get(
            "/admin/inventory/search?filter=notes:contains:foil",
            headers=_auth_header(admin_token),
        )

        assert [i["item_id"] for i in resp.json()["items"]] == ["foil"]

    def test_generic_filters_and_combine(self, admin_client):
        client, repo, admin_token, _ = admin_client
        repo.put_inventory_item(
            _raw(item_id="both", notes="foil", cost_basis="50.00")
        )
        repo.put_inventory_item(
            _raw(item_id="cheap", card_id="sv1-2", notes="foil", cost_basis="5.00")
        )

        resp = client.get(
            "/admin/inventory/search"
            "?filter=notes:contains:foil&filter=cost_basis:gte:10",
            headers=_auth_header(admin_token),
        )

        assert [i["item_id"] for i in resp.json()["items"]] == ["both"]

    def test_the_named_param_and_its_generic_twin_agree(self, admin_client):
        """ONE evaluator, two spellings.

        Two IMPLEMENTATIONS is the "two definitions of countability" failure CLAUDE.md
        warns about under the ledger: one drifts, and two filters that look identical
        quietly return different sets.
        """
        client, repo, admin_token, _ = admin_client
        repo.put_inventory_item(_raw(item_id="owned"))
        repo.put_inventory_item(
            _raw(item_id="consigned", card_id="sv1-2",
                 consignment={"consignor_id": "c1", "split_percent": "0.8"})
        )

        named = client.get(
            "/admin/inventory/search?ownership=owned",
            headers=_auth_header(admin_token),
        )
        generic = client.get(
            "/admin/inventory/search?filter=consignment:isnull:",
            headers=_auth_header(admin_token),
        )

        assert named.status_code == generic.status_code == 200
        assert (
            [i["item_id"] for i in named.json()["items"]]
            == [i["item_id"] for i in generic.json()["items"]]
            == ["owned"]
        )

    def test_a_generic_filter_combines_with_a_named_one(self, admin_client):
        """An admin using both gets the intersection, not one silently winning."""
        client, repo, admin_token, _ = admin_client
        repo.put_inventory_item(
            _raw(item_id="match", status="available", notes="foil")
        )
        repo.put_inventory_item(
            _raw(item_id="sold_foil", card_id="sv1-2", status="sold", notes="foil")
        )

        resp = client.get(
            "/admin/inventory/search?status=available&filter=notes:contains:foil",
            headers=_auth_header(admin_token),
        )

        assert [i["item_id"] for i in resp.json()["items"]] == ["match"]

    def test_the_card_link_filter_answers_the_unlinked_question(self, admin_client):
        """`card_id` is a presence control, not a text box — nobody types an id."""
        client, repo, admin_token, _ = admin_client
        repo.put_inventory_item(_raw(item_id="linked", card_id="sv1-2"))
        repo.put_inventory_item(_raw(item_id="unlinked", card_id=None))

        resp = client.get(
            "/admin/inventory/search?filter=card_id:isnull:",
            headers=_auth_header(admin_token),
        )

        assert [i["item_id"] for i in resp.json()["items"]] == ["unlinked"]


# ===========================================================================
# A5: Enhanced Inventory Search — card_number, artist, min/max price
# ===========================================================================

class TestAdminInventorySearchEnhanced:
    """A5: Additional filter params for admin inventory search."""

    def test_filter_by_card_number(self, admin_client):
        """card_number filters by matching the catalog card's number field."""
        client, repo, admin_token, _ = admin_client
        # Create catalog cards with different numbers
        repo.batch_upsert_catalog_cards([
            _catalog(card_id="sv1-25", name="Pikachu", number="025"),
            _catalog(card_id="sv1-4", name="Charizard", number="004"),
        ])
        repo.put_inventory_item(_raw(item_id="pika-1", card_id="sv1-25"))
        repo.put_inventory_item(_raw(item_id="char-1", card_id="sv1-4"))

        resp = client.get(
            "/admin/inventory/search?card_number=025",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["item_id"] == "pika-1"

    def test_filter_by_artist(self, admin_client):
        """artist filters by case-insensitive substring on catalog artist field."""
        client, repo, admin_token, _ = admin_client
        repo.batch_upsert_catalog_cards([
            _catalog(card_id="sv1-25", name="Pikachu", number="025", artist="Mitsuhiro Arita"),
            _catalog(card_id="sv1-4", name="Charizard", number="004", artist="Ken Sugimori"),
        ])
        repo.put_inventory_item(_raw(item_id="pika-1", card_id="sv1-25"))
        repo.put_inventory_item(_raw(item_id="char-1", card_id="sv1-4"))

        resp = client.get(
            "/admin/inventory/search?artist=arita",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["item_id"] == "pika-1"

    def test_filter_by_artist_partial_match(self, admin_client):
        """artist substring match works with partial names."""
        client, repo, admin_token, _ = admin_client
        repo.batch_upsert_catalog_cards([
            _catalog(card_id="sv1-25", name="Pikachu", number="025", artist="Mitsuhiro Arita"),
            _catalog(card_id="sv1-4", name="Charizard", number="004", artist="Ken Sugimori"),
        ])
        repo.put_inventory_item(_raw(item_id="pika-1", card_id="sv1-25"))
        repo.put_inventory_item(_raw(item_id="char-1", card_id="sv1-4"))

        resp = client.get(
            "/admin/inventory/search?artist=sugi",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["item_id"] == "char-1"

    def test_filter_by_min_price(self, admin_client):
        """min_price filters by cost_basis when no market value is known."""
        client, repo, admin_token, _ = admin_client
        repo.put_inventory_item(_raw(item_id="cheap-1", cost_basis="5.00",
                                     current_market_value=None))
        repo.put_inventory_item(_raw(item_id="mid-1", card_id="sv1-2", cost_basis="25.00",
                                     current_market_value=None))
        repo.put_inventory_item(_raw(item_id="exp-1", card_id="sv1-3", cost_basis="100.00",
                                     current_market_value=None))

        resp = client.get(
            "/admin/inventory/search?min_price=20",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        ids = {i["item_id"] for i in data["items"]}
        assert ids == {"mid-1", "exp-1"}

    def test_filter_by_max_price(self, admin_client):
        """max_price filters by cost_basis when no market value is known."""
        client, repo, admin_token, _ = admin_client
        repo.put_inventory_item(_raw(item_id="cheap-1", cost_basis="5.00",
                                     current_market_value=None))
        repo.put_inventory_item(_raw(item_id="mid-1", card_id="sv1-2", cost_basis="25.00",
                                     current_market_value=None))
        repo.put_inventory_item(_raw(item_id="exp-1", card_id="sv1-3", cost_basis="100.00",
                                     current_market_value=None))

        resp = client.get(
            "/admin/inventory/search?max_price=30",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        ids = {i["item_id"] for i in data["items"]}
        assert ids == {"cheap-1", "mid-1"}

    def test_filter_by_price_range(self, admin_client):
        """min_price + max_price combined to form a range."""
        client, repo, admin_token, _ = admin_client
        repo.put_inventory_item(_raw(item_id="cheap-1", cost_basis="5.00",
                                     current_market_value=None))
        repo.put_inventory_item(_raw(item_id="mid-1", card_id="sv1-2", cost_basis="25.00",
                                     current_market_value=None))
        repo.put_inventory_item(_raw(item_id="exp-1", card_id="sv1-3", cost_basis="100.00",
                                     current_market_value=None))

        resp = client.get(
            "/admin/inventory/search?min_price=10&max_price=50",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["item_id"] == "mid-1"

    def test_filters_combine_with_and(self, admin_client):
        """Multiple enhanced filters are AND-combined with existing ones."""
        client, repo, admin_token, _ = admin_client
        repo.batch_upsert_catalog_cards([
            _catalog(card_id="sv1-25", name="Pikachu", number="025", artist="Mitsuhiro Arita"),
            _catalog(card_id="sv1-4", name="Charizard", number="004", artist="Mitsuhiro Arita"),
        ])
        repo.put_inventory_item(_raw(item_id="pika-1", card_id="sv1-25", cost_basis="10.00",
                                     current_market_value=None))
        repo.put_inventory_item(_raw(item_id="char-1", card_id="sv1-4", cost_basis="50.00",
                                     current_market_value=None))

        # Filter: artist=arita AND min_price=20 — should only get charizard
        resp = client.get(
            "/admin/inventory/search?artist=arita&min_price=20",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["item_id"] == "char-1"

    def test_card_number_no_catalog_match_excluded(self, admin_client):
        """Items without a card_id or without catalog card are excluded by card_number filter."""
        client, repo, admin_token, _ = admin_client
        # Item with no card_id (sealed)
        from merlins_collection.models.inventory import SealedInventoryItem, SealedProductType
        sealed = SealedInventoryItem(
            item_id="sealed-1",
            product_name="ETB",
            product_type=SealedProductType.ETB,
            cost_basis=Decimal("40.00"),
            acquired_at=date(2025, 1, 1),
        )
        repo.put_inventory_item(sealed)
        # Item with card_id but matching number
        repo.batch_upsert_catalog_cards([
            _catalog(card_id="sv1-25", name="Pikachu", number="025"),
        ])
        repo.put_inventory_item(_raw(item_id="pika-1", card_id="sv1-25"))

        resp = client.get(
            "/admin/inventory/search?card_number=025",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["item_id"] == "pika-1"


# ===========================================================================
# Get single item
# ===========================================================================

class TestAdminGetItem:
    """GET /admin/inventory/{item_id}"""

    def test_get_existing_item(self, admin_client):
        client, repo, admin_token, _ = admin_client
        repo.put_inventory_item(_raw(item_id="item-42"))

        resp = client.get(
            "/admin/inventory/item-42", headers=_auth_header(admin_token)
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["item_id"] == "item-42"
        assert "cost_basis" in data  # admin sees internal fields

    def test_get_nonexistent_returns_404(self, admin_client):
        client, _, admin_token, _ = admin_client
        resp = client.get(
            "/admin/inventory/does-not-exist", headers=_auth_header(admin_token)
        )
        assert resp.status_code == 404


# ===========================================================================
# Create item
# ===========================================================================

class TestAdminCreateItem:
    """POST /admin/inventory"""

    def test_create_raw_item(self, admin_client):
        client, repo, admin_token, _ = admin_client
        payload = {
            "kind": "raw",
            "card_id": "sv1-1",
            "finish": "holofoil",
            "condition": "NM",
            "cost_basis": "25.00",
            "acquired_at": "2025-01-15",
            "location": "toploader",
        }
        resp = client.post(
            "/admin/inventory",
            json=payload,
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["kind"] == "raw"
        assert data["card_id"] == "sv1-1"
        assert "item_id" in data

        # Verify persisted
        stored = repo.get_inventory_item(data["item_id"])
        assert stored is not None
        assert stored.cost_basis == Decimal("25.00")

    def test_create_sealed_item(self, admin_client):
        client, repo, admin_token, _ = admin_client
        payload = {
            "kind": "sealed",
            "product_name": "Scarlet & Violet Booster Box",
            "product_type": "booster_box",
            "cost_basis": "120.00",
            "acquired_at": "2025-01-15",
            "location": "storage",
        }
        resp = client.post(
            "/admin/inventory",
            json=payload,
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["kind"] == "sealed"
        assert data["product_name"] == "Scarlet & Violet Booster Box"

    def test_create_rejects_invalid_kind(self, admin_client):
        client, _, admin_token, _ = admin_client
        payload = {
            "kind": "invalid",
            "cost_basis": "10.00",
            "acquired_at": "2025-01-15",
        }
        resp = client.post(
            "/admin/inventory",
            json=payload,
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 422


# ===========================================================================
# Update item
# ===========================================================================

class TestAdminUpdateItem:
    """PUT /admin/inventory/{item_id}"""

    def test_partial_update_location(self, admin_client):
        client, repo, admin_token, _ = admin_client
        repo.put_inventory_item(_raw(item_id="item-1", location="toploader"))

        resp = client.put(
            "/admin/inventory/item-1",
            json={"location": "glass"},
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["location"] == "glass"

        # Verify in DB
        stored = repo.get_inventory_item("item-1")
        assert stored.location == "glass"

    def test_partial_update_condition(self, admin_client):
        client, repo, admin_token, _ = admin_client
        repo.put_inventory_item(_raw(item_id="item-1", condition=Condition.NM))

        resp = client.put(
            "/admin/inventory/item-1",
            json={"condition": "LP", "notes": "Found corner wear"},
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        stored = repo.get_inventory_item("item-1")
        assert stored.condition == Condition.LP
        assert stored.notes == "Found corner wear"

    def test_update_nonexistent_returns_404(self, admin_client):
        client, _, admin_token, _ = admin_client
        resp = client.put(
            "/admin/inventory/no-such-id",
            json={"location": "glass"},
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 404

    def test_update_status(self, admin_client):
        client, repo, admin_token, _ = admin_client
        repo.put_inventory_item(_raw(item_id="item-1", status=ItemStatus.AVAILABLE))

        resp = client.put(
            "/admin/inventory/item-1",
            json={"status": "on_hold"},
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        stored = repo.get_inventory_item("item-1")
        assert stored.status == ItemStatus.ON_HOLD

    def test_update_writes_audit_timeline_event(self, admin_client):
        """A manual field edit must write an 'edit' timeline event with old/new values."""
        client, repo, admin_token, _ = admin_client
        repo.put_inventory_item(_raw(item_id="item-1", location="toploader", cost_basis="10.00"))

        resp = client.put(
            "/admin/inventory/item-1",
            json={"location": "glass", "cost_basis": "15.00"},
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200

        events = repo.get_timeline_events("item-1")
        edit_events = [e for e in events if e.get("type") == "edit"]
        assert len(edit_events) == 1
        changed = edit_events[0]["changed_fields"]
        assert changed["location"] == {"old": "toploader", "new": "glass"}
        assert changed["cost_basis"] == {"old": "10.00", "new": "15.00"}

    # ---- T10: display_name_override, admin-authored customer-facing name ----
    # docs/plans/rfc-0008/t10-jp-english-names.md. The update handler merges the
    # whole body into the validated model (no per-field allowlist), so these
    # pin the field's WRITABILITY as an endpoint contract rather than a model
    # detail — a future allowlist there would break the admin UI silently.

    def test_update_sets_display_name_override(self, admin_client):
        client, repo, admin_token, _ = admin_client
        repo.put_inventory_item(_raw(card_id="ja:M4-084", item_id="item-jp"))

        resp = client.put(
            "/admin/inventory/item-jp",
            json={"display_name_override": "Chespin"},
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert resp.json()["display_name_override"] == "Chespin"
        assert repo.get_inventory_item("item-jp").display_name_override == "Chespin"

    def test_update_does_not_touch_card_id_when_setting_the_override(self, admin_client):
        """Owner requirement: editing the displayed name must never be able to
        break the item's link to its catalog card."""
        client, repo, admin_token, _ = admin_client
        repo.put_inventory_item(_raw(card_id="ja:M4-084", item_id="item-jp"))

        client.put(
            "/admin/inventory/item-jp",
            json={"display_name_override": "Chespin"},
            headers=_auth_header(admin_token),
        )
        assert repo.get_inventory_item("item-jp").card_id == "ja:M4-084"

    def test_update_with_empty_override_clears_it(self, admin_client):
        """Clearing the input box sends "" and must remove the override, letting
        the catalog name take over again — not store a blank name."""
        client, repo, admin_token, _ = admin_client
        repo.put_inventory_item(
            _raw(item_id="item-jp", display_name_override="Chespin"))

        resp = client.put(
            "/admin/inventory/item-jp",
            json={"display_name_override": "   "},
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert repo.get_inventory_item("item-jp").display_name_override is None

    def test_update_rejects_over_length_display_name_override(self, admin_client):
        client, repo, admin_token, _ = admin_client
        repo.put_inventory_item(_raw(item_id="item-jp"))

        resp = client.put(
            "/admin/inventory/item-jp",
            json={"display_name_override": "x" * 201},
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 422
        assert repo.get_inventory_item("item-jp").display_name_override is None

    def test_update_with_no_actual_change_writes_no_edit_event(self, admin_client):
        """Re-submitting the same value must not spam the audit trail."""
        client, repo, admin_token, _ = admin_client
        repo.put_inventory_item(_raw(item_id="item-1", location="glass"))

        resp = client.put(
            "/admin/inventory/item-1",
            json={"location": "glass"},
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        events = [e for e in repo.get_timeline_events("item-1") if e.get("type") == "edit"]
        assert events == []

    def test_timeline_endpoint_returns_changed_fields_for_edit_events(self, admin_client):
        client, repo, admin_token, _ = admin_client
        repo.put_inventory_item(_raw(item_id="item-1", location="toploader"))
        client.put("/admin/inventory/item-1", json={"location": "glass"}, headers=_auth_header(admin_token))

        resp = client.get("/admin/inventory/item-1/timeline", headers=_auth_header(admin_token))
        assert resp.status_code == 200
        events = resp.json()["events"]
        edit_events = [e for e in events if e["type"] == "edit"]
        assert len(edit_events) == 1
        assert edit_events[0]["changed_fields"]["location"] == {"old": "toploader", "new": "glass"}

    def test_unknown_key_in_body_writes_no_spurious_audit_entry(self, admin_client):
        """A typo'd/unknown key that Pydantic's ``extra='ignore'`` silently
        drops must not show up in the audit trail as a change that never
        actually happened to the stored item (finding 7a)."""
        client, repo, admin_token, _ = admin_client
        repo.put_inventory_item(_raw(item_id="item-1", location="glass"))

        resp = client.put(
            "/admin/inventory/item-1",
            json={"locaton": "toploader"},  # typo — not a real field
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        stored = repo.get_inventory_item("item-1")
        assert stored.location == "glass"  # untouched — the typo'd key was ignored

        events = [e for e in repo.get_timeline_events("item-1") if e.get("type") == "edit"]
        assert events == []

    def test_equal_value_in_different_literal_form_writes_no_spurious_diff(self, admin_client):
        """Re-typing ``cost_basis`` as ``"10.0"`` against a stored ``"10.00"``
        is the same value and must not show as a changed field (finding 7b)."""
        client, repo, admin_token, _ = admin_client
        repo.put_inventory_item(_raw(item_id="item-1", cost_basis="10.00"))

        resp = client.put(
            "/admin/inventory/item-1",
            json={"cost_basis": "10.0"},
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        events = [e for e in repo.get_timeline_events("item-1") if e.get("type") == "edit"]
        assert events == []


# ===========================================================================
# Delete item
# ===========================================================================

class TestAdminDeleteItem:
    """DELETE /admin/inventory/{item_id}"""

    def test_soft_delete_default(self, admin_client):
        """Default delete sets status to LOST (soft delete)."""
        client, repo, admin_token, _ = admin_client
        repo.put_inventory_item(_raw(item_id="item-1"))

        resp = client.delete(
            "/admin/inventory/item-1",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        stored = repo.get_inventory_item("item-1")
        assert stored is not None
        assert stored.status == ItemStatus.LOST

    def test_hard_delete(self, admin_client):
        """hard=true permanently removes the item."""
        client, repo, admin_token, _ = admin_client
        repo.put_inventory_item(_raw(item_id="item-1"))

        resp = client.delete(
            "/admin/inventory/item-1?hard=true",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        stored = repo.get_inventory_item("item-1")
        assert stored is None

    def test_delete_nonexistent_returns_404(self, admin_client):
        client, _, admin_token, _ = admin_client
        resp = client.delete(
            "/admin/inventory/does-not-exist",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 404


# ===========================================================================
# Item history
# ===========================================================================

class TestAdminItemHistory:
    """GET /admin/inventory/{item_id}/history"""

    def test_returns_price_history(self, admin_client):
        client, repo, admin_token, _ = admin_client
        repo.put_inventory_item(_raw(item_id="item-1"))
        # Add price points
        repo.append_item_price_point("item-1", date(2025, 1, 1), Decimal("40.00"))
        repo.append_item_price_point("item-1", date(2025, 1, 15), Decimal("55.00"))

        resp = client.get(
            "/admin/inventory/item-1/history",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "price_history" in data
        assert len(data["price_history"]) == 2

    def test_returns_transactions(self, admin_client):
        client, repo, admin_token, _ = admin_client
        repo.put_inventory_item(_raw(item_id="item-1"))
        today = date.today()
        txn = Transaction(
            type=TransactionType.SALE,
            item_id="item-1",
            category=ItemCategory.RAW,
            date=today,
            amount=Decimal("75.00"),
            payment_method="cash",
        )
        repo.put_transaction(txn)

        resp = client.get(
            "/admin/inventory/item-1/history",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "transactions" in data
        assert len(data["transactions"]) >= 1
        assert data["transactions"][0]["item_id"] == "item-1"

    def test_history_nonexistent_item_returns_404(self, admin_client):
        client, _, admin_token, _ = admin_client
        resp = client.get(
            "/admin/inventory/no-item/history",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 404


# ===========================================================================
# Price chart endpoint tests
# ===========================================================================

class TestAdminPriceChart:
    """GET /admin/inventory/{item_id}/price-chart"""

    def test_returns_item_level_history_for_sealed(self, admin_client):
        """Sealed items use item-level price points."""
        from datetime import timedelta

        client, repo, admin_token, _ = admin_client
        today = date.today()
        item = SealedInventoryItem(
            item_id="sealed-1",
            product_name="Scarlet & Violet ETB",
            product_type=SealedProductType.ETB,
            cost_basis=Decimal("40.00"),
            acquired_at=date(2025, 1, 1),
            current_market_value=Decimal("55.00"),
        )
        repo.put_inventory_item(item)
        repo.append_item_price_point(
            "sealed-1", today - timedelta(days=60), Decimal("45.00")
        )
        repo.append_item_price_point(
            "sealed-1", today - timedelta(days=10), Decimal("55.00")
        )

        resp = client.get(
            "/admin/inventory/sealed-1/price-chart?timeframe=1yr",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["item_id"] == "sealed-1"
        assert data["timeframe"] == "1yr"
        assert len(data["points"]) == 2
        assert data["points"][0]["market_value"] == "45.00"

    def test_returns_card_level_history_for_raw(self, admin_client):
        """Raw items with card_id use card-level price history."""
        from datetime import timedelta
        from merlins_collection.models.catalog import PricePoint

        client, repo, admin_token, _ = admin_client
        today = date.today()
        repo.put_inventory_item(_raw(item_id="raw-1", card_id="sv1-1"))
        # Seed card-level price points (recent dates)
        repo.append_price_points([
            PricePoint(
                card_id="sv1-1", date=today - timedelta(days=30),
                source="tcgplayer",
                kind="raw", finish="holofoil", market=Decimal("50.00"),
            ),
            PricePoint(
                card_id="sv1-1", date=today - timedelta(days=10),
                source="tcgplayer",
                kind="raw", finish="holofoil", market=Decimal("60.00"),
            ),
        ])

        resp = client.get(
            "/admin/inventory/raw-1/price-chart?timeframe=1yr",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["points"]) == 2
        assert data["points"][0]["market_value"] == "50.00"
        assert data["points"][1]["market_value"] == "60.00"

    def test_returns_card_level_history_for_graded(self, admin_client):
        """Graded items with card_id use card-level price history (company+grade)."""
        from datetime import timedelta
        from merlins_collection.models.catalog import PricePoint

        client, repo, admin_token, _ = admin_client
        today = date.today()
        repo.put_inventory_item(_graded(item_id="graded-1", card_id="sv1-2"))
        # Seed graded price points (PSA 9, recent dates)
        repo.append_price_points([
            PricePoint(
                card_id="sv1-2", date=today - timedelta(days=30),
                source="manual",
                kind="graded", company="PSA", grade=Decimal("9"),
                market=Decimal("100.00"),
            ),
            PricePoint(
                card_id="sv1-2", date=today - timedelta(days=10),
                source="manual",
                kind="graded", company="PSA", grade=Decimal("9"),
                market=Decimal("120.00"),
            ),
        ])

        resp = client.get(
            "/admin/inventory/graded-1/price-chart?timeframe=1yr",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["points"]) == 2
        assert data["points"][0]["market_value"] == "100.00"

    def test_buy_marker_included(self, admin_client):
        """Response includes buy_marker from cost_basis + acquired_at."""
        client, repo, admin_token, _ = admin_client
        repo.put_inventory_item(_raw(
            item_id="raw-2", cost_basis="15.00",
        ))

        resp = client.get(
            "/admin/inventory/raw-2/price-chart?timeframe=2yr",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["buy_marker"] is not None
        assert data["buy_marker"]["date"] == "2025-01-01"
        assert data["buy_marker"]["price"] == "15.00"

    def test_timeframe_filters_old_points(self, admin_client):
        """Points older than the timeframe cutoff are excluded."""
        from datetime import timedelta

        client, repo, admin_token, _ = admin_client
        item = SealedInventoryItem(
            item_id="sealed-2",
            product_name="Obsidian Flames BB",
            product_type=SealedProductType.BOOSTER_BOX,
            cost_basis=Decimal("100.00"),
            acquired_at=date(2023, 1, 1),
            current_market_value=Decimal("130.00"),
        )
        repo.put_inventory_item(item)
        today = date.today()
        # One recent point (within 1mo)
        repo.append_item_price_point(
            "sealed-2", today - timedelta(days=10), Decimal("125.00")
        )
        # One old point (over 1mo ago)
        repo.append_item_price_point(
            "sealed-2", today - timedelta(days=60), Decimal("110.00")
        )

        resp = client.get(
            "/admin/inventory/sealed-2/price-chart?timeframe=1mo",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        # Only the recent point should be in range
        assert len(data["points"]) == 1
        assert data["points"][0]["market_value"] == "125.00"

    def test_nonexistent_item_returns_404(self, admin_client):
        client, _, admin_token, _ = admin_client
        resp = client.get(
            "/admin/inventory/no-item/price-chart",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 404

    def test_invalid_timeframe_returns_422(self, admin_client):
        """Invalid timeframe param is rejected by validation."""
        client, repo, admin_token, _ = admin_client
        repo.put_inventory_item(_raw(item_id="raw-3"))

        resp = client.get(
            "/admin/inventory/raw-3/price-chart?timeframe=5yr",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 422


# ===========================================================================
# 2.3: LP± search, set_name / ownership / missing_sticker filters,
#      market-aware price range, combined condition writes, lineage profit,
#      unified price refresh.
# ===========================================================================

class TestAdminInventorySearch23:
    """New/changed GET /admin/inventory/search filters (Task 2.3)."""

    def test_search_condition_accepts_modifier(self, admin_client):
        """``LP`` matches every LP-tier item; ``LP+`` matches only LP/+ items."""
        client, repo, admin_token, _ = admin_client
        repo.put_inventory_item(_raw(item_id="lp-plus", condition=Condition.LP,
                                     condition_modifier=ConditionModifier.PLUS))
        repo.put_inventory_item(_raw(item_id="lp-plain", card_id="sv1-2",
                                     condition=Condition.LP))
        repo.put_inventory_item(_raw(item_id="lp-minus", card_id="sv1-3",
                                     condition=Condition.LP,
                                     condition_modifier=ConditionModifier.MINUS))
        repo.put_inventory_item(_raw(item_id="nm-1", card_id="sv1-4",
                                     condition=Condition.NM))

        resp = client.get("/admin/inventory/search?condition=LP",
                          headers=_auth_header(admin_token))
        assert resp.status_code == 200
        assert {i["item_id"] for i in resp.json()["items"]} == {
            "lp-plus", "lp-plain", "lp-minus",
        }

        resp = client.get("/admin/inventory/search?condition=LP%2B",
                          headers=_auth_header(admin_token))
        assert resp.status_code == 200
        assert {i["item_id"] for i in resp.json()["items"]} == {"lp-plus"}

        resp = client.get("/admin/inventory/search?condition=LP-",
                          headers=_auth_header(admin_token))
        assert resp.status_code == 200
        assert {i["item_id"] for i in resp.json()["items"]} == {"lp-minus"}

    def test_search_condition_rejects_garbage(self, admin_client):
        client, _, admin_token, _ = admin_client
        resp = client.get("/admin/inventory/search?condition=SHINY",
                          headers=_auth_header(admin_token))
        assert resp.status_code == 422

    def test_search_by_set_name(self, admin_client):
        """set_name is a case-insensitive substring on the CATALOG set_name."""
        client, repo, admin_token, _ = admin_client
        repo.batch_upsert_catalog_cards([
            _catalog(card_id="sv1-25", name="Pikachu", number="025",
                     set_id="sv1", set_name="Scarlet & Violet"),
            _catalog(card_id="swsh7-1", name="Umbreon", number="001",
                     set_id="swsh7", set_name="Evolving Skies"),
        ])
        repo.put_inventory_item(_raw(item_id="pika-1", card_id="sv1-25"))
        repo.put_inventory_item(_raw(item_id="umb-1", card_id="swsh7-1"))

        resp = client.get("/admin/inventory/search?set_name=evolving",
                          headers=_auth_header(admin_token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["item_id"] == "umb-1"

    def test_search_by_set_id(self, admin_client):
        """T8: the combobox selects a SET, not a name substring.

        ``set_name`` cannot express the selection the combobox makes. Names are
        not unique across languages (``en:base1`` and ``ja:base1`` are both
        "Base Set") and a substring like "Sun & Moon" catches a dozen sets, so
        picking one entry from a list and getting several sets back is the exact
        failure the dropdown exists to remove. Resolved through the GSI1 ``SET#``
        partition, which is a query — not the catalog walk ``set_name`` does.
        """
        client, repo, admin_token, _ = admin_client
        repo.batch_upsert_catalog_cards([
            _catalog(card_id="sv1-25", name="Pikachu", number="025",
                     set_id="sv1", set_name="Scarlet & Violet"),
            _catalog(card_id="swsh7-1", name="Umbreon", number="001",
                     set_id="swsh7", set_name="Evolving Skies"),
        ])
        repo.put_inventory_item(_raw(item_id="pika-1", card_id="sv1-25"))
        repo.put_inventory_item(_raw(item_id="umb-1", card_id="swsh7-1"))

        resp = client.get("/admin/inventory/search?set_id=swsh7",
                          headers=_auth_header(admin_token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["item_id"] == "umb-1"

    def test_search_by_set_id_excludes_unlinked_items(self, admin_client):
        """An item with no catalog link belongs to no set, including sealed
        products, which have no ``card_id`` field at all rather than a null one."""
        client, repo, admin_token, _ = admin_client
        repo.batch_upsert_catalog_cards([
            _catalog(card_id="sv1-25", name="Pikachu", number="025",
                     set_id="sv1", set_name="Scarlet & Violet"),
        ])
        repo.put_inventory_item(_raw(item_id="pika-1", card_id="sv1-25"))
        repo.put_inventory_item(_sealed(item_id="etb-1"))

        resp = client.get("/admin/inventory/search?set_id=sv1",
                          headers=_auth_header(admin_token))
        assert resp.status_code == 200
        assert [i["item_id"] for i in resp.json()["items"]] == ["pika-1"]

    def test_search_ownership_filter(self, admin_client):
        from merlins_collection.models.inventory import ConsignmentTerms

        client, repo, admin_token, _ = admin_client
        repo.put_inventory_item(_raw(item_id="owned-1"))
        repo.put_inventory_item(_raw(
            item_id="cosigned-1", card_id="sv1-2",
            consignment=ConsignmentTerms(consignor_id="c-1",
                                         split_percent=Decimal("0.20")),
        ))

        resp = client.get("/admin/inventory/search?ownership=owned",
                          headers=_auth_header(admin_token))
        assert resp.status_code == 200
        assert [i["item_id"] for i in resp.json()["items"]] == ["owned-1"]

        resp = client.get("/admin/inventory/search?ownership=cosigned",
                          headers=_auth_header(admin_token))
        assert resp.status_code == 200
        assert [i["item_id"] for i in resp.json()["items"]] == ["cosigned-1"]

        resp = client.get("/admin/inventory/search?ownership=borrowed",
                          headers=_auth_header(admin_token))
        assert resp.status_code == 422

    def test_search_missing_sticker(self, admin_client):
        """missing_sticker=true is the show-prep queue: sticker_price is null."""
        client, repo, admin_token, _ = admin_client
        repo.put_inventory_item(_raw(item_id="no-sticker"))
        repo.put_inventory_item(_raw(item_id="has-sticker", card_id="sv1-2",
                                     sticker_price=Decimal("20.00")))

        resp = client.get("/admin/inventory/search?missing_sticker=true",
                          headers=_auth_header(admin_token))
        assert resp.status_code == 200
        assert [i["item_id"] for i in resp.json()["items"]] == ["no-sticker"]

        # Default (absent) does not filter.
        resp = client.get("/admin/inventory/search",
                          headers=_auth_header(admin_token))
        assert resp.json()["total"] == 2

    def test_search_needs_review_filter(self, admin_client):
        client, repo, admin_token, _ = admin_client
        repo.put_inventory_item(_raw(item_id="reviewed-1", needs_review=False))
        repo.put_inventory_item(_raw(item_id="flagged-1", card_id="sv1-2", needs_review=True))

        resp = client.get(
            "/admin/inventory/search",
            params={"needs_review": "true"},
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        ids = {i["item_id"] for i in resp.json()["items"]}
        assert ids == {"flagged-1"}

    def test_price_range_uses_market_value(self, admin_client):
        """The price bound compares against current_market_value when present,
        falling back to cost_basis only when it is null."""
        client, repo, admin_token, _ = admin_client
        # Cheap to buy, expensive now — must be INCLUDED by min_price=100.
        repo.put_inventory_item(_raw(item_id="risen", cost_basis="5.00",
                                     current_market_value="250.00"))
        # Expensive to buy, cheap now — must be EXCLUDED by min_price=100.
        repo.put_inventory_item(_raw(item_id="fallen", card_id="sv1-2",
                                     cost_basis="400.00",
                                     current_market_value="20.00"))
        # No market value at all — falls back to cost_basis (150 >= 100).
        repo.put_inventory_item(_raw(item_id="unpriced", card_id="sv1-3",
                                     cost_basis="150.00",
                                     current_market_value=None))

        resp = client.get("/admin/inventory/search?min_price=100",
                          headers=_auth_header(admin_token))
        assert resp.status_code == 200
        assert {i["item_id"] for i in resp.json()["items"]} == {"risen", "unpriced"}

        resp = client.get("/admin/inventory/search?max_price=100",
                          headers=_auth_header(admin_token))
        assert resp.status_code == 200
        assert {i["item_id"] for i in resp.json()["items"]} == {"fallen"}


class TestAdminWriteCombinedCondition:
    """POST/PUT accept the display condition string (``LP-``) and split it."""

    def test_put_accepts_combined_condition(self, admin_client):
        client, repo, admin_token, _ = admin_client
        repo.put_inventory_item(_raw(item_id="item-1", condition=Condition.NM))

        resp = client.put(
            "/admin/inventory/item-1",
            json={"condition": "LP-"},
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        assert resp.json()["condition"] == "LP"
        assert resp.json()["condition_modifier"] == "-"
        stored = repo.get_inventory_item("item-1")
        assert stored.condition is Condition.LP
        assert stored.condition_modifier is ConditionModifier.MINUS

    def test_post_accepts_combined_condition(self, admin_client):
        client, repo, admin_token, _ = admin_client
        resp = client.post(
            "/admin/inventory",
            json={
                "kind": "raw", "card_id": "sv1-1", "finish": "holofoil",
                "condition": "LP+", "cost_basis": "25.00",
                "acquired_at": "2025-01-15", "location": "glass",
            },
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 201
        stored = repo.get_inventory_item(resp.json()["item_id"])
        assert stored.condition is Condition.LP
        assert stored.condition_modifier is ConditionModifier.PLUS

    def test_put_rejects_unknown_location(self, admin_client):
        client, repo, admin_token, _ = admin_client
        repo.put_inventory_item(_raw(item_id="item-1", location="glass"))

        resp = client.put(
            "/admin/inventory/item-1",
            json={"location": "under_the_sofa"},
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 422
        assert repo.get_inventory_item("item-1").location == "glass"

    def test_post_rejects_unknown_location(self, admin_client):
        client, _, admin_token, _ = admin_client
        resp = client.post(
            "/admin/inventory",
            json={
                "kind": "raw", "card_id": "sv1-1", "finish": "holofoil",
                "condition": "NM", "cost_basis": "25.00",
                "acquired_at": "2025-01-15", "location": "under_the_sofa",
            },
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 422


class TestAdminLocationRequired:
    def test_create_rejects_missing_location(self, admin_client):
        client, repo, admin_token, _ = admin_client
        resp = client.post(
            "/admin/inventory",
            json={
                "kind": "raw", "card_id": "sv1-1", "finish": "holofoil",
                "condition": "NM", "cost_basis": "10.00", "acquired_at": "2025-01-01",
            },
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 422

    def test_update_rejects_blanking_location(self, admin_client):
        client, repo, admin_token, _ = admin_client
        repo.put_inventory_item(_raw(item_id="item-1", location="glass"))
        resp = client.put(
            "/admin/inventory/item-1",
            json={"location": None},
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 422
        # Original location must be untouched.
        assert repo.get_inventory_item("item-1").location == "glass"


class TestAdminLineageProfit:
    """GET /admin/inventory/{item_id}/lineage — per-step and cumulative profit."""

    def test_lineage_reports_step_and_cumulative_profit(self, admin_client):
        client, repo, admin_token, _ = admin_client
        # Node A: bought for 10, traded out at 40.
        repo.put_inventory_item(_raw(
            item_id="chain-a", cost_basis="10.00", status=ItemStatus.SOLD,
            lineage_id="chain-a", display_name="Node A",
        ))
        # Node B: acquired via that trade at cost 30, later sold for 75 cash.
        repo.put_inventory_item(_raw(
            item_id="chain-b", card_id="sv1-2", cost_basis="30.00",
            status=ItemStatus.SOLD, lineage_id="chain-a",
            predecessor_item_id="chain-a", display_name="Node B",
        ))
        repo.put_timeline_event("chain-a", {
            "item_id": "chain-a", "txn_id": "t-1", "type": "trade_out",
            "date": "2025-03-01", "amount": "40.00", "payment_method": "trade",
            "trade_id": "tr-1", "counterpart_item_id": "chain-b",
        })
        repo.put_timeline_event("chain-b", {
            "item_id": "chain-b", "txn_id": "t-2", "type": "sale",
            "date": "2025-05-01", "amount": "75.00", "payment_method": "cash",
        })

        resp = client.get("/admin/inventory/chain-b/lineage",
                          headers=_auth_header(admin_token))
        assert resp.status_code == 200
        data = resp.json()
        chain = data["chain"]
        assert [n["item_id"] for n in chain] == ["chain-a", "chain-b"]

        assert chain[0]["disposed_via"] == "trade_out"
        assert chain[0]["disposed_value"] == "40.00"
        assert chain[0]["step_profit"] == "30.00"
        assert chain[0]["cumulative_profit"] == "30.00"

        assert chain[1]["disposed_via"] == "sale"
        assert chain[1]["disposed_value"] == "75.00"
        assert chain[1]["step_profit"] == "45.00"
        assert chain[1]["cumulative_profit"] == "75.00"

        assert data["chain_complete"] is True

    def test_lineage_incomplete_when_last_node_still_held(self, admin_client):
        client, repo, admin_token, _ = admin_client
        repo.put_inventory_item(_raw(
            item_id="open-a", cost_basis="10.00", status=ItemStatus.SOLD,
            lineage_id="open-a",
        ))
        repo.put_inventory_item(_raw(
            item_id="open-b", card_id="sv1-2", cost_basis="30.00",
            lineage_id="open-a", predecessor_item_id="open-a",
        ))
        repo.put_timeline_event("open-a", {
            "item_id": "open-a", "txn_id": "t-1", "type": "trade_out",
            "date": "2025-03-01", "amount": "40.00", "payment_method": "trade",
        })

        resp = client.get("/admin/inventory/open-b/lineage",
                          headers=_auth_header(admin_token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["chain_complete"] is False
        last = data["chain"][-1]
        assert last["disposed_via"] is None
        assert last["disposed_value"] is None
        assert last["step_profit"] is None
        # Cumulative carries the previous node's realized profit forward.
        assert last["cumulative_profit"] == "30.00"

    def test_lineage_trade_settled_sale_does_not_complete_chain(self, admin_client):
        """A ``sale`` event paid in trade is a swap, not an exit."""
        client, repo, admin_token, _ = admin_client
        repo.put_inventory_item(_raw(item_id="solo-1", cost_basis="10.00",
                                     status=ItemStatus.SOLD, lineage_id="solo-1"))
        repo.put_timeline_event("solo-1", {
            "item_id": "solo-1", "txn_id": "t-1", "type": "sale",
            "date": "2025-03-01", "amount": "40.00", "payment_method": "trade",
        })

        resp = client.get("/admin/inventory/solo-1/lineage",
                          headers=_auth_header(admin_token))
        assert resp.status_code == 200
        assert resp.json()["chain_complete"] is False


class TestAdminSearchByLifetimeProfit:
    """GET /admin/inventory/search — filtering by cumulative lifetime profit."""

    def test_filters_by_min_profit(self, admin_client):
        client, repo, admin_token, _ = admin_client
        # chain-a: bought 10, traded out at 40 -> step profit 30 (still available/current node not evaluated here)
        repo.put_inventory_item(_raw(
            item_id="chain-a", cost_basis="10.00", status=ItemStatus.SOLD, lineage_id="chain-a",
        ))
        repo.put_inventory_item(_raw(
            item_id="chain-b", card_id="sv1-2", cost_basis="30.00", status=ItemStatus.SOLD,
            lineage_id="chain-a", predecessor_item_id="chain-a",
        ))
        repo.put_timeline_event("chain-a", {
            "item_id": "chain-a", "txn_id": "t-1", "type": "trade_out",
            "date": "2025-03-01", "amount": "40.00", "payment_method": "trade",
        })
        repo.put_timeline_event("chain-b", {
            "item_id": "chain-b", "txn_id": "t-2", "type": "sale",
            "date": "2025-05-01", "amount": "75.00", "payment_method": "cash",
        })
        # low-profit-1: bought 10, sold for 12 -> cumulative 2.00
        repo.put_inventory_item(_raw(item_id="low-1", card_id="sv1-3", cost_basis="10.00",
                                      status=ItemStatus.SOLD, lineage_id="low-1"))
        repo.put_timeline_event("low-1", {
            "item_id": "low-1", "txn_id": "t-3", "type": "sale",
            "date": "2025-04-01", "amount": "12.00", "payment_method": "cash",
        })

        resp = client.get(
            "/admin/inventory/search",
            params={"min_profit": "10"},
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        ids = {i["item_id"] for i in resp.json()["items"]}
        assert "chain-a" in ids  # cumulative through chain-a is 30.00
        assert "chain-b" in ids  # cumulative through chain-b is 75.00
        assert "low-1" not in ids  # cumulative is only 2.00

    def test_filters_by_max_profit(self, admin_client):
        client, repo, admin_token, _ = admin_client
        repo.put_inventory_item(_raw(item_id="low-1", cost_basis="10.00",
                                      status=ItemStatus.SOLD, lineage_id="low-1"))
        repo.put_timeline_event("low-1", {
            "item_id": "low-1", "txn_id": "t-1", "type": "sale",
            "date": "2025-04-01", "amount": "12.00", "payment_method": "cash",
        })
        repo.put_inventory_item(_raw(item_id="high-1", card_id="sv1-2", cost_basis="10.00",
                                      status=ItemStatus.SOLD, lineage_id="high-1"))
        repo.put_timeline_event("high-1", {
            "item_id": "high-1", "txn_id": "t-2", "type": "sale",
            "date": "2025-04-01", "amount": "500.00", "payment_method": "cash",
        })

        resp = client.get(
            "/admin/inventory/search",
            params={"max_profit": "10"},
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        ids = {i["item_id"] for i in resp.json()["items"]}
        assert "low-1" in ids
        assert "high-1" not in ids

    def test_never_disposed_item_has_zero_lifetime_profit(self, admin_client):
        client, repo, admin_token, _ = admin_client
        repo.put_inventory_item(_raw(item_id="held-1", cost_basis="10.00"))

        resp = client.get(
            "/admin/inventory/search",
            params={"min_profit": "0", "max_profit": "0"},
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        ids = {i["item_id"] for i in resp.json()["items"]}
        assert "held-1" in ids

    def test_min_profit_scoped_to_name_filter_does_not_walk_unrelated_lineages(
        self, admin_client, monkeypatch,
    ):
        """A name-scoped profit search must only fetch timeline events for
        lineages actually present in the name-filtered candidate set — not
        re-walk every chain in the whole table (finding 3)."""
        client, repo, admin_token, _ = admin_client
        repo.put_inventory_item(_raw(
            item_id="target-1", display_name="Pikachu",
            cost_basis="10.00", status=ItemStatus.SOLD, lineage_id="target-1",
        ))
        repo.put_timeline_event("target-1", {
            "item_id": "target-1", "txn_id": "t-1", "type": "sale",
            "date": "2025-04-01", "amount": "50.00", "payment_method": "cash",
        })
        # An unrelated item/chain that does NOT match the name filter — its
        # timeline must never be fetched by a name-scoped profit search.
        repo.put_inventory_item(_raw(
            item_id="other-1", display_name="Charizard", card_id="sv1-2",
            cost_basis="10.00", status=ItemStatus.SOLD, lineage_id="other-1",
        ))
        repo.put_timeline_event("other-1", {
            "item_id": "other-1", "txn_id": "t-2", "type": "sale",
            "date": "2025-04-01", "amount": "999.00", "payment_method": "cash",
        })

        calls: list[str] = []
        original = repo.get_timeline_events

        def _tracking(item_id):
            calls.append(item_id)
            return original(item_id)

        monkeypatch.setattr(repo, "get_timeline_events", _tracking)

        resp = client.get(
            "/admin/inventory/search",
            params={"name": "Pikachu", "min_profit": "0"},
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        ids = {i["item_id"] for i in resp.json()["items"]}
        assert ids == {"target-1"}
        assert "target-1" in calls
        assert "other-1" not in calls


class TestAdminRefreshPrices:
    """POST /admin/inventory/refresh-prices agrees with catalog_sync."""

    def test_refresh_prices_applies_condition_adjustment(self, admin_client):
        from merlins_collection.services.condition_pricing import (
            apply_condition_adjustment,
        )

        client, repo, admin_token, _ = admin_client
        repo.batch_upsert_catalog_cards([
            _catalog(card_id="sv1-1", name="Pikachu",
                     prices={"holofoil": FinishPrice(market=Decimal("100.00"))}),
        ])
        repo.put_inventory_item(_raw(
            item_id="lp-1", card_id="sv1-1", finish="holofoil",
            condition=Condition.LP, current_market_value=None,
        ))

        resp = client.post("/admin/inventory/refresh-prices",
                           headers=_auth_header(admin_token))
        assert resp.status_code == 200
        assert resp.json()["updated"] == 1

        expected, expected_note = apply_condition_adjustment(
            Decimal("100.00"), Condition.LP, None,
        )
        stored = repo.get_inventory_item("lp-1")
        assert stored.current_market_value == expected
        assert stored.current_market_value != Decimal("100.00")
        assert stored.value_note == expected_note

    def test_refresh_prices_uses_finish_fallback(self, admin_client):
        """A ``normal``-finish item against a holo-only card still gets priced
        (the bug the shared ``_market_price`` walk exists to prevent)."""
        client, repo, admin_token, _ = admin_client
        repo.batch_upsert_catalog_cards([
            _catalog(card_id="sv1-1", name="Pikachu",
                     prices={"holofoil": FinishPrice(market=Decimal("100.00"))}),
        ])
        repo.put_inventory_item(_raw(
            item_id="nm-1", card_id="sv1-1", finish="normal",
            condition=Condition.NM, current_market_value=None,
        ))

        resp = client.post("/admin/inventory/refresh-prices",
                           headers=_auth_header(admin_token))
        assert resp.status_code == 200
        stored = repo.get_inventory_item("nm-1")
        assert stored.current_market_value == Decimal("100.00")
        assert stored.value_note is None

    def test_refresh_prices_skips_graded_without_manual_value(self, admin_client):
        """Catalog figures are UNGRADED, so a slab never takes one."""
        client, repo, admin_token, _ = admin_client
        repo.batch_upsert_catalog_cards([
            _catalog(card_id="sv1-2", name="Charizard",
                     prices={"holofoil": FinishPrice(market=Decimal("100.00"))}),
        ])
        repo.put_inventory_item(_graded(item_id="slab-1", card_id="sv1-2",
                                        current_market_value="500.00"))

        resp = client.post("/admin/inventory/refresh-prices",
                           headers=_auth_header(admin_token))
        assert resp.status_code == 200
        assert resp.json()["updated"] == 0
        assert repo.get_inventory_item("slab-1").current_market_value == Decimal("500.00")


# ===========================================================================
# RFC 0010 T16 — valuing a card the catalog does not carry
# ===========================================================================

class TestAdminHandValuation:
    """A card with no catalog match still needs a price, and a way to type it.

    The nightly denormalizer skips an unlinked item (see
    ``tests/services/test_catalog_sync.py``), so the ordinary partial update IS
    the hand-valuation write path — there is no second endpoint and there must
    not be one.
    """

    def test_put_accepts_a_hand_set_value_and_note_on_an_unlinked_item(
        self, admin_client
    ):
        client, repo, admin_token, _ = admin_client
        repo.put_inventory_item(_raw(
            item_id="unlinked-1", card_id=None, condition=Condition.MP,
            current_market_value=None,
        ))

        resp = client.put(
            "/admin/inventory/unlinked-1",
            json={
                "current_market_value": "23.20",
                "value_note": "Hand-valued 2026-08-11 - NM comp $40.00 x MP (0.58)",
            },
            headers=_auth_header(admin_token),
        )

        assert resp.status_code == 200
        stored = repo.get_inventory_item("unlinked-1")
        assert stored.current_market_value == Decimal("23.20")
        assert "Hand-valued" in stored.value_note
        # The one rule that must not be broken: valuing never links the card.
        assert stored.card_id is None

    def test_a_raw_row_carries_the_condition_multiplier_the_server_computed(
        self, admin_client
    ):
        """The hand-valuation helper needs the multiplier, not a copy of the table.

        ``services/condition_pricing.py`` is the authority and it already has one
        duplicate (``mcp-server/src/condition-pricing.ts``). A third copy in
        ``frontend/lib`` is what the task doc's "do not hardcode a second copy of
        the condition multiplier table" rules out, so the number rides on the row.
        """
        client, repo, admin_token, _ = admin_client
        repo.put_inventory_item(_raw(
            item_id="mp-1", card_id=None, condition=Condition.MP,
        ))
        repo.put_inventory_item(_raw(
            item_id="lp-plus-1", card_id=None, condition=Condition.LP,
            condition_modifier=ConditionModifier.PLUS,
        ))
        # A kind with no condition at all must not invent one.
        repo.put_inventory_item(_sealed(item_id="sealed-1"))

        rows = client.get(
            "/admin/inventory/search", headers=_auth_header(admin_token)
        ).json()["items"]
        by_id = {r["item_id"]: r for r in rows}

        assert Decimal(by_id["mp-1"]["condition_multiplier"]) == Decimal("0.58")
        # LP+ is the midpoint of LP (0.82) and NM (1.00).
        assert Decimal(by_id["lp-plus-1"]["condition_multiplier"]) == Decimal("0.91")
        assert by_id["sealed-1"]["condition_multiplier"] is None


# ===========================================================================
# RFC 0011 T5 — the unmatched queue's model + endpoint behaviour
# ===========================================================================
#
# The queue is `GET /admin/inventory/search?no_catalog_match=true` — NOT a new
# list endpoint, on the same "reuse before adding" rule that keeps Triage on the
# shared search.

class TestNoCatalogMatchQueue:

    def test_the_unmatched_queue_ships_empty(self, admin_client):
        """Owner requirement, 2026-08-13, verbatim: "make sure that the new tab
        is empty right now, all cards that go there should only be moved under
        admin supervision."

        Nothing is backfilled and nothing auto-migrates. Unlinked inventory that
        no admin has touched must NOT appear here.
        """
        client, repo, admin, _ = admin_client
        repo.put_inventory_item(_raw(card_id=None, item_id="unlinked"))
        repo.put_inventory_item(_sealed(item_id="box"))

        resp = client.get(
            "/admin/inventory/search",
            params={"no_catalog_match": "true"},
            headers=_auth_header(admin),
        )

        assert resp.status_code == 200
        assert resp.json()["items"] == []

    def test_the_queue_lists_exactly_what_an_admin_parked(self, admin_client):
        client, repo, admin, _ = admin_client
        repo.put_inventory_item(
            _raw(card_id=None, item_id="parked", no_catalog_match=True),
        )
        repo.put_inventory_item(_raw(card_id=None, item_id="unlinked"))
        repo.put_inventory_item(_raw(item_id="linked"))

        resp = client.get(
            "/admin/inventory/search",
            params={"no_catalog_match": "true"},
            headers=_auth_header(admin),
        )

        assert [i["item_id"] for i in resp.json()["items"]] == ["parked"]

    def test_the_parameter_also_excludes(self, admin_client):
        """`false` is a real query, not a synonym for "unset" — it is how the
        ordinary inventory list hides the parked cohort."""
        client, repo, admin, _ = admin_client
        repo.put_inventory_item(
            _raw(card_id=None, item_id="parked", no_catalog_match=True),
        )
        repo.put_inventory_item(_raw(item_id="linked"))

        resp = client.get(
            "/admin/inventory/search",
            params={"no_catalog_match": "false"},
            headers=_auth_header(admin),
        )

        assert [i["item_id"] for i in resp.json()["items"]] == ["linked"]

    def test_parking_stamps_the_server_side_timestamp(self, admin_client):
        """Server-stamped, never client-supplied — the rule ``reviewed_at``
        already follows. Drives "parked 3 weeks ago" on the queue."""
        client, repo, admin, _ = admin_client
        repo.put_inventory_item(_raw(card_id=None, item_id="x"))

        resp = client.put(
            "/admin/inventory/x",
            json={"no_catalog_match": True},
            headers=_auth_header(admin),
        )

        assert resp.status_code == 200
        assert repo.get_inventory_item("x").no_catalog_match_at is not None

    def test_a_client_supplied_timestamp_is_ignored(self, admin_client):
        client, repo, admin, _ = admin_client
        repo.put_inventory_item(_raw(card_id=None, item_id="x"))

        client.put(
            "/admin/inventory/x",
            json={
                "no_catalog_match": True,
                "no_catalog_match_at": "2020-01-01T00:00:00Z",
            },
            headers=_auth_header(admin),
        )

        stamped = repo.get_inventory_item("x").no_catalog_match_at
        assert stamped.year > 2020

    def test_assigning_a_card_id_unparks_automatically(self, admin_client):
        """Pairing is the exit condition. Requiring a SECOND write to leave the
        queue is how rows get stranded in it."""
        client, repo, admin, _ = admin_client
        repo.batch_upsert_catalog_cards([_catalog(card_id="sv1-9")])
        repo.put_inventory_item(
            _raw(card_id=None, item_id="x", no_catalog_match=True),
        )

        resp = client.put(
            "/admin/inventory/x",
            json={"card_id": "sv1-9"},
            headers=_auth_header(admin),
        )

        assert resp.status_code == 200
        item = repo.get_inventory_item("x")
        assert item.no_catalog_match is False
        assert item.no_catalog_match_at is None

    def test_unparking_clears_the_timestamp(self, admin_client):
        """Parking that cannot be undone is just a slower delete."""
        client, repo, admin, _ = admin_client
        repo.put_inventory_item(_raw(
            card_id=None, item_id="x", no_catalog_match=True,
            no_catalog_match_at=datetime.now(tz=timezone.utc),
        ))

        resp = client.put(
            "/admin/inventory/x",
            json={"no_catalog_match": False},
            headers=_auth_header(admin),
        )

        assert resp.status_code == 200
        assert repo.get_inventory_item("x").no_catalog_match_at is None

    def test_parking_a_still_linked_item_is_a_422(self, admin_client):
        """The model invariant, surfaced at the endpoint an admin actually hits.
        T6 unlinks and parks in one click; doing only half of it must not pass.
        """
        client, repo, admin, _ = admin_client
        repo.put_inventory_item(_raw(item_id="x"))

        resp = client.put(
            "/admin/inventory/x",
            json={"no_catalog_match": True},
            headers=_auth_header(admin),
        )

        assert resp.status_code == 422
        assert "unlink" in resp.json()["detail"].lower()

    def test_unlinking_and_parking_in_one_body_succeeds(self, admin_client):
        """The T6 gesture. Order inside the handler has to resolve this, not
        reject it."""
        client, repo, admin, _ = admin_client
        repo.put_inventory_item(_raw(item_id="x"))

        resp = client.put(
            "/admin/inventory/x",
            json={"card_id": None, "no_catalog_match": True},
            headers=_auth_header(admin),
        )

        assert resp.status_code == 200
        item = repo.get_inventory_item("x")
        assert item.card_id is None
        assert item.no_catalog_match is True
        assert item.no_catalog_match_at is not None

    def test_a_sealed_item_cannot_be_parked(self, admin_client):
        """Sealed product has no catalog link BY DESIGN — there is nothing
        missing, so there is nothing to park."""
        client, repo, admin, _ = admin_client
        repo.put_inventory_item(_sealed(item_id="box"))

        resp = client.put(
            "/admin/inventory/box",
            json={"no_catalog_match": True},
            headers=_auth_header(admin),
        )

        assert resp.status_code == 422
