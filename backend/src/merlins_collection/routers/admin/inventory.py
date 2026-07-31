"""``/admin/inventory`` — Admin inventory CRUD with full visibility.

Unlike the customer ``/inventory/search``, this surface:
- Exposes ALL fields (cost_basis, consignment, notes, location, etc.)
- Shows ALL statuses (sold, lost, on_hold, etc.)
- Supports location-based filtering
- Allows create, update, and delete operations
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from merlins_collection.dependencies import get_repo
from merlins_collection.models.inventory import (
    Condition,
    InventoryItem,
    InventoryItemAdapter,
    ItemStatus,
    new_ulid,
)
from merlins_collection.services.dynamodb import InventoryRepository

router = APIRouter(prefix="/inventory", tags=["admin-inventory"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class AdminInventorySearchResult(BaseModel):
    """Admin search response: all fields, all statuses."""

    items: list[dict[str, Any]]
    total: int


class AdminItemHistoryResponse(BaseModel):
    """Item price history and related transactions."""

    price_history: list[dict[str, Any]]
    transactions: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

@router.get("/search", response_model=AdminInventorySearchResult)
def admin_search_inventory(
    name: str | None = Query(None, max_length=200),
    status: ItemStatus | None = Query(None),
    location: str | None = Query(None),
    condition: Condition | None = Query(None),
    kind: str | None = Query(None),
    sort: str | None = Query(None),
    repo: InventoryRepository = Depends(get_repo),
) -> AdminInventorySearchResult:
    """Search inventory with full admin visibility.

    All items across all statuses are returned. Filters are AND-combined.
    Unlike the customer search, there is no location restriction and
    cost_basis/margin data is included in the response.
    """
    items = repo.list_inventory()

    # Apply filters
    if status is not None:
        items = [i for i in items if i.status == status]

    if location is not None:
        items = [i for i in items if getattr(i, "location", None) == location]

    if condition is not None:
        items = [i for i in items if i.kind == "raw" and i.condition == condition]

    if kind is not None:
        items = [i for i in items if i.kind == kind]

    if name is not None:
        name_lower = name.lower()
        items = [
            i for i in items
            if _item_matches_name(i, name_lower)
        ]

    # Sort
    items = _sort_admin_results(items, sort)

    # Serialize with full fields
    serialized = [_serialize_item(i) for i in items]

    return AdminInventorySearchResult(items=serialized, total=len(serialized))


# ---------------------------------------------------------------------------
# Get single item
# ---------------------------------------------------------------------------

@router.get("/{item_id}")
def admin_get_item(
    item_id: str,
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Get a single inventory item with all admin-visible fields."""
    item = repo.get_inventory_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return _serialize_item(item)


# ---------------------------------------------------------------------------
# Create item
# ---------------------------------------------------------------------------


@router.post("", status_code=201)
def admin_create_item(
    body: dict[str, Any],
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Create a new inventory item. The ``kind`` field determines the item type."""
    kind = body.get("kind")
    if kind not in ("raw", "graded", "sealed", "bulk"):
        raise HTTPException(status_code=422, detail=f"Invalid kind: {kind}")

    # Assign a new item_id
    body.setdefault("item_id", new_ulid())
    body.setdefault("status", "available")

    try:
        item = InventoryItemAdapter.validate_python(body)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    repo.put_inventory_item(item)
    return _serialize_item(item)


# ---------------------------------------------------------------------------
# Update item (partial)
# ---------------------------------------------------------------------------

@router.put("/{item_id}")
def admin_update_item(
    item_id: str,
    body: dict[str, Any],
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Partial update of an inventory item. Only provided fields are changed."""
    existing = repo.get_inventory_item(item_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Item not found")

    # Merge: dump existing to dict, overlay with update body, re-validate
    current_data = existing.model_dump(mode="python")
    current_data.update(body)
    # Ensure item_id cannot be changed
    current_data["item_id"] = item_id

    try:
        updated_item = InventoryItemAdapter.validate_python(current_data)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    repo.put_inventory_item(updated_item)
    return _serialize_item(updated_item)


# ---------------------------------------------------------------------------
# Delete item
# ---------------------------------------------------------------------------

@router.delete("/{item_id}")
def admin_delete_item(
    item_id: str,
    hard: bool = Query(False),
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, str]:
    """Delete an inventory item.

    By default, performs a soft-delete (sets status to LOST).
    With ``?hard=true``, permanently removes the item from the database.
    """
    existing = repo.get_inventory_item(item_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Item not found")

    if hard:
        repo.delete_inventory_item(item_id)
        return {"status": "deleted", "item_id": item_id, "mode": "hard"}
    else:
        # Soft-delete: set status to LOST
        current_data = existing.model_dump(mode="python")
        current_data["status"] = ItemStatus.LOST
        updated = InventoryItemAdapter.validate_python(current_data)
        repo.put_inventory_item(updated)
        return {"status": "deleted", "item_id": item_id, "mode": "soft"}


# ---------------------------------------------------------------------------
# Item history
# ---------------------------------------------------------------------------

@router.get("/{item_id}/history", response_model=AdminItemHistoryResponse)
def admin_item_history(
    item_id: str,
    repo: InventoryRepository = Depends(get_repo),
) -> AdminItemHistoryResponse:
    """Get price history and transactions for a specific item."""
    item = repo.get_inventory_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")

    # Price history for this item
    price_history = repo.get_item_price_history(item_id)

    # Transactions mentioning this item — scan last 12 months.
    end = date.today()
    start = date(end.year - 1, end.month, end.day)
    all_txns = repo.list_transactions(start, end)

    item_txns = [t for t in all_txns if t.item_id == item_id]

    return AdminItemHistoryResponse(
        price_history=price_history,
        transactions=[t.model_dump(mode="json") for t in item_txns],
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _item_matches_name(item: InventoryItem, name_lower: str) -> bool:
    """Check if an item matches a name substring (case-insensitive).

    Checks display_name, product_name, description, and notes.
    """
    display_name = getattr(item, "display_name", None)
    if display_name and name_lower in display_name.lower():
        return True
    product_name = getattr(item, "product_name", None)
    if product_name and name_lower in product_name.lower():
        return True
    description = getattr(item, "description", None)
    if description and name_lower in description.lower():
        return True
    notes = getattr(item, "notes", None)
    if notes and name_lower in notes.lower():
        return True
    return False


def _sort_admin_results(
    items: list[InventoryItem], sort: str | None
) -> list[InventoryItem]:
    """Sort items by the requested criteria. Priceless items sort last."""
    if sort is None:
        return items

    if sort in ("price_desc", "price_asc"):
        reverse = sort == "price_desc"

        def _key(item):
            price = item.current_market_value
            if price is None:
                # Priceless items always sort last: use a sentinel tuple.
                # When ascending, (1, 0) > (0, anything) so they sort last.
                # When descending (reversed), (0, anything) > (1, 0) is false,
                # so we need a different approach.
                return (1, Decimal(0))
            return (0, -price if reverse else price)

        # Always sort ascending — the key handles direction.
        return sorted(items, key=_key)

    return items


def _serialize_item(item: InventoryItem) -> dict[str, Any]:
    """Serialize an inventory item to dict with all fields (admin view).

    Converts Decimal/date/enum to JSON-safe types.
    """
    data = item.model_dump(mode="json")
    return data
