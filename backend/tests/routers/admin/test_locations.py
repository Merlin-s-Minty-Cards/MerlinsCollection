"""Tests for the admin locations endpoint (``/admin/locations``).

Verifies the canonical location list is served for dropdown population.
"""

import pytest
from fastapi.testclient import TestClient


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
