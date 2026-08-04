"""``/admin/locations`` — admin-managed, DB-backed inventory location list.

Replaces the hardcoded ``InventoryLocation`` enum as the source of truth for
which locations are valid. Seeded from the enum plus any distinct values
already present in inventory (see ``services.locations.get_locations``), then
stored as a single config row that admins can add to and prune.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from merlins_collection.dependencies import get_repo
from merlins_collection.services import locations as locations_service
from merlins_collection.services.dynamodb import InventoryRepository

router = APIRouter(prefix="/locations", tags=["admin-locations"])


class LocationCreate(BaseModel):
    value: str
    label: str | None = None


@router.get("")
def list_locations(
    repo: InventoryRepository = Depends(get_repo),
) -> list[dict[str, str]]:
    """Return the canonical list of inventory location choices for dropdowns."""
    return locations_service.get_locations(repo)


@router.post("", status_code=201)
def create_location(
    body: LocationCreate,
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, str]:
    """Add a new admin-managed location."""
    locations_service.validate_new_slug(body.value)
    current = locations_service.get_locations(repo)
    if any(loc["value"] == body.value for loc in current):
        raise HTTPException(status_code=409, detail=f"Location '{body.value}' already exists")

    entry = {"value": body.value, "label": body.label or locations_service._label(body.value)}
    current.append(entry)
    repo.put_location_config(current)
    return entry


@router.delete("/{value}", status_code=204)
def delete_location(
    value: str,
    repo: InventoryRepository = Depends(get_repo),
) -> Response:
    """Remove an admin-managed location, if unused by any inventory item."""
    current = locations_service.get_locations(repo)
    if not any(loc["value"] == value for loc in current):
        raise HTTPException(status_code=404, detail=f"Unknown location '{value}'")

    if any(getattr(item, "location", None) == value for item in repo.list_inventory()):
        raise HTTPException(status_code=409, detail=f"Location '{value}' is still in use")

    updated = [loc for loc in current if loc["value"] != value]
    repo.put_location_config(updated)
    return Response(status_code=204)
