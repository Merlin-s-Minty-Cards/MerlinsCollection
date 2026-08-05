"""``/admin/inventory`` — Admin inventory CRUD with full visibility.

Unlike the customer ``/inventory/search``, this surface:
- Exposes ALL fields (cost_basis, consignment, notes, location, etc.)
- Shows ALL statuses (sold, lost, on_hold, etc.)
- Supports location-based filtering
- Allows create, update, and delete operations
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from merlins_collection.dependencies import get_repo
from merlins_collection.models.inventory import (
    Condition,
    ConditionModifier,
    InventoryItem,
    InventoryItemAdapter,
    ItemStatus,
    _market_price,
    new_ulid,
    normalize_condition,
)
from merlins_collection.services.condition_pricing import apply_condition_adjustment
from merlins_collection.services.dynamodb import InventoryRepository
from merlins_collection.services.locations import validate_location

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
    condition: str | None = Query(None, max_length=8),
    kind: str | None = Query(None),
    card_number: str | None = Query(None, max_length=20),
    artist: str | None = Query(None, max_length=200),
    set_name: str | None = Query(None, max_length=200),
    ownership: str | None = Query(None),
    missing_sticker: bool = Query(False),
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
        items = [
            i for i in items
            if location_lower in (getattr(i, "location", None) or "").lower()
        ]

    if condition is not None:
        tier, modifier = _parse_condition_query(condition)
        items = [
            i for i in items
            if i.kind == "raw"
            and i.condition == tier
            # A bare tier ("LP") is the whole tier including LP+/LP-; a query
            # that names a modifier ("LP+") narrows to exactly that grade.
            and (modifier is None or i.condition_modifier == modifier)
        ]

    if kind is not None:
        items = [i for i in items if i.kind == kind]

    if name is not None:
        name_lower = name.lower()
        items = [
            i for i in items
            if _item_matches_name(i, name_lower)
        ]

    if ownership is not None:
        if ownership == "owned":
            items = [i for i in items if i.consignment is None]
        elif ownership == "cosigned":
            items = [i for i in items if i.consignment is not None]
        else:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid ownership '{ownership}'. Expected 'owned' or 'cosigned'.",
            )

    # Show-prep queue: everything still waiting for a price sticker.
    if missing_sticker:
        items = [i for i in items if i.sticker_price is None]

    # Price range filters compare against what the item is worth NOW, falling
    # back to what it cost only when no market figure is known. Filtering on
    # cost alone made "show me my $100+ cards" answer a different question.
    if min_price is not None:
        items = [
            i for i in items
            if (v := _effective_price(i)) is not None and v >= min_price
        ]

    if max_price is not None:
        items = [
            i for i in items
            if (v := _effective_price(i)) is not None and v <= max_price
        ]

    # A5: Catalog-based filters (card_number, artist, set_name) — joins the catalog
    if card_number is not None or artist is not None or set_name is not None:
        items = _filter_by_catalog(
            items, repo, card_number=card_number, artist=artist, set_name=set_name,
        )

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

    body = _split_combined_condition(body)
    if "location" in body:
        validate_location(repo, body.get("location"))

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

    body = _split_combined_condition(body)
    if "location" in body:
        validate_location(repo, body.get("location"), required=True)

    # Merge: dump existing to dict, overlay with update body, re-validate
    current_data = existing.model_dump(mode="python")
    changed_fields = _diff_fields(current_data, body)
    current_data.update(body)
    # Ensure item_id cannot be changed
    current_data["item_id"] = item_id

    try:
        updated_item = InventoryItemAdapter.validate_python(current_data)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    repo.put_inventory_item(updated_item)

    # A manual edit is the only mutation path with no built-in transaction
    # record (purchases/sales/trades all write one) — without this, the
    # prior value is unrecoverably overwritten with no audit trail.
    if changed_fields:
        repo.put_timeline_event(item_id, {
            "item_id": item_id,
            "txn_id": new_ulid(),
            "type": "edit",
            "date": date.today().isoformat(),
            "changed_fields": changed_fields,
        })

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
            "changed_fields": e.get("changed_fields"),
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
    ordered: list[InventoryItem] = []
    if roots:
        current = roots[0]
        visited = set()
        while current and current.item_id not in visited:
            visited.add(current.item_id)
            ordered.append(current)
            # Find next in chain (item whose predecessor is current)
            next_item = None
            for i in lineage_items:
                if i.predecessor_item_id == current.item_id and i.item_id not in visited:
                    next_item = i
                    break
            current = next_item
    else:
        ordered.append(item)

    # Profit is only knowable per NODE: a trade chain's value is the sum of what
    # each link was disposed for minus what it cost to acquire. Disposal comes
    # from the item's own timeline (the same events the /timeline endpoint
    # reads), not from status, because a trade-out and a cash sale are both
    # "gone" but only one of them ends the chain.
    chain: list[dict[str, Any]] = []
    cumulative = Decimal("0")
    last_exit_event: dict[str, Any] | None = None

    for node in ordered:
        disposal = _disposal_event(repo.get_timeline_events(node.item_id))
        last_exit_event = disposal

        disposed_via = disposal["type"] if disposal else None
        disposed_value = _event_amount(disposal) if disposal else None

        step_profit: Decimal | None = None
        if disposed_value is not None:
            step_profit = (disposed_value - node.cost_basis).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP,
            )
            cumulative += step_profit

        chain.append({
            "item_id": node.item_id,
            "name": _node_name(node),
            "acquired_cost": str(node.cost_basis),
            "status": node.status.value,
            "disposed_via": disposed_via,
            "disposed_value": None if disposed_value is None else str(disposed_value),
            "step_profit": None if step_profit is None else str(step_profit),
            "cumulative_profit": str(
                cumulative.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            ),
        })

    # The chain is only CLOSED when the final link left for money. A trade-out
    # (or a "sale" settled in trade) just hands the value to the next link.
    chain_complete = bool(
        last_exit_event
        and last_exit_event.get("type") == "sale"
        and str(last_exit_event.get("payment_method") or "") != "trade"
    )

    return {
        "lineage_id": lineage_id,
        "chain": chain,
        "chain_complete": chain_complete,
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
    """Refresh current_market_value for available RAW items linked to the catalog.

    This is the admin's on-demand version of the nightly
    ``catalog_sync.refresh_inventory_market_values`` pass, and it must agree
    with it card-for-card: it uses the SAME shared finish-aware lookup
    (``models.inventory._market_price``) and the SAME condition multiplier
    (``services.condition_pricing.apply_condition_adjustment``). It previously
    hand-rolled its own finish walk — a bare ``card.prices.get(item.finish)``
    with an arbitrary "first finish" fallback and no condition adjustment — so
    the two paths quoted different numbers for the same card, and it called a
    ``repo.update_item`` that does not exist (every would-be update raised).

    Graded slabs are skipped on purpose: catalog figures are UNGRADED prices,
    and a slab's value comes from its manual graded figure instead.
    """
    items = repo.list_inventory()
    # Only process available raw items with a card_id — the catalog price is an
    # ungraded, per-finish figure, so only raw singles can consume it.
    eligible = [
        i for i in items
        if i.status == ItemStatus.AVAILABLE
        and i.kind == "raw"
        and getattr(i, "card_id", None) is not None
    ]

    checked = 0
    updated = 0
    catalog_cache: dict[str, Any] = {}

    for item in eligible:
        checked += 1
        card_id = item.card_id

        if card_id not in catalog_cache:
            catalog_cache[card_id] = repo.get_catalog_card(card_id)
        card = catalog_cache[card_id]
        if card is None:
            continue

        value = _market_price(card, item.finish)
        if value is None:
            continue

        value, value_note = apply_condition_adjustment(
            value, item.condition, item.condition_modifier,
        )

        if value == item.current_market_value:
            continue

        update_fields: dict[str, Any] = {"current_market_value": value}
        if value_note is not None:
            update_fields["value_note"] = value_note
        repo.put_inventory_item(item.model_copy(update=update_fields))
        updated += 1

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

def _node_name(item: InventoryItem) -> str:
    """Best human label for an item, whatever kind it is."""
    return (
        getattr(item, "display_name", None)
        or getattr(item, "product_name", None)
        or ""
    )


_DISPOSAL_TYPES = ("sale", "trade_out")


def _disposal_event(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The LAST event that took an item out of stock, or ``None`` if still held.

    ``get_timeline_events`` already returns events in date order, so the last
    disposal wins — an item that was sold, returned and sold again reports the
    disposal that actually stuck.
    """
    disposals = [e for e in events if e.get("type") in _DISPOSAL_TYPES]
    return disposals[-1] if disposals else None


