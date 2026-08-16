"""``/admin/locations`` — admin-managed, DB-backed inventory location list.

Replaces the hardcoded ``InventoryLocation`` enum as the source of truth for
which locations are valid. Seeded from the enum plus any distinct values
already present in inventory (see ``services.locations.get_locations``), then
stored as a single config row that admins can add to and prune.

Add/remove are guarded by optimistic concurrency (see
``services.locations.get_locations_with_generation`` and
``InventoryRepository.put_location_config``): a lost race against a
concurrent admin surfaces as a 409 to retry, never a silently dropped write.
"""

from __future__ import annotations

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel

from merlins_collection.dependencies import get_repo
from merlins_collection.services import locations as locations_service
from merlins_collection.services.dynamodb import InventoryRepository
from merlins_collection.services.locations_sort import (
    SORT_FIELDS,
    parse_sort,
    sort_locations,
)

router = APIRouter(prefix="/locations", tags=["admin-locations"])

_MAX_LABEL_LENGTH = 60
_CONFLICT_DETAIL = "Location list was modified concurrently; retry"


class LocationCreate(BaseModel):
    value: str
    label: str | None = None


@router.get("")
def list_locations(
    sort: str | None = Query(None),
    repo: InventoryRepository = Depends(get_repo),
) -> list[dict[str, str]]:
    """Return the canonical list of inventory location choices for dropdowns.

    ``sort`` (RFC 0013 T4e) orders the result via ``services.locations_sort`` —
    same ``{field}_{direction}`` convention and 422-on-unknown rule as every
    other admin list endpoint. No order was ever guaranteed here before, so
    omitting it keeps today's storage order.
    """
    if sort is not None and parse_sort(sort) is None:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unknown sort {sort!r}. Expected {{field}}_asc or {{field}}_desc, "
                f"where field is one of: {', '.join(sorted(SORT_FIELDS))}."
            ),
        )

    rows = locations_service.get_locations(repo)
    if sort is not None:
        rows = sort_locations(rows, sort)
    return rows


@router.post("", status_code=201)
def create_location(
    body: LocationCreate,
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, str]:
    """Add a new admin-managed location."""
    locations_service.validate_new_slug(body.value)
    if body.label is not None and len(body.label) > _MAX_LABEL_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"label must be at most {_MAX_LABEL_LENGTH} characters",
        )

    current, gen = locations_service.get_locations_with_generation(repo)
    if any(loc["value"] == body.value for loc in current):
        raise HTTPException(status_code=409, detail=f"Location '{body.value}' already exists")

    entry = {"value": body.value, "label": body.label or locations_service.label(body.value)}
    updated = current + [entry]
    try:
        repo.put_location_config(updated, expected_generation=gen)
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        raise HTTPException(status_code=409, detail=_CONFLICT_DETAIL) from exc
    return entry


@router.delete("/{value}", status_code=204)
def delete_location(
    value: str,
    repo: InventoryRepository = Depends(get_repo),
) -> Response:
    """Remove an admin-managed location, if unused by any inventory item."""
    current, gen = locations_service.get_locations_with_generation(repo)
    if not any(loc["value"] == value for loc in current):
        raise HTTPException(status_code=404, detail=f"Unknown location '{value}'")

    if any(getattr(item, "location", None) == value for item in repo.list_inventory()):
        raise HTTPException(status_code=409, detail=f"Location '{value}' is still in use")

    updated = [loc for loc in current if loc["value"] != value]
    try:
        repo.put_location_config(updated, expected_generation=gen)
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        raise HTTPException(status_code=409, detail=_CONFLICT_DETAIL) from exc
    return Response(status_code=204)
