"""``/admin/show-prep`` — Show prep workflows.

Pre-show tasks: find mispriced cards (market value drifted from listed),
bulk-move items between locations, and get location summaries.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from merlins_collection.dependencies import get_repo
from merlins_collection.models.inventory import InventoryItemAdapter, ItemStatus
from merlins_collection.services.dynamodb import InventoryRepository

router = APIRouter(prefix="/show-prep", tags=["admin-show-prep"])


# ---------------------------------------------------------------------------
# Mispriced Cards
# ---------------------------------------------------------------------------

@router.get("/mispriced")
def get_mispriced_cards(
    threshold: int = Query(10, ge=1, le=500),
    threshold_mode: str = Query("percent"),
    location: str | None = Query(None),
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Find cards where current_market_value has drifted from listed/stored value.

    Returns items where the price delta exceeds the threshold.
    ``threshold_mode`` can be ``percent`` (default) or ``dollar``.
    Only considers AVAILABLE items with a known market value.
    """
    items = repo.list_inventory()

    # Filter to available items with market values
    items = [
        i for i in items
        if i.status == ItemStatus.AVAILABLE
        and i.current_market_value is not None
        and i.cost_basis is not None
    ]

    if location is not None:
        items = [i for i in items if getattr(i, "location", None) == location]

    flagged = []
    for item in items:
        market = item.current_market_value
        cost = item.cost_basis
        if cost == 0:
            continue

        # Calculate margin percentage and dollar delta
        margin_pct = ((market - cost) / cost * 100).quantize(Decimal("0.1"))
        dollar_delta = (market - cost).quantize(Decimal("0.01"))

        # Flag based on mode
        if threshold_mode == "dollar":
            if abs(dollar_delta) >= Decimal(str(threshold)):
                flagged.append({
                    "item_id": item.item_id,
                    "card_id": getattr(item, "card_id", None),
                    "name": getattr(item, "display_name", None) or getattr(item, "product_name", None) or "",
                    "location": getattr(item, "location", None),
                    "cost_basis": str(cost),
                    "current_market_value": str(market),
                    "sticker_price": str(item.sticker_price) if item.sticker_price is not None else None,
                    "delta_pct": str(margin_pct),
                    "delta_dollar": str(dollar_delta),
                })
        else:
            if abs(margin_pct) >= threshold:
                flagged.append({
                    "item_id": item.item_id,
                    "card_id": getattr(item, "card_id", None),
                    "name": getattr(item, "display_name", None) or getattr(item, "product_name", None) or "",
                    "location": getattr(item, "location", None),
                    "cost_basis": str(cost),
                    "current_market_value": str(market),
                    "sticker_price": str(item.sticker_price) if item.sticker_price is not None else None,
                    "delta_pct": str(margin_pct),
                    "delta_dollar": str(dollar_delta),
                })

    # Sort by absolute delta descending
    flagged.sort(key=lambda x: abs(Decimal(x["delta_pct"])), reverse=True)

    return {"items": flagged, "total_flagged": len(flagged)}


# ---------------------------------------------------------------------------
# Bulk Move
# ---------------------------------------------------------------------------

@router.post("/bulk-move")
def bulk_move_items(
    body: dict[str, Any],
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Move multiple items to a new location."""
    item_ids = body.get("item_ids", [])
    new_location = body.get("new_location")

    if not item_ids:
        raise HTTPException(status_code=422, detail="item_ids required")
    if not new_location:
        raise HTTPException(status_code=422, detail="new_location required")

    moved = 0
    errors = []

    for item_id in item_ids:
        item = repo.get_inventory_item(item_id)
        if item is None:
            errors.append({"item_id": item_id, "error": "not found"})
            continue

        # Update location
        data = item.model_dump(mode="python")
        data["location"] = new_location
        updated = InventoryItemAdapter.validate_python(data)
        repo.put_inventory_item(updated)
        moved += 1

    return {
        "moved": moved,
        "errors": errors,
        "new_location": new_location,
    }


# ---------------------------------------------------------------------------
# Location Summary
# ---------------------------------------------------------------------------

@router.get("/location-summary")
def location_summary(
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Get item counts grouped by location."""
    items = repo.list_inventory()
    items = [i for i in items if i.status == ItemStatus.AVAILABLE]

    counts: dict[str, int] = {}
    for item in items:
        loc = getattr(item, "location", None) or "unknown"
        counts[loc] = counts.get(loc, 0) + 1

    return {"locations": counts, "total": sum(counts.values())}
