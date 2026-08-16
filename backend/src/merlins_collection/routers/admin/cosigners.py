"""``/admin/cosigners`` — Cosigner profile management.

A2: Full CRUD for consignor profiles, asset linking, and per-cosigner
analytics (total items, value, items sold).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from merlins_collection.dependencies import get_repo
from merlins_collection.models.business import Consignor
from merlins_collection.models.inventory import (
    ConsignmentTerms,
    InventoryItemAdapter,
)
from merlins_collection.services.consignors_sort import SORT_FIELDS, parse_sort, sort_consignors
from merlins_collection.services.dynamodb import InventoryRepository

router = APIRouter(prefix="/cosigners", tags=["admin-cosigners"])

# Fields a PATCH may move. ``archived`` is deliberately absent: the two archive
# transitions below are its only writers, so there is one path per transition
# rather than two that can disagree. A legacy ``active`` in the body is ignored
# rather than 422'd — see ``Consignor._archived_from_legacy_active``.
_PATCHABLE = ("name", "contact", "email", "phone", "payout_percent", "notes")


# ---------------------------------------------------------------------------
# Duplicate-name guard
# ---------------------------------------------------------------------------

def _normalized(name: str) -> str:
    """Fold a name for comparison: case-insensitive, whitespace-insensitive."""
    return " ".join(name.split()).casefold()


def _reject_duplicate_name(
    repo: InventoryRepository, name: str, *, exclude_id: str | None = None
) -> None:
    """409 if ``name`` collides with ANOTHER consignor's.

    Scoped to another so re-saving Harry as "Harry", or a PATCH that never
    touches the name, is not an error.

    An ARCHIVED consignor still collides. It is hidden, not gone, and letting a
    live duplicate be created beside it means two rows with the same name appear
    the moment it is unarchived — so the detail says the row is archived, or an
    admin gets a 409 pointing at somebody they cannot see.
    """
    target = _normalized(name)
    for other in repo.list_consignors():
        if other.consignor_id == exclude_id or _normalized(other.name) != target:
            continue
        where = " (archived — turn on View archived to see them)" if other.archived else ""
        raise HTTPException(
            status_code=409,
            detail=f'A cosigner named "{other.name}" already exists{where}.',
        )


def _save_cosigner(
    repo: InventoryRepository, existing: Consignor, changes: dict[str, Any]
) -> dict[str, Any]:
    """Merge ``changes`` onto ``existing``, re-validate, store, and serialize.

    Shared by the update and both archive transitions so all three go through
    one validation path and one write.
    """
    merged = existing.model_dump(mode="python")
    merged.update(changes)
    merged["consignor_id"] = existing.consignor_id  # never reassignable
    updated = Consignor.model_validate(merged)
    repo.put_consignor(updated)
    return updated.model_dump(mode="json")


def _require_cosigner(repo: InventoryRepository, consignor_id: str) -> Consignor:
    consignor = repo.get_consignor(consignor_id)
    if consignor is None:
        raise HTTPException(status_code=404, detail="Cosigner not found")
    return consignor


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

@router.post("", status_code=201)
def create_cosigner(
    body: dict[str, Any],
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Create a new cosigner profile."""
    name = str(body["name"]).strip()
    _reject_duplicate_name(repo, name)
    consignor = Consignor(
        name=name,
        contact=body.get("contact"),
        email=body.get("email"),
        phone=body.get("phone"),
        payout_percent=Decimal(str(body.get("payout_percent", "50"))),
        notes=body.get("notes"),
    )
    repo.put_consignor(consignor)
    return consignor.model_dump(mode="json")


@router.get("")
def list_cosigners(
    include_archived: bool = Query(False),
    sort: str | None = Query(None),
    repo: InventoryRepository = Depends(get_repo),
) -> list[dict[str, Any]]:
    """Every cosigner. Archived ones are excluded unless asked for.

    Only THIS listing hides them. ``repo.get_consignor`` stays archive-agnostic
    so assets, analytics and unarchive keep resolving an archived consignor.

    ``sort`` (RFC 0013 T4d) orders the result via ``services.consignors_sort`` —
    same ``{field}_{direction}`` convention and 422-on-unknown rule as every
    other admin list endpoint. No sort was ever guaranteed here before, so
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

    cosigners = repo.list_consignors()
    if not include_archived:
        cosigners = [c for c in cosigners if not c.archived]
    if sort is not None:
        cosigners = sort_consignors(cosigners, sort)
    return [c.model_dump(mode="json") for c in cosigners]


@router.get("/{consignor_id}")
def get_cosigner(
    consignor_id: str,
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Get a single cosigner profile."""
    return _require_cosigner(repo, consignor_id).model_dump(mode="json")