def _event_amount(event: dict[str, Any]) -> Decimal | None:
    """The event's amount as a Decimal (DynamoDB may hand back str or Decimal)."""
    amount = event.get("amount")
    if amount is None:
        return None
    try:
        return Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return None


def _split_combined_condition(body: dict[str, Any]) -> dict[str, Any]:
    """Expand a display ``condition`` (``"LP-"``) into the two stored fields.

    Every human-facing surface speaks one combined string; storage is always
    ``condition`` + ``condition_modifier``. Splitting here means the admin UI
    can POST/PUT exactly what it renders. A body carrying a bare tier is
    untouched apart from normalization, and an explicit ``condition_modifier``
    in the same body still wins (the caller was explicit).
    """
    raw = body.get("condition")
    if not isinstance(raw, str):
        return body

    try:
        tier, modifier = normalize_condition(raw)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid condition: {raw!r}") from exc

    updated = dict(body)
    updated["condition"] = tier.value
    if "condition_modifier" not in updated:
        updated["condition_modifier"] = modifier.value if modifier else None
    return updated


def _diff_fields(
    before: dict[str, Any], updates: dict[str, Any],
) -> dict[str, dict[str, str | None]]:
    """Which fields actually changed value, as ``{field: {"old": ..., "new": ...}}``.

    Compared as strings — ``before`` holds Python-native types (Decimal, date,
    enum) from ``model_dump(mode="python")`` while ``updates`` holds raw
    request-body values, so an exact-type comparison would treat e.g.
    ``Decimal("10.00")`` vs the (identical) incoming ``"10.00"`` as different.
    String comparison accepts the rare false-positive (a value re-typed in a
    different literal form) in exchange for never missing a real change.
    """
    changed: dict[str, dict[str, str | None]] = {}
    for key, new_value in updates.items():
        if key == "item_id":
            continue
        old_value = before.get(key)
        old_str = None if old_value is None else str(old_value)
        new_str = None if new_value is None else str(new_value)
        if old_str != new_str:
            changed[key] = {"old": old_str, "new": new_str}
    return changed


def _parse_condition_query(value: str) -> tuple[Condition, ConditionModifier | None]:
    """Parse a ``condition`` query value, 422-ing instead of 500-ing on garbage.

    The param used to be typed ``Condition``, which made the perfectly ordinary
    display values ``LP+``/``LP-`` a validation error the admin UI could not
    recover from.
    """
    try:
        return normalize_condition(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid condition '{value}'. Expected one of NM, LP+, LP, LP-, MP, HP, DMG.",
        ) from exc


def _effective_price(item: InventoryItem) -> Decimal | None:
    """What an item is worth for filtering: market value, else what it cost."""
    market = item.current_market_value
    return market if market is not None else item.cost_basis


def _filter_by_catalog(
    items: list[InventoryItem],
    repo: InventoryRepository,
    *,
    card_number: str | None = None,
    artist: str | None = None,
    set_name: str | None = None,
) -> list[InventoryItem]:
    """Filter items by catalog card attributes (card_number, artist, set_name).

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

        # Apply set_name filter (case-insensitive substring)
        if set_name is not None:
            card_set_name = getattr(card, "set_name", None) or ""
            if set_name.lower() not in card_set_name.lower():
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
            return _node_name(item).lower()
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
