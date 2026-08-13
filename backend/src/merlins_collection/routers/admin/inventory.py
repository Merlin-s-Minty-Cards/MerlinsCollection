"""``/admin/inventory`` — Admin inventory CRUD with full visibility.

Unlike the customer ``/inventory/search``, this surface:
- Exposes ALL fields (cost_basis, consignment, notes, location, etc.)
- Shows ALL statuses (sold, lost, on_hold, etc.)
- Supports location-based filtering
- Allows create, update, and delete operations
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from merlins_collection.dependencies import get_repo
from merlins_collection.models.inventory import (
    MACHINE_REVIEW_REASONS,
    Condition,
    ConditionModifier,
    InventoryItem,
    InventoryItemAdapter,
    ItemStatus,
    _market_price,
    new_ulid,
    normalize_condition,
)
from merlins_collection.services.card_text import admin_item_name
from merlins_collection.services.condition_pricing import (
    apply_condition_adjustment,
    condition_multiplier,
)
from merlins_collection.services.dynamodb import InventoryRepository
from merlins_collection.services.inventory_filters import (
    FieldFilter,
    apply_filters,
    validate_filters,
)
from merlins_collection.services.inventory_sort import (
    SORT_FIELDS,
    parse_sort,
    sort_items,
)
from merlins_collection.services.locations import validate_location
from merlins_collection.services.triage import (
    TRIAGE_REASONS,
    in_triage_scope,
    is_bulk_clearable,
    is_missing_card_id,
    is_missing_english_name,
    needs_triage,
    reasons_for,
)

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
    set_id: str | None = Query(None, max_length=100),
    set_name: str | None = Query(None, max_length=200),
    ownership: str | None = Query(None),
    needs_review: bool | None = Query(None),
    # RFC 0011 T5: the unmatched queue is THIS endpoint with this parameter, not
    # a new list route — the same "reuse before adding" rule that keeps Triage on
    # the shared search. `false` is a real query, not a synonym for unset: it is
    # how an ordinary inventory list hides the parked cohort.
    no_catalog_match: bool | None = Query(None),
    missing_sticker: bool = Query(False),
    # Triage (T11). `triage` is the one OR on this endpoint — the union of every
    # reason — while the ones below narrow WITHIN it like every other filter here.
    triage: bool = Query(False),
    # RFC 0010 T3: ONE parameter, validated against the predicate set that built
    # the union, so `flagged` narrows by the predicate that produced the chip
    # rather than by the stored boolean, and a new reason needs no new param.
    # The three below are kept for backward compatibility; the Triage page has
    # stopped sending them.
    triage_reason: str | None = Query(None, max_length=64),
    include_terminal: bool = Query(False),
    missing_card_id: bool = Query(False),
    missing_english_name: bool = Query(False),
    min_price: Decimal | None = Query(None, ge=0),
    max_price: Decimal | None = Query(None, ge=0),
    min_profit: Decimal | None = Query(None),
    max_profit: Decimal | None = Query(None),
    sort: str | None = Query(None),
    # RFC 0011 T3: the generic, registry-validated filter. Repeatable —
    # `?filter=notes:contains:foil&filter=cost_basis:gte:100`. The named parameters
    # above are kept and build the SAME FieldFilter objects, so there are two
    # spellings but only ever one evaluator.
    filter_: list[str] = Query(default_factory=list, alias="filter"),
    repo: InventoryRepository = Depends(get_repo),
) -> AdminInventorySearchResult:
    """Search inventory with full admin visibility.

    All items across all statuses are returned. Filters are AND-combined.
    Unlike the customer search, there is no location restriction and
    cost_basis/margin data is included in the response.
    """
    # Checked before the table read: an unknown reason key is a caller mistake,
    # and it must be LOUD. Ignoring it silently returns the whole union, which
    # looks exactly like the "the filter doesn't filter" report this replaced.
    _validate_triage_reason(triage_reason)
    # Same rule, same place: before the table read, because a caller mistake must not
    # cost a full `list_inventory()` scan first.
    _validate_sort(sort)
    parsed_filters = _validate_filters(filter_)

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

    if needs_review is not None:
        items = [i for i in items if i.needs_review == needs_review]

    if no_catalog_match is not None:
        # `getattr` with a default rather than attribute access: a row written
        # before the field existed loads without it, and defaulting to False is
        # what makes the queue ship empty instead of scooping up every legacy
        # unlinked card.
        items = [
            i for i in items
            if getattr(i, "no_catalog_match", False) == no_catalog_match
        ]

    # Show-prep queue: everything still waiting for a price sticker.
    if missing_sticker:
        items = [i for i in items if i.sticker_price is None]

    # Triage. The predicates live in services.triage so the list and the sidebar
    # badge (`GET /admin/triage/counts`) can never disagree about what counts.
    if triage:
        items = [
            i for i in items
            if needs_triage(i) and in_triage_scope(i, include_terminal=include_terminal)
        ]

    # Narrows WITHIN the union, using the same predicate that put the item there.
    if triage_reason is not None:
        matches_reason = TRIAGE_REASONS[triage_reason]
        items = [i for i in items if matches_reason(i)]

    if missing_card_id:
        items = [i for i in items if is_missing_card_id(i)]

    if missing_english_name:
        items = [i for i in items if is_missing_english_name(i)]

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

    # Lifetime profit needs the FULL lineage — a chain member may already
    # have been filtered out above (e.g. a SOLD predecessor when this search
    # is scoped to status=available), so this refetches the whole table
    # rather than reusing `items`, or the chain walk below would silently
    # under-count. Only paid when the filter is actually requested. The
    # per-item cumulative profit is computed in one batched pass
    # (`_lifetime_profit_map`) rather than one chain walk per candidate item,
    # since candidates sharing a lineage would otherwise re-walk and
    # re-fetch timeline events for the same chain over and over. The walk
    # itself is further scoped to only the lineages `items` (the
    # already-filtered candidates, e.g. after `name` narrowed the table down
    # to a handful of rows) actually belong to — membership within each
    # walked group still comes from the full `items_by_id` map, so a chain
    # member excluded by an earlier filter is still counted, but a lineage
    # nothing in `items` belongs to is never fetched at all.
    if min_profit is not None or max_profit is not None:
        items_by_id = {i.item_id: i for i in repo.list_inventory()}
        needed_lineage_ids = {i.lineage_id or i.item_id for i in items}
        profit_map = _lifetime_profit_map(items_by_id, repo, only_lineages=needed_lineage_ids)
        items = [
            i for i in items
            if (profit := profit_map.get(i.item_id, Decimal("0"))) is not None
            and (min_profit is None or profit >= min_profit)
            and (max_profit is None or profit <= max_profit)
        ]

    # T8: exact set membership, resolved through the GSI1 `SET#` partition —
    # one query, not the catalog walk `set_name` below does. This is what the
    # set combobox sends, and why it sends an id: set NAMES are not unique
    # across languages ("Base Set" is both `en:base1` and `ja:base1`) and a
    # substring like "Sun & Moon" spans a dozen sets, so picking one entry from
    # a dropdown and getting several sets back would defeat the control. An
    # item with no catalog link belongs to no set and is excluded — including
    # sealed and bulk items, which have no `card_id` field at all.
    if set_id is not None:
        set_card_ids = {c.card_id for c in repo.list_cards_by_set(set_id)}
        items = [i for i in items if getattr(i, "card_id", None) in set_card_ids]

    # A5: Catalog-based filters (card_number, artist, set_name) — joins the catalog
    if card_number is not None or artist is not None or set_name is not None:
        items = _filter_by_catalog(
            items, repo, card_number=card_number, artist=artist, set_name=set_name,
        )

    # RFC 0011 T3: the generic filters, applied AFTER the named ones so an admin
    # combining both gets the intersection. `apply_filters` raises ValueError on a
    # bound it cannot parse (a date field given "yesterday"), which is a caller
    # mistake and must be as loud as an unknown field.
    if parsed_filters:
        try:
            items = apply_filters(items, parsed_filters)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Sort
    items = _sort_admin_results(items, sort)

    # Serialize with full fields
    serialized = [_serialize_item(i) for i in items]

    # Triage rows carry their catalog card so the page can render the EFFECTIVE
    # name — `display_name_override -> card.name -> display_name` (T10). Without
    # the join the page can only ever show the fallback, and an admin fixing a
    # name would be working blind against the one field that outranks theirs.
    # Scoped to `triage` so the ordinary admin search keeps its payload and its
    # cost; the triage cohort is tens of rows, not the whole table.
    if triage:
        _attach_catalog_cards(serialized, repo)
        _attach_triage_reasons(serialized, items)

    return AdminInventorySearchResult(items=serialized, total=len(serialized))


# ---------------------------------------------------------------------------
# Bulk clear of machine review flags
# ---------------------------------------------------------------------------

class BulkClearReviewRequest(BaseModel):
    """The filter the admin is currently looking at.

    Mirrors the search's own triage arguments so "clear what I can see" is
    expressible, rather than offering a bare "clear everything" that nobody can
    predict the effect of.
    """

    triage_reason: str | None = None
    include_terminal: bool = False
    name: str | None = None


class BulkClearReviewResponse(BaseModel):
    """How many flags were actually dropped — the UI names this number first."""

    cleared: int


@router.post("/bulk-clear-review", response_model=BulkClearReviewResponse)
def admin_bulk_clear_review(
    body: BulkClearReviewRequest,
    repo: InventoryRepository = Depends(get_repo),
) -> BulkClearReviewResponse:
    """Clear ``needs_review`` on the machine-flagged items matching the filter.

    Deliberately narrow — see ``services.triage.is_bulk_clearable``. A human's
    free-text flag is never touched, and ``blank_condition`` is excluded because
    clearing it accepts an NM price on a card nobody has graded.

    ``reviewed_at`` is stamped, so ``_apply_review_transition``'s rule 2 stops
    automation re-flagging what this just cleared — the bulk path inherits the
    anti-rot guarantee rather than routing around it.
    """
    _validate_triage_reason(body.triage_reason)

    items = [
        i for i in repo.list_inventory()
        if needs_triage(i) and in_triage_scope(i, include_terminal=body.include_terminal)
    ]
    if body.triage_reason is not None:
        matches_reason = TRIAGE_REASONS[body.triage_reason]
        items = [i for i in items if matches_reason(i)]
    if body.name is not None:
        name_lower = body.name.lower()
        items = [i for i in items if _item_matches_name(i, name_lower)]

    now = datetime.now(tz=timezone.utc)
    cleared = 0
    for item in items:
        if not is_bulk_clearable(item):
            continue
        before = item.model_dump(mode="python")
        updated = InventoryItemAdapter.validate_python({
            **before,
            "needs_review": False,
            "review_reason": None,
            "reviewed_at": now,
        })
        repo.put_inventory_item(updated)
        # Same audit trail a single-item edit gets. A bulk mutation is the last
        # place to drop it: it is the one that overwrites many rows at once.
        changed_fields = _diff_fields(before, updated.model_dump(mode="python"))
        if changed_fields:
            repo.put_timeline_event(item.item_id, {
                "item_id": item.item_id,
                "txn_id": new_ulid(),
                "type": "edit",
                "date": date.today().isoformat(),
                "changed_fields": changed_fields,
            })
        cleared += 1

    return BulkClearReviewResponse(cleared=cleared)


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
    validate_location(repo, body.get("location"), required=True)

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
    # Re-pointing a card is a first-class Triage action, so the id it lands on
    # has to exist. The importer already validates the composite against the
    # catalog index before storing it (services/spreadsheet_import.py); this
    # endpoint did not, so a stale or hand-typed id silently linked an item to a
    # phantom card that resolves no price, no image and no set — and then
    # reappears in Triage looking unlinked while actually carrying a bad id.
    #
    # Only what the request CHANGES is checked. Validating the whole row would
    # make a single bad legacy card_id uneditable, including from the very tool
    # meant to repair it. ``None`` stays allowed: unlinking is a real repair for
    # a match that was simply wrong.
    if "card_id" in body and body["card_id"] is not None:
        if repo.get_catalog_card(str(body["card_id"])) is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"card_id {body['card_id']!r} is not in the catalog. "
                    "Pick a card from search, or clear the link instead."
                ),
            )
    body = _apply_review_transition(existing, body)
    body = _apply_no_catalog_match_transition(existing, body)

    # Merge: dump existing to dict, overlay with update body, re-validate
    current_data = existing.model_dump(mode="python")
    current_data.update(body)
    # Ensure item_id cannot be changed
    current_data["item_id"] = item_id

    try:
        updated_item = InventoryItemAdapter.validate_python(current_data)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Diff the VALIDATED before/after dumps, not the raw request body, and
    # only after validation succeeds. Diffing the raw body would (a) record
    # an unknown/typo'd key (e.g. "locaton") as a change even though
    # Pydantic's extra='ignore' silently dropped it and nothing was actually
    # stored, and (b) show a spurious diff for a value re-typed in a
    # different but equal literal form (e.g. "10.0" vs stored "10.00").
    # Running this after validation also means a rejected update (422 above)
    # writes no audit event at all.
    changed_fields = _diff_fields(
        existing.model_dump(mode="python"), updated_item.model_dump(mode="python"),
    )

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
            # RFC 0010 T11. A `voided` / `void_restored` event carries the id of
            # the transaction it withdrew, so the History page can strike
            # through the original sale rather than merely appending a note
            # nobody connects to it. The original sale event is untouched — the
            # timeline is a history, and history includes the mistake.
            "voided_txn_id": e.get("voided_txn_id"),
            "void_reason": e.get("void_reason"),
            "voided_at": e.get("voided_at"),
            "voided_by": e.get("voided_by"),
            "restored_at": e.get("restored_at"),
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

    item_map = {i.item_id: i for i in lineage_items}
    ordered = _build_lineage_chain(item, item_map)

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
            # The CATALOG card, so the History page can show each link's art.
            # `None` for sealed/bulk links, which have no catalog row at all.
            "card_id": getattr(node, "card_id", None),
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
    return admin_item_name(item)


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


def _build_lineage_chain(
    item: InventoryItem, items_by_id: dict[str, InventoryItem],
) -> list[InventoryItem]:
    """Order an item's trade chain from root to tip by walking predecessor_item_id.

    ``items_by_id`` should already be scoped to items sharing ``item``'s
    lineage_id (or be item_id-keyed broadly — entries unreachable from the
    root by predecessor links are simply not included in the result).
    """
    lineage_id = item.lineage_id or item.item_id
    lineage_items = [
        i for i in items_by_id.values()
        if (i.lineage_id == lineage_id) or (i.item_id == lineage_id and i.lineage_id is None)
    ] or [item]
    chain_map = {i.item_id: i for i in lineage_items}
    roots = [
        i for i in lineage_items
        if i.predecessor_item_id is None or i.predecessor_item_id not in chain_map
    ]

    ordered: list[InventoryItem] = []
    current: InventoryItem | None = roots[0] if roots else item
    visited: set[str] = set()
    while current and current.item_id not in visited:
        visited.add(current.item_id)
        ordered.append(current)
        current = next(
            (
                i for i in lineage_items
                if i.predecessor_item_id == current.item_id and i.item_id not in visited
            ),
            None,
        )
    return ordered


def _lifetime_profit_map(
    items_by_id: dict[str, InventoryItem],
    repo: InventoryRepository,
    only_lineages: set[str] | None = None,
) -> dict[str, Decimal]:
    """Cumulative profit for every item in items_by_id, one walk per lineage.

    A naive per-item chain walk is O(chain-length^2) timeline fetches when
    called once per candidate item in a filter over many items sharing
    chains (each item at chain position k re-walks and re-fetches k+1
    nodes). This groups by lineage first and walks each distinct chain
    exactly once, same figure as ``cumulative_profit`` in
    ``admin_item_lineage`` computed for every node along the way.

    ``only_lineages``, when given, skips walking (and fetching timeline
    events for) any lineage group whose key isn't in the set — the caller
    already knows which lineages its candidates belong to and there is no
    reason to pay for chains nothing in the result set is a member of.
    Group membership itself still comes from the full ``items_by_id`` map
    regardless of this filter, so a walked chain's members are complete.
    """
    groups: dict[str, list[InventoryItem]] = {}
    for i in items_by_id.values():
        key = i.lineage_id or i.item_id
        if only_lineages is not None and key not in only_lineages:
            continue
        groups.setdefault(key, []).append(i)

    result: dict[str, Decimal] = {}
    for members in groups.values():
        member_map = {m.item_id: m for m in members}
        ordered = _build_lineage_chain(members[0], member_map)
        cumulative = Decimal("0")
        for node in ordered:
            disposal = _disposal_event(repo.get_timeline_events(node.item_id))
            disposed_value = _event_amount(disposal) if disposal else None
            if disposed_value is not None:
                cumulative += (disposed_value - node.cost_basis).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP,
                )
            result[node.item_id] = cumulative
    return result


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
    before: dict[str, Any], after: dict[str, Any],
) -> dict[str, dict[str, str | None]]:
    """Which fields actually changed value, as ``{field: {"old": ..., "new": ...}}``.

    Both ``before`` and ``after`` must be ``model_dump(mode="python")`` of
    the pre- and post-update model — never the raw request body. Comparing
    validated dumps (not raw input) means a field Pydantic's ``extra=
    'ignore'`` silently dropped (an unknown/typo'd key) never reaches
    ``after`` and is correctly not recorded as a change. Values are compared
    as their native Python types (Decimal, date, enum) so e.g.
    ``Decimal("10.00") == Decimal("10.0")`` is correctly seen as unchanged,
    instead of a spurious diff from comparing differently-formatted literal
    strings. The recorded old/new are stringified afterward only for the
    audit trail / API response.
    """
    changed: dict[str, dict[str, str | None]] = {}
    for key, new_value in after.items():
        if key == "item_id":
            continue
        old_value = before.get(key)
        if old_value != new_value:
            old_str = None if old_value is None else str(old_value)
            new_str = None if new_value is None else str(new_value)
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
    """Sort items by the requested criteria — see ``services.inventory_sort``.

    Sort format: ``{field}_{direction}`` e.g. ``name_asc``, ``cost_basis_desc``.

    This used to be an if/elif chain over EIGHT field names while the admin table
    offered thirty-three columns, so twenty-five headers had no order at all and an
    unknown field fell through to ``return ""`` — every row comparing equal, which
    reads as "sorting is broken" (RFC 0011 §A). The registry now covers every model
    field, missing values sort last in both directions, and ``condition`` orders by
    rank rather than alphabetically.
    """
    return sort_items(items, sort)


def _attach_catalog_cards(
    rows: list[dict[str, Any]], repo: InventoryRepository,
) -> None:
    """Set ``row["card"]`` on each serialized row, in place.

    Always sets the key — ``None`` for an unlinked item or a dangling
    ``card_id`` — so the frontend can distinguish "no catalog row" from "this
    response shape does not carry one" without guessing.
    """
    cache: dict[str, dict[str, Any] | None] = {}
    for row in rows:
        card_id = row.get("card_id")
        if not card_id:
            row["card"] = None
            continue
        if card_id not in cache:
            card = repo.get_catalog_card(card_id)
            cache[card_id] = card.model_dump(mode="json") if card is not None else None
        row["card"] = cache[card_id]


def _validate_filters(raws: list[str]) -> list[FieldFilter]:
    """Parse the generic ``filter`` params, or 422.

    Three distinct caller mistakes get three distinct messages — a malformed triple, an
    unknown field, and an operator the field's kind does not support. The alternative,
    ignoring what we cannot parse, produces a response identical to "no filter was
    applied", which is the failure this whole parameter was designed around.
    """
    try:
        return validate_filters(raws)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _validate_sort(sort: str | None) -> None:
    """422 on a sort field that is not in the registry.

    Never a silent no-op. An ignored ``sort`` returns the list in table order, which
    looks exactly like "this column has no order" from the admin's side — the same
    indistinguishable-failure class ``_validate_triage_reason`` below was written to
    eliminate, and the reason twenty-five dead headers went unnoticed for so long.
    """
    if sort is not None and parse_sort(sort) is None:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unknown sort {sort!r}. Expected {{field}}_asc or {{field}}_desc, "
                f"where field is one of: {', '.join(sorted(SORT_FIELDS))}."
            ),
        )


def _validate_triage_reason(reason: str | None) -> None:
    """422 on a reason key that is not one of the predicates.

    Never a silent no-op. A filter that quietly does nothing is indistinguishable
    from a list that is pulling everything — which is exactly the report this
    parameter exists to answer.
    """
    if reason is not None and reason not in TRIAGE_REASONS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unknown triage reason {reason!r}. "
                f"Expected one of: {', '.join(TRIAGE_REASONS)}."
            ),
        )


def _attach_triage_reasons(
    rows: list[dict[str, Any]], items: list[InventoryItem],
) -> None:
    """Set ``triage_reasons`` and ``bulk_clearable`` on each serialized row.

    ``rows`` is ``[_serialize_item(i) for i in items]``, so the two are parallel.

    Emitted by the SERVER rather than recomputed in the client: the rules live in
    one module, and a row rendered with no reason is the defect the whole feature
    is being corrected for. ``bulk_clearable`` rides along so the confirm dialog
    can name an exact count without the client re-deriving
    ``MACHINE_REVIEW_REASONS`` membership — a second copy of that rule is how the
    two would come to disagree about what a bulk clear is about to destroy.

    Scoped to ``triage`` for the same reason the catalog join is: the ordinary
    admin search keeps its payload and its cost.
    """
    for row, item in zip(rows, items, strict=True):
        row["triage_reasons"] = reasons_for(item)
        row["bulk_clearable"] = is_bulk_clearable(item)


def _apply_review_transition(
    existing: InventoryItem, body: dict[str, Any],
) -> dict[str, Any]:
    """Resolve a ``needs_review`` change into the fields actually written.

    Three rules, all of them about keeping the Triage queue drainable:

    1. **Clearing stamps ``reviewed_at``** (server clock — a client's own clock
       is not evidence that a human looked at the item).
    2. **Automation must not re-flag a reviewed item.** A write carrying a
       reason from ``MACHINE_REVIEW_REASONS`` is automation; if an admin has
       already inspected and passed this item, the flag is dropped. Without
       this the queue refills with cards nobody needs to look at, which is the
       standard failure mode for review queues.
    3. **A human always may re-flag**, and doing so clears the stale stamp —
       otherwise the row says "reviewed and passed" about an item that is back
       in the queue, and would suppress the next automated flag.

    NOTE: rule 2 is currently a guard against a FUTURE in-place re-matcher and
    against UI mistakes. No automated path writes ``needs_review`` onto an
    existing row today; the live re-import creates new rows and destroys
    ``reviewed_at`` outright. See docs/plans/rfc-0008/follow-ups.md (T11).
    """
    if "needs_review" not in body:
        return body

    body = dict(body)
    reason = body.get("review_reason")
    is_machine = isinstance(reason, str) and reason in MACHINE_REVIEW_REASONS

    if body["needs_review"]:
        if is_machine and existing.reviewed_at is not None:
            # Rule 2 — leave the item exactly as the admin left it. Popping
            # both keys (rather than forcing False) keeps the merge a no-op, so
            # this write records no spurious `edit` timeline event either.
            body.pop("needs_review")
            body.pop("review_reason", None)
        else:
            body["reviewed_at"] = None  # rule 3
    else:
        body["reviewed_at"] = datetime.now(tz=timezone.utc)  # rule 1

    return body


def _apply_no_catalog_match_transition(
    existing: InventoryItem, body: dict[str, Any],
) -> dict[str, Any]:
    """Resolve a ``no_catalog_match`` change into the fields actually written.

    Four rules, all of them about keeping the unmatched queue drainable:

    1. **Only a catalog-linkable kind can be parked.** Sealed product and bulk
       lots have no ``card_id`` field at all, so there is no catalog link for
       them to be missing — the same ``hasattr`` reasoning
       ``triage.is_missing_card_id`` documents. The model validator cannot catch
       this one, because a sealed item has no ``card_id`` to be non-None.
    2. **Parking stamps ``no_catalog_match_at`` server-side**, and the client's
       own value is discarded. A client clock is not evidence of when a human
       looked, exactly as with ``reviewed_at``.
    3. **Unparking clears the stamp.** Parking that cannot be undone is just a
       slower delete, and a stale "parked 3 weeks ago" on an active card is a
       lie the queue would render.
    4. **Assigning a ``card_id`` unparks.** Pairing is the exit condition, and
       requiring a SECOND write to leave the queue is how rows get stranded in
       it. This runs LAST so a body carrying both a ``card_id`` and
       ``no_catalog_match: true`` resolves to "paired" rather than tripping the
       model's invariant.
    """
    body = dict(body)

    if body.get("no_catalog_match") and not hasattr(existing, "card_id"):
        raise HTTPException(
            status_code=422,
            detail=(
                f"A {existing.kind} item has no catalog link to be missing. "
                "Only raw and graded items can be marked as having no catalog "
                "match."
            ),
        )

    # Never client-supplied. Popped before the branches below so a request that
    # sends the stamp alone cannot rewrite history either.
    body.pop("no_catalog_match_at", None)

    if "no_catalog_match" in body:
        if body["no_catalog_match"]:
            if not existing.no_catalog_match:
                body["no_catalog_match_at"] = datetime.now(tz=timezone.utc)
        else:
            body["no_catalog_match_at"] = None

    if body.get("card_id") is not None:
        body["no_catalog_match"] = False
        body["no_catalog_match_at"] = None

    return body


def _serialize_item(item: InventoryItem) -> dict[str, Any]:
    """Serialize an inventory item to dict with all fields (admin view).

    Converts Decimal/date/enum to JSON-safe types.

    ``condition_multiplier`` is DERIVED, not stored — the figure
    ``services/condition_pricing.py`` would scale a Near Mint price by for this
    card, or ``None`` for a kind that has no condition (graded, sealed, bulk).
    It rides on the row so the hand-valuation helper (RFC 0010 T16) can show an
    admin the arithmetic without a third copy of the multiplier table: the
    authority is Python and there is already one duplicate in
    ``mcp-server/src/condition-pricing.ts``, which is one more than the codebase
    should be maintaining.
    """
    data = item.model_dump(mode="json")
    condition = getattr(item, "condition", None)
    data["condition_multiplier"] = (
        str(condition_multiplier(condition, getattr(item, "condition_modifier", None)))
        if condition is not None
        else None
    )
    return data
