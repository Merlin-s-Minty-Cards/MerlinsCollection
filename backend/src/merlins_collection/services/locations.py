"""Admin-managed inventory locations (owner decision 2026-08-03)."""
import re

from botocore.exceptions import ClientError
from fastapi import HTTPException

from ..models.inventory import INVENTORY_LOCATION_CHOICES

_SLUG_RE = re.compile(r"^[a-z0-9_]{2,40}$")


def label(value: str) -> str:
    return value.replace("_", " ").title()


def _is_conflict(exc: ClientError) -> bool:
    return exc.response["Error"]["Code"] == "ConditionalCheckFailedException"


def _seed(repo) -> tuple[list[dict[str, str]], int]:
    """Build the initial location list from the enum plus any distinct
    in-use values, and persist it as the first row (gen 1)."""
    seen = {c["value"] for c in INVENTORY_LOCATION_CHOICES}
    locations = list(INVENTORY_LOCATION_CHOICES)
    for item in repo.list_inventory():
        loc = getattr(item, "location", None)
        if loc and loc not in seen:
            seen.add(loc)
            locations.append({"value": loc, "label": label(loc)})
    try:
        gen = repo.put_location_config(locations)
    except ClientError as exc:
        if not _is_conflict(exc):
            raise
        # Another request seeded the row first — use its version rather
        # than clobbering it.
        result = repo.get_location_config_with_generation()
        if result is None:
            raise
        return result
    return locations, gen


def get_locations_with_generation(repo) -> tuple[list[dict[str, str]], int]:
    """Current location list plus its generation, seeding if never stored.

    Callers that mutate the list (add/remove) need the generation to pass
    back into ``repo.put_location_config(..., expected_generation=...)`` so a
    concurrent writer's change can't be silently lost.
    """
    result = repo.get_location_config_with_generation()
    if result is not None:
        return result
    return _seed(repo)


def get_locations(repo) -> list[dict[str, str]]:
    locations, _gen = get_locations_with_generation(repo)
    return locations


def validate_location(repo, value, *, required: bool = False) -> None:
    if value is None or value == "":
        if required:
            raise HTTPException(status_code=422, detail="location is required")
        return
    if value not in {o["value"] for o in get_locations(repo)}:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown location '{value}'. Add it via POST /admin/locations first.",
        )


def validate_new_slug(value: str) -> None:
    if not _SLUG_RE.match(value or ""):
        raise HTTPException(status_code=422, detail="value must match ^[a-z0-9_]{2,40}$")
