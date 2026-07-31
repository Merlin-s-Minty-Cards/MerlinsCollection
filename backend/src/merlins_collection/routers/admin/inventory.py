"""``/admin/inventory`` — Admin inventory CRUD with full visibility.

Unlike the customer ``/inventory/search``, this surface:
- Exposes ALL fields (cost_basis, consignment, notes, location, etc.)
- Shows ALL statuses (sold, lost, on_hold, etc.)
- Supports location-based filtering
- Allows create, update, and delete operations
"""

from __future__ import annotations

from datetime import date, timedelta
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


class PriceChartPoint(BaseModel):
    """One data point for the price chart time-series."""

    date: str
    market_value: str


class BuyPriceMarker(BaseModel):
    """The purchase price dot for the chart overlay."""

    date: str
    price: str


class PriceChartResponse(BaseModel):
    """Time-series price data for Chart.js rendering."""

    points: list[PriceChartPoint]
    buy_marker: BuyPriceMarker | None = None
    timeframe: str
    item_id: str


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
        location_lower = location.lower()
        items = [i for i in items if (getattr(i, "location", None) or "").lower().find(location_lower) >= 0]

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
# Price chart
# ---------------------------------------------------------------------------

_TIMEFRAME_DAYS: dict[str, int] = {
    "1mo": 30,
    "3mo": 90,
    "6mo": 180,
    "1yr": 365,
    "2yr": 730,
}


@router.get("/{item_id}/price-chart", response_model=PriceChartResponse)
def admin_item_price_chart(
    item_id: str,
    timeframe: str = Query("1yr", pattern="^(1mo|3mo|6mo|1yr|2yr)$"),
    repo: InventoryRepository = Depends(get_repo),
) -> PriceChartResponse:
    """Return time-series price data for rendering a price chart.

    For raw/graded items with a card_id, uses the card-level price history
    (per-finish or per-grade). For sealed/bulk items (or items without a
    card link), uses item-level price points.

    Includes a buy_marker with cost_basis + acquired_at for chart overlay.
    """
    item = repo.get_inventory_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")

    days = _TIMEFRAME_DAYS.get(timeframe, 365)
    cutoff = date.today() - timedelta(days=days)

    points: list[PriceChartPoint] = []

    card_id = getattr(item, "card_id", None)

    if card_id and item.kind == "raw":
        # Card-level history filtered by finish
        finish = getattr(item, "finish", None)
        history = repo.get_price_history(
            card_id, finish=finish, start=cutoff,
        )
        for pp in history:
            if pp.market is not None:
                points.append(PriceChartPoint(
                    date=pp.date.isoformat(),
                    market_value=str(pp.market),
                ))
    elif card_id and item.kind == "graded":
        # Card-level history filtered by company + grade
        company = getattr(item, "company", None)
        grade = getattr(item, "grade", None)
        if company and grade is not None:
            history = repo.get_price_history(
                card_id, company=str(company), grade=grade, start=cutoff,
            )
            for pp in history:
                if pp.market is not None:
                    points.append(PriceChartPoint(
                        date=pp.date.isoformat(),
                        market_value=str(pp.market),
                    ))
    else:
        # Item-level history (sealed, bulk, or items without card_id)
        raw_history = repo.get_item_price_history(item_id)
        for rec in raw_history:
            rec_date = rec.get("date", "")
            rec_value = rec.get("market_value")
            if rec_date >= cutoff.isoformat() and rec_value is not None:
                points.append(PriceChartPoint(
                    date=rec_date,
                    market_value=str(rec_value),
                ))

    # Buy price marker
    buy_marker: BuyPriceMarker | None = None
    if item.cost_basis is not None and item.acquired_at is not None:
        buy_marker = BuyPriceMarker(
            date=item.acquired_at.isoformat(),
            price=str(item.cost_basis),
        )

    return PriceChartResponse(
        points=points,
        buy_marker=buy_marker,
        timeframe=timeframe,
        item_id=item_id,
    )


# ---------------------------------------------------------------------------
# Card images (bulk resolve)
# ---------------------------------------------------------------------------

@router.post("/card-images")
def admin_resolve_card_images(
    body: dict[str, Any],
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, str | None]:
    """Resolve card_ids to image URLs from the catalog.

    Accepts ``{"card_ids": ["sv1-1", "sv1-2", ...]}``.
    Returns a mapping of card_id → small image URL (or null if not found).
    Capped at 100 card_ids per request.
    """
    card_ids = body.get("card_ids", [])
    if not isinstance(card_ids, list):
        raise HTTPException(status_code=422, detail="card_ids must be a list")
    card_ids = card_ids[:100]  # cap to prevent abuse

    result: dict[str, str | None] = {}
    for card_id in card_ids:
        if not isinstance(card_id, str):
            continue
        card = repo.get_catalog_card(card_id)
        if card and card.images.small:
            result[card_id] = card.images.small
        else:
            result[card_id] = None
    return result


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
    """Sort items by the requested criteria.

    Sort format: ``{field}_{direction}`` e.g. ``name_asc``, ``cost_basis_desc``.
    Supported fields: price (alias for current_market_value), name, status,
    cost_basis, current_market_value, location, condition, display_name, kind.
    """
    if sort is None:
        return items

    # Parse sort parameter
    parts = sort.rsplit("_", 1)
    if len(parts) != 2 or parts[1] not in ("asc", "desc"):
        return items

    field, direction = parts
    reverse = direction == "desc"

    # Alias
    if field == "price":
        field = "current_market_value"

    def _get_sort_value(item: InventoryItem):
        if field in ("current_market_value", "cost_basis"):
            if field == "current_market_value":
                val = item.current_market_value
            else:
                val = item.cost_basis
            if val is None:
                return float("inf") if not reverse else float("-inf")
            return float(val)
        elif field in ("name", "display_name"):
            display = getattr(item, "display_name", None) or getattr(item, "product_name", None) or ""
            return display.lower()
        elif field == "status":
            return str(item.status)
        elif field == "location":
            loc = getattr(item, "location", None) or ""
            return loc.lower()
        elif field == "condition":
            cond = getattr(item, "condition", None) or ""
            return str(cond)
        elif field == "kind":
            return str(item.kind)
        else:
            return ""

    return sorted(items, key=_get_sort_value, reverse=reverse)


def _serialize_item(item: InventoryItem) -> dict[str, Any]:
    """Serialize an inventory item to dict with all fields (admin view).

    Converts Decimal/date/enum to JSON-safe types.
    """
    data = item.model_dump(mode="json")
    return data
