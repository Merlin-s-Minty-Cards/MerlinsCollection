"""Tests for the admin locations endpoint (``/admin/locations``).

Verifies the canonical location list is served for dropdown population, and
that it is admin-managed (DB-backed, validated) rather than a hardcoded enum.
"""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from merlins_collection.models.inventory import Condition, ItemStatus, RawInventoryItem


def _raw(item_id="item-1", *, card_id="sv1-1", location="glass",
         status=ItemStatus.AVAILABLE):
    return RawInventoryItem(
        item_id=item_id, card_id=card_id, finish="holofoil",
        condition=Condition.NM, location=location, status=status,
        cost_basis=Decimal("20.00"),
        current_market_value=Decimal("50.00"),
        acquired_at=date(2025, 1, 1),
    )


@pytest.fixture
def admin_client(cognito_config, jwks, dynamo_repo, mint_token):
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

    admin_token = mint_token(claims={"cognito:groups": ["admin"]})
    client = TestClient(app)
    yield client, admin_token
    app.dependency_overrides.clear()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class TestListLocations:
    def test_returns_location_list(self, admin_client):
        """GET /admin/locations returns the full location choice list."""
        client, token = admin_client
        resp = client.get("/admin/locations", headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 4  # at minimum glass, toploader, binder, storage

        # Each entry has value and label
        for entry in data:
            assert "value" in entry
            assert "label" in entry

        # Known values present
        values = [e["value"] for e in data]
        assert "glass" in values
        assert "toploader" in values
        assert "binder" in values
        assert "storage" in values
        assert "show_box_a" in values
        assert "show_box_b" in values

    def test_requires_admin_auth(self, admin_client):
        """Endpoint is admin-only."""
        client, _ = admin_client
        resp = client.get("/admin/locations")
        assert resp.status_code in (401, 403)


class TestLocationsAdminManaged:
    """DB-backed, admin-managed locations: seeding, add, delete, validation."""

    def test_get_seeds_from_enum_and_inventory(self, admin_client, dynamo_repo):
        client, token = admin_client
        dynamo_repo.put_inventory_item(_raw(item_id="seed-1", location="card_show_bin"))

        resp = client.get("/admin/locations", headers=_auth(token))
        assert resp.status_code == 200
        values = [o["value"] for o in resp.json()]
        assert "toploader" in values            # from enum
        assert "card_show_bin" in values        # discovered from DB

        # second GET returns the persisted config (no re-scan needed): same list
        second = client.get("/admin/locations", headers=_auth(token))
        assert second.json() == resp.json()

    def test_post_adds_location(self, admin_client):
        client, token = admin_client
        r = client.post(
            "/admin/locations",
            json={"value": "show_box_c", "label": "Show Box C"},
            headers=_auth(token),
        )
        assert r.status_code == 201
        listing = client.get("/admin/locations", headers=_auth(token)).json()
        assert {"value": "show_box_c", "label": "Show Box C"} in listing

    def test_post_duplicate_409(self, admin_client):
        client, token = admin_client
        client.post(
            "/admin/locations",
            json={"value": "show_box_d", "label": "Show Box D"},
            headers=_auth(token),
        )
        r = client.post(
            "/admin/locations",
            json={"value": "show_box_d", "label": "Show Box D"},
            headers=_auth(token),
        )
        assert r.status_code == 409

    def test_post_bad_slug_422(self, admin_client):
        client, token = admin_client
        r = client.post(
            "/admin/locations",
            json={"value": "Show Box!", "label": "Bad"},
            headers=_auth(token),
        )
        assert r.status_code == 422

    def test_delete_in_use_409(self, admin_client, dynamo_repo):
        client, token = admin_client
        dynamo_repo.put_inventory_item(_raw(item_id="in-use", location="glass"))
        r = client.delete("/admin/locations/glass", headers=_auth(token))
        assert r.status_code == 409

    def test_delete_unused_204(self, admin_client):
        client, token = admin_client
        client.post(
            "/admin/locations",
            json={"value": "temp_box", "label": "Temp Box"},
            headers=_auth(token),
        )
        r = client.delete("/admin/locations/temp_box", headers=_auth(token))
        assert r.status_code == 204
        listing = client.get("/admin/locations", headers=_auth(token)).json()
        assert "temp_box" not in [o["value"] for o in listing]

    def test_delete_unknown_404(self, admin_client):
        client, token = admin_client
        r = client.delete("/admin/locations/nonexistent_value", headers=_auth(token))
        assert r.status_code == 404

    def test_bulk_move_unknown_location_422(self, admin_client, dynamo_repo):
        client, token = admin_client
        dynamo_repo.put_inventory_item(_raw(item_id="mv-1", location="glass"))
        r = client.post(
            "/admin/show-prep/bulk-move",
            json={"item_ids": ["mv-1"], "new_location": "narnia"},
            headers=_auth(token),
        )
        assert r.status_code == 422


class TestInventoryLocationEnum:
    def test_enum_values_match_choices(self):
        """The InventoryLocation enum and INVENTORY_LOCATION_CHOICES stay in sync."""
        from merlins_collection.models.inventory import (
            INVENTORY_LOCATION_CHOICES,
            InventoryLocation,
        )
        enum_values = {loc.value for loc in InventoryLocation}
        choice_values = {c["value"] for c in INVENTORY_LOCATION_CHOICES}
        assert enum_values == choice_values

    def test_location_field_accepts_enum_values(self):
        """Inventory items accept InventoryLocation values for location field."""
        from datetime import date
        from decimal import Decimal

        from merlins_collection.models.inventory import (
            Condition,
            InventoryLocation,
            RawInventoryItem,
        )

        item = RawInventoryItem(
            finish="normal",
            condition=Condition.NM,
            cost_basis=Decimal("10"),
            acquired_at=date(2025, 1, 1),
            location=InventoryLocation.SHOW_BOX_A.value,
        )
        assert item.location == "show_box_a"

    def test_location_field_accepts_legacy_strings(self):
        """Backward compat: items with any string in location still validate."""
        from datetime import date
        from decimal import Decimal

        from merlins_collection.models.inventory import Condition, RawInventoryItem

        # Legacy free-text value — should still work
        item = RawInventoryItem(
            finish="normal",
            condition=Condition.NM,
            cost_basis=Decimal("10"),
            acquired_at=date(2025, 1, 1),
            location="old_custom_value",
        )
        assert item.location == "old_custom_value"