@router.patch("/{consignor_id}")
def update_cosigner(
    consignor_id: str,
    body: dict[str, Any],
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Partial update of a cosigner profile."""
    consignor = _require_cosigner(repo, consignor_id)

    changes: dict[str, Any] = {}
    for key in _PATCHABLE:
        if key not in body:
            continue
        if key == "payout_percent":
            changes[key] = Decimal(str(body[key]))
        elif key == "name":
            changes[key] = str(body[key]).strip()
            _reject_duplicate_name(repo, changes[key], exclude_id=consignor_id)
        else:
            changes[key] = body[key]

    return _save_cosigner(repo, consignor, changes)


@router.delete("/{consignor_id}")
def archive_cosigner(
    consignor_id: str,
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Hide a cosigner from the default listing.

    "Delete" in the admin UI, and an ARCHIVE in fact — the owner's decision, and
    the same contract shows follow. Idempotent and non-destructive: there is
    deliberately no 409 in-use guard, because nothing is destroyed, so a
    consignor with real consignment history archives like any other and their
    linked items keep pointing at a row that still exists.
    """
    return _save_cosigner(repo, _require_cosigner(repo, consignor_id), {"archived": True})


@router.post("/{consignor_id}/unarchive")
def unarchive_cosigner(
    consignor_id: str,
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Restore an archived cosigner. Archiving that cannot be undone is just a
    slower delete, which is the thing this feature exists to avoid."""
    return _save_cosigner(repo, _require_cosigner(repo, consignor_id), {"archived": False})


# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------

@router.get("/{consignor_id}/assets")
def get_cosigner_assets(
    consignor_id: str,
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """List all inventory items linked to this cosigner."""
    consignor = repo.get_consignor(consignor_id)
    if consignor is None:
        raise HTTPException(status_code=404, detail="Cosigner not found")

    all_items = repo.list_inventory()
    linked = [
        i for i in all_items
        if i.consignment is not None and i.consignment.consignor_id == consignor_id
    ]
    serialized = [i.model_dump(mode="json") for i in linked]
    return {"items": serialized, "total": len(serialized)}


@router.post("/{consignor_id}/link")
def link_items_to_cosigner(
    consignor_id: str,
    body: dict[str, Any],
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Batch-link item IDs to a cosigner profile."""
    consignor = repo.get_consignor(consignor_id)
    if consignor is None:
        raise HTTPException(status_code=404, detail="Cosigner not found")

    item_ids = body.get("item_ids", [])
    default_split = (Decimal("100") - consignor.payout_percent) / Decimal("100")
    try:
        split_percent = Decimal(str(body.get("split_percent", str(default_split))))
    except InvalidOperation:
        raise HTTPException(status_code=422, detail="split_percent must be a number")
    if not (Decimal("0") <= split_percent <= Decimal("1")):
        raise HTTPException(
            status_code=422,
            detail="split_percent must be a fraction between 0 and 1 (e.g. 0.2 for a 20% cut)",
        )
    minimum_price = Decimal(str(body["minimum_price"])) if body.get("minimum_price") else None

    linked = 0
    failed_item_ids: list[str] = []
    for item_id in item_ids:
        item = repo.get_inventory_item(item_id)
        if item is None:
            failed_item_ids.append(item_id)
            continue
        # Set consignment terms
        item_data = item.model_dump(mode="python")
        item_data["consignment"] = ConsignmentTerms(
            consignor_id=consignor_id,
            split_percent=split_percent,
            minimum_price=minimum_price,
        ).model_dump(mode="python")
        updated_item = InventoryItemAdapter.validate_python(item_data)
        repo.put_inventory_item(updated_item)
        linked += 1

    return {"linked": linked, "consignor_id": consignor_id, "failed_item_ids": failed_item_ids}


@router.delete("/{consignor_id}/assets/{item_id}")
def unlink_item_from_cosigner(
    consignor_id: str,
    item_id: str,
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Clear an item's consignment terms, returning it to owned stock."""
    item = repo.get_inventory_item(item_id)
    if item is None or item.consignment is None or item.consignment.consignor_id != consignor_id:
        raise HTTPException(status_code=404, detail="Linked item not found for this cosigner")

    item_data = item.model_dump(mode="python")
    item_data["consignment"] = None
    updated_item = InventoryItemAdapter.validate_python(item_data)
    repo.put_inventory_item(updated_item)

    return {"status": "unlinked", "item_id": item_id}


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

@router.get("/{consignor_id}/analytics")
def get_cosigner_analytics(
    consignor_id: str,
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Per-cosigner performance stats."""
    consignor = repo.get_consignor(consignor_id)
    if consignor is None:
        raise HTTPException(status_code=404, detail="Cosigner not found")

    all_items = repo.list_inventory()
    linked = [
        i for i in all_items
        if i.consignment is not None and i.consignment.consignor_id == consignor_id
    ]

    total_items = len(linked)
    items_sold = sum(1 for i in linked if i.status.value == "sold")
    item_values = [
        i.current_market_value if i.current_market_value is not None else i.cost_basis
        for i in linked
    ]
    total_value = sum(v for v in item_values if v is not None)

    return {
        "consignor_id": consignor_id,
        "total_items": total_items,
        "items_sold": items_sold,
        "total_value": str(total_value),
    }
