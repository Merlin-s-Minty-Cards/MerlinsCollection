"""``/admin/market`` — Market lookup and watchlist management.

Provides catalog search against the locally-synced TCGdex data, card detail
with current prices, price trend history, and a watchlist for cards the admin
wants to track for buying opportunities.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from merlins_collection.dependencies import get_repo
from merlins_collection.models.inventory import new_ulid
from merlins_collection.services.dynamodb import InventoryRepository

router = APIRouter(prefix="/market", tags=["admin-market"])

# Watchlist lives at /admin/watchlist (not /admin/market/watchlist per RFC)
watchlist_router = APIRouter(prefix="/watchlist", tags=["admin-watchlist"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class MarketSearchResult(BaseModel):
    items: list[dict[str, Any]]
    total: int


class PriceTrendResponse(BaseModel):
    card_id: str
    points: list[dict[str, Any]]


class WatchlistResponse(BaseModel):
    entries: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Catalog Search
# ---------------------------------------------------------------------------

@router.get("/search", response_model=MarketSearchResult)
def market_search(
    name: str | None = Query(None, max_length=200),
    set_id: str | None = Query(None),
    repo: InventoryRepository = Depends(get_repo),
) -> MarketSearchResult:
    """Search the synced catalog for cards by name and/or set.

    This searches the LOCAL DynamoDB catalog (already synced from TCGdex),
    not the live TCGdex API. For the admin to see a card here, the catalog
    sync must have already pulled it.
    """
    if set_id is not None:
        # Use the set GSI for efficient lookup
        cards = repo.list_cards_by_set(set_id)
    else:
        # Full catalog scan — filtered by name
        cards = _scan_catalog(repo)

    # Apply name filter
    if name is not None:
        name_lower = name.lower()
        cards = [c for c in cards if name_lower in c.name.lower()]

    # Serialize
    serialized = [c.model_dump(mode="json") for c in cards]

    return MarketSearchResult(items=serialized, total=len(serialized))


# ---------------------------------------------------------------------------
# Card Detail
# ---------------------------------------------------------------------------

@router.get("/card/{card_id}")
def market_card_detail(
    card_id: str,
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Get full detail for a catalog card including current prices."""
    card = repo.get_catalog_card(card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Card not found in catalog")
    return card.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Price Trend
# ---------------------------------------------------------------------------

@router.get("/card/{card_id}/trend", response_model=PriceTrendResponse)
def market_price_trend(
    card_id: str,
    finish: str | None = Query(None),
    days: int = Query(30, ge=1, le=365),
    repo: InventoryRepository = Depends(get_repo),
) -> PriceTrendResponse:
    """Get price history for a card, optionally filtered by finish.

    Returns price points within the last N days (default 30).
    """
    card = repo.get_catalog_card(card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Card not found in catalog")

    end = date.today()
    start = end - timedelta(days=days)

    points = repo.get_price_history(card_id, finish=finish, start=start, end=end)
    serialized = [p.model_dump(mode="json") for p in points]

    return PriceTrendResponse(card_id=card_id, points=serialized)


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------

class WatchlistAddRequest(BaseModel):
    card_id: str
    name: str
    set_name: str
    target_buy_price: Decimal | None = None
    notes: str | None = None


@watchlist_router.post("", status_code=201)
def add_to_watchlist(
    body: WatchlistAddRequest,
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Add a card to the admin watchlist."""
    # Route is under /admin/market but we mount the watchlist here for simplicity.
    # Use a dedicated prefix at the admin level instead.
    entry_id = new_ulid()
    entry = {
        "entry_id": entry_id,
        "card_id": body.card_id,
        "name": body.name,
        "set_name": body.set_name,
        "target_buy_price": str(body.target_buy_price) if body.target_buy_price else None,
        "notes": body.notes,
        "added_at": datetime.now(tz=timezone.utc).isoformat(),
    }
    repo.put_watchlist_entry(entry)
    return entry


@watchlist_router.get("", response_model=WatchlistResponse)
def list_watchlist(
    repo: InventoryRepository = Depends(get_repo),
) -> WatchlistResponse:
    """List all watchlist entries."""
    entries = repo.list_watchlist_entries()
    return WatchlistResponse(entries=entries)


@watchlist_router.delete("/{entry_id}")
def delete_watchlist_entry(
    entry_id: str,
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, str]:
    """Remove a card from the watchlist."""
    existing = repo.get_watchlist_entry(entry_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Watchlist entry not found")
    repo.delete_watchlist_entry(entry_id)
    return {"status": "deleted", "entry_id": entry_id}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _scan_catalog(repo: InventoryRepository):
    """Scan all catalog cards. Uses the list_all_catalog_cards method if available,
    otherwise falls back to listing known sets."""
    return repo.list_all_catalog_cards()
