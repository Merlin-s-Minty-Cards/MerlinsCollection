"""``/admin/cosigners`` — Cosigner profile management.

A2: Full CRUD for consignor profiles, asset linking, and per-cosigner
analytics (total items, value, items sold).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from merlins_collection.dependencies import get_repo
from merlins_collection.models.business import Consignor
from merlins_collection.models.inventory import (
    ConsignmentTerms,
    InventoryItemAdapter,
)
from merlins_collection.services.dynamodb import InventoryRepository

router = APIRouter(prefix="/cosigners", tags=["admin-cosigners"])


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

@router.post("", status_code=201)
def create_cosigner(
    body: dict[str, Any],
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Create a new cosigner profile."""
    consignor = Consignor(
        name=body["name"],
        contact=body.get("contact"),
        email=body.get("email"),
        phone=body.get("phone"),
        payout_percent=Decimal(str(body.get("payout_percent", "50"))),
        active=body.get("active", True),
        notes=body.get("notes"),
    )
    repo.put_consignor(consignor)
    return consignor.model_dump(mode="json")


@router.get("")
def list_cosigners(
    repo: InventoryRepository = Depends(get_repo),
) -> list[dict[str, Any]]:
    """List all cosigner profiles."""
    cosigners = repo.list_consignors()
    return [c.model_dump(mode="json") for c in cosigners]


@router.get("/{consignor_id}")
def get_cosigner(
    consignor_id: str,
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Get a single cosigner profile."""
    consignor = repo.get_consignor(consignor_id)
    if consignor is None:
        raise HTTPException(status_code=404, detail="Cosigner not found")
    return consignor.model_dump(mode="json")


@router.patch("/{consignor_id}")
def update_cosigner(
    consignor_id: str,
    body: dict[str, Any],
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Partial update of a cosigner profile."""
    consignor = repo.get_consignor(consignor_id)
    if consignor is None:
        raise HTTPException(status_code=404, detail="Cosigner not found")

    # Merge updates
    data = consignor.model_dump(mode="python")
    for key in ("name", "contact", "email", "phone", "payout_percent", "active", "notes"):
        if key in body:
            if key == "payout_percent":
                data[key] = Decimal(str(body[key]))
            else:
                data[key] = body[key]

    updated = Consignor.model_validate(data)
    repo.put_consignor(updated)
    return updated.model_dump(mode="json")


@router.delete("/{consignor_id}")
def delete_cosigner(
    consignor_id: str,
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Deactivate a cosigner (soft delete — sets active=False)."""
    consignor = repo.get_consignor(consignor_id)
    if consignor is None:
        raise HTTPException(status_code=404, detail="Cosigner not found")

    data = consignor.model_dump(mode="python")
    data["active"] = False
    updated = Consignor.model_validate(data)
    repo.put_consignor(updated)
    return {"status": "deactivated", "consignor_id": consignor_id}


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
    split_percent = Decimal(str(body.get("split_percent", str(default_split))))
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
