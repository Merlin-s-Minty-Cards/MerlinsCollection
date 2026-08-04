"""``/admin/inventory`` — Admin inventory CRUD with full visibility.

Unlike the customer ``/inventory/search``, this surface:
- Exposes ALL fields (cost_basis, consignment, notes, location, etc.)
- Shows ALL statuses (sold, lost, on_hold, etc.)
- Supports location-based filtering
- Allows create, update, and delete operations
"""

from __future__ import annotations

from datetime import date, timedelta
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
    card_number: str | None = Query(None, max_length=20),
    artist: str | None = Query(None, max_length=200),
    min_price: Decimal | None = Query(None, ge=0),
    max_price: Decimal | None = Query(None, ge=0),
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

    # A5: Price range filters (cost_basis)
    if min_price is not None:
        items = [i for i in items if i.cost_basis is not None and i.cost_basis >= min_price]

    if max_price is not None:
        items = [i for i in items if i.cost_basis is not None and i.cost_basis <= max_price]

    # A5: Catalog-based filters (card_number, artist) — requires joining with catalog
    if card_number is not None or artist is not None:
        items = _filter_by_catalog(items, repo, card_number=card_number, artist=artist)

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
# Timeline (A3)
# ---------------------------------------------------------------------------

@router.get("/{item_id}/timeline")
def admin_item_timeline(
    item_id: str,
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Get all timeline events for an item in chronological order."""
    item = repo.get_inventory_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")

    events = repo.get_timeline_events(item_id)
    # Strip DynamoDB keys from response
    clean_events = []
    for e in events:
        clean_events.append({
            "txn_id": e.get("txn_id"),
            "type": e.get("type"),
            "date": e.get("date"),
            "amount": e.get("amount"),
            "payment_method": e.get("payment_method"),
            "trade_id": e.get("trade_id"),
            "counterpart_item_id": e.get("counterpart_item_id"),
            "show_id": e.get("show_id"),
        })

    return {"item_id": item_id, "events": clean_events}


# ---------------------------------------------------------------------------
# Lineage (A3)
# ---------------------------------------------------------------------------

@router.get("/{item_id}/lineage")
def admin_item_lineage(
    item_id: str,
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Get the full trade chain for an item.

    Walks predecessor_item_id backward to find the root, then forward
    through items sharing the same lineage_id to build the complete chain.
    """
    item = repo.get_inventory_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")

    lineage_id = item.lineage_id or item.item_id

    # Find all items in this lineage
    all_items = repo.list_inventory()
    lineage_items = [
        i for i in all_items
        if (i.lineage_id == lineage_id) or (i.item_id == lineage_id and i.lineage_id is None)
    ]

    # If no items share this lineage, just return the current item
    if not lineage_items:
        lineage_items = [item]

    # Build chain by walking predecessor links
    # Create a map of item_id -> item
    item_map = {i.item_id: i for i in lineage_items}

    # Find the root (item with no predecessor or predecessor not in set)
    roots = [
        i for i in lineage_items
        if i.predecessor_item_id is None or i.predecessor_item_id not in item_map
    ]

    # Walk from root forward
    chain = []
    if roots:
        current = roots[0]
        visited = set()
        while current and current.item_id not in visited:
            visited.add(current.item_id)
            chain.append({
                "item_id": current.item_id,
                "name": getattr(current, "display_name", None) or getattr(current, "product_name", None) or "",
                "acquired_cost": str(current.cost_basis),
                "status": current.status.value,
            })
            # Find next in chain (item whose predecessor is current)
            next_item = None
            for i in lineage_items:
                if i.predecessor_item_id == current.item_id and i.item_id not in visited:
                    next_item = i
                    break
            current = next_item
    else:
        chain.append({
            "item_id": item.item_id,
            "name": getattr(item, "display_name", None) or "",
            "acquired_cost": str(item.cost_basis),
            "status": item.status.value,
        })

    return {
        "lineage_id": lineage_id,
        "chain": chain,
    }


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

@router.post("/refresh-prices")
def admin_refresh_market_prices(
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Refresh current_market_value for items missing it or linked to catalog.

    Iterates available items with a card_id, looks up the catalog card's latest
    market price for the item's finish, and updates the item if the catalog
    has a newer price. Returns count of items checked and updated.
    """
    items = repo.list_inventory()
    # Only process available items with a card_id
    eligible = [
        i for i in items
        if i.status == ItemStatus.AVAILABLE
        and getattr(i, "card_id", None) is not None
    ]

    checked = 0
    updated = 0

    for item in eligible:
        card_id = getattr(item, "card_id", None)
        if not card_id:
            continue

        card = repo.get_catalog_card(card_id)
        if card is None or not card.prices:
            checked += 1
            continue

        # Find the best market price for this item's finish
        finish = getattr(item, "finish", "normal")
        finish_price = card.prices.get(finish)
        if finish_price is None:
            # Try first available finish
            finish_price = next(iter(card.prices.values()), None)

        if finish_price is None or finish_price.market is None:
            checked += 1
            continue

        new_market = finish_price.market
        current = item.current_market_value

        # Update if missing or different
        if current is None or current != new_market:
            repo.update_item(item.item_id, {"current_market_value": new_market})
            updated += 1

        checked += 1

    return {
        "checked": checked,
        "updated": updated,
        "total_eligible": len(eligible),
    }


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

def _filter_by_catalog(
    items: list[InventoryItem],
    repo: InventoryRepository,
    *,
    card_number: str | None = None,
    artist: str | None = None,
) -> list[InventoryItem]:
    """Filter items by catalog card attributes (card_number, artist).

    Items without a card_id are excluded when these filters are active.
    Catalog cards are fetched in batch to avoid N+1 queries.
    """
    # Collect unique card_ids from items
    card_ids = list({
        getattr(item, "card_id", None)
        for item in items
        if getattr(item, "card_id", None) is not None
    })

    if not card_ids:
        return []

    # Batch-fetch catalog cards
    catalog_map = {}
    for card_id in card_ids:
        card = repo.get_catalog_card(card_id)
        if card is not None:
            catalog_map[card_id] = card

    result = []
    for item in items:
        item_card_id = getattr(item, "card_id", None)
        if item_card_id is None:
            continue
        card = catalog_map.get(item_card_id)
        if card is None:
            continue

        # Apply card_number filter (exact match)
        if card_number is not None:
            if card.number != card_number:
                continue

        # Apply artist filter (case-insensitive substring)
        if artist is not None:
            card_artist = getattr(card, "artist", None) or ""
            if artist.lower() not in card_artist.lower():
                continue

        result.append(item)

    return result


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
