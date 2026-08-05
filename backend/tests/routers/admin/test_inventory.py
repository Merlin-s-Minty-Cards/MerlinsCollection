"""Tests for the admin inventory CRUD router (``/admin/inventory/...``).

TDD RED: covers auth gate (403 for non-admin), full CRUD lifecycle, search
across all statuses, partial updates, soft/hard deletes, and item history.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from merlins_collection.models.business import Transaction, TransactionType, ItemCategory
from merlins_collection.models.catalog import CardImages, CatalogCard, FinishPrice
from merlins_collection.models.inventory import (
    Condition,
    ConditionModifier,
    GradedInventoryItem,
    GradingCompany,
    ItemStatus,
    Language,
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
    """TestClient + repo + admin token factory for admin endpoint tests."""
    from merlins_collection.dependencies import get_repo, get_verifier
    from merlins_collection.main import app
    from merlins_collection.services.cognito import CognitoJwtVerifier

    verifier = CognitoJwtVerifier(
        region=cognito_config["region"],
        user_pool_id=cognito_config["user_pool_id"],
        client_id=cognito_config["client_id"],
        jwks=jwks,
    )
    app.dependency_overrides[get_verifier] = lambda: verifier
    app.dependency_overrides[get_repo] = lambda: dynamo_repo

    # Admin token: include cognito:groups with admin group
    admin_token = mint_token(claims={"cognito:groups": ["admin"]})
    # Non-admin token: no admin group
    user_token = mint_token(claims={"cognito:groups": []})

    client = TestClient(app)
    yield client, dynamo_repo, admin_token, user_token
    app.dependency_overrides.clear()


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
