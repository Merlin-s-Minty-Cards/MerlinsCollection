"""Admin-managed inventory locations (owner decision 2026-08-03)."""
import re

from fastapi import HTTPException

from ..models.inventory import INVENTORY_LOCATION_CHOICES

_SLUG_RE = re.compile(r"^[a-z0-9_]{2,40}$")


def _label(value: str) -> str:
    return value.replace("_", " ").title()


def get_locations(repo) -> list[dict[str, str]]:
    stored = repo.get_location_config()
    if stored is not None:
        return stored
    seen = {c["value"] for c in INVENTORY_LOCATION_CHOICES}
    locations = list(INVENTORY_LOCATION_CHOICES)
    for item in repo.list_inventory():
        loc = getattr(item, "location", None)
        if loc and loc not in seen:
            seen.add(loc)
            locations.append({"value": loc, "label": _label(loc)})
    repo.put_location_config(locations)
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
