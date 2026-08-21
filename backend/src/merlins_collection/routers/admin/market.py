"""``/admin/market`` — Market lookup and watchlist management.

Provides catalog search against the locally-synced TCGdex data, card detail
with current prices, price trend history, and a watchlist for cards the admin
wants to track for buying opportunities.
"""

from __future__ import annotations

import logging
import statistics
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel

from merlins_collection.dependencies import get_repo
from merlins_collection.models.inventory import market_price_and_finish, new_ulid
from merlins_collection.services import catalog_cache
from merlins_collection.services.card_text import (
    admin_item_name,
    normalize_number,
    number_keys,
)
from merlins_collection.services.catalog_sync import (
    as_utc,
    build_pricing_provider,
    refresh_graded_prices,
    refresh_held_prices,
    refresh_inventory_market_values,
    sync_new_sets,
)
from merlins_collection.services.dynamodb import InventoryRepository
from merlins_collection.services.tcgdex import TcgdexClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/market", tags=["admin-market"])

# Sync-run status, kept in a module-level dict rather than a datastore. This is
# a single-worker assumption: with more than one API process/worker the status
# would only reflect whichever process last ran a sync, and a 409 from one
# worker would not block a concurrent POST landing on another. Fine for the
# current single-instance deployment; revisit if the admin API ever scales out.
_SYNC_STATUS: dict[str, Any] = {
    "state": "idle",
    "started_at": None,
    "finished_at": None,
    "priced_cards": None,
    # Slabs priced by the graded provider in this run (RFC 0009 T7). Reported
    # separately from `priced_cards` because they are different vendors on
    # different budgets, and "0 slabs" is a fact worth being able to see.
    "priced_slabs": None,
    "updated_items": None,
    "error": None,
}

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
    number: str | None = Query(None),
    repo: InventoryRepository = Depends(get_repo),
) -> MarketSearchResult:
    """Search the synced catalog for cards by name, set, and/or number.

    This searches the LOCAL DynamoDB catalog (already synced from TCGdex),
    not the live TCGdex API. For the admin to see a card here, the catalog
    sync must have already pulled it.
    """
    started = time.perf_counter()

    if set_id is not None:
        # Use the set GSI for efficient lookup
        cards = repo.list_cards_by_set(set_id)
    else:
        # Full catalog read — cached, then filtered by name in Python. The
        # `set_id` branch above deliberately does NOT go through the cache:
        # it returns one set's cards, and seeding the full-catalog cache from
        # that partial result would make every later name search miss
        # everything outside that set.
        cards = _scan_catalog(repo)

    # Apply name filter
    if name is not None:
        name_lower = name.lower()
        cards = [c for c in cards if name_lower in c.name.lower()]

    # Apply number filter. Both sides normalized, exactly as `_match_card` does
    # -- an Excel float artifact ("181.0"), a slash form ("182/167") and a bare
    # "182" all have to find the same card. Hand-typed at a buy table, all
    # three get typed.
    if number is not None:
        wanted = set(number_keys(normalize_number(number)))
        cards = [c for c in cards if set(number_keys(normalize_number(c.number))) & wanted]

    total = len(cards)
    # Cap the response to keep the payload bounded — the catalog scan behind
    # this endpoint is unindexed by name/number, so `total` still reflects the
    # full match count even once `items` is capped.
    serialized = [_with_display_price(c) for c in cards[:50]]

    # Timed and logged so the next "search looks broken" report can be read off
    # the API logs instead of costing another workstation investigation (RFC
    # 0008 T9 -- the original diagnosis needed one). `%r` on the operator-typed
    # values: a newline in a query must not be able to forge a second log line.
    logger.info(
        "market search name=%r set_id=%r number=%r -> %d matches in %.0f ms",
        name, set_id, number, total, (time.perf_counter() - started) * 1000,
    )

    return MarketSearchResult(items=serialized, total=total)


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
# Purchase Confidence
# ---------------------------------------------------------------------------

@router.get("/card/{card_id}/confidence")
def market_card_confidence(
    card_id: str,
    days: int = Query(90, ge=1, le=365),
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Rate how much a card's recent price history supports a buying decision.

    Reuses the same finish-unfiltered point fetch the trend endpoint uses
    (``repo.get_price_history``), just over the confidence window instead of
    the trend window.
    """
    card = repo.get_catalog_card(card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Card not found in catalog")

    end = date.today()
    start = end - timedelta(days=days)
    # Fetched WITHOUT a repo-side `start`/`end` (unlike the trend endpoint's
    # explicit-finish call): `get_price_history`'s range query keys on
    # `PRICE#RAW#<finish>#<date>`, and with no finish segment the date bound
    # compares against the finish text itself, silently matching nothing. The
    # trend endpoint sidesteps this because its `finish` query param is part
    # of its own contract; confidence deliberately spans all finishes, so the
    # range is applied here in Python instead.
    points = repo.get_price_history(card_id)
    points = [p for p in points if start <= p.date <= end]
    prices = [float(p.market) for p in points if p.market is not None]
    n = len(prices)

    if n >= 2:
        volatility = statistics.stdev(prices) / statistics.mean(prices) * 100
    else:
        volatility = 0.0

    if prices and prices[0] != 0:
        trend = (prices[-1] - prices[0]) / prices[0] * 100
    else:
        trend = 0.0

    if n >= 8 and volatility <= 15:
        level = "high"
    elif n >= 4 and volatility <= 30:
        level = "medium"
    else:
        level = "low"

    reason = f"{n} price point{'s' if n != 1 else ''} over {days}d, {volatility:.1f}% volatility"

    return {
        "level": level,
        "points": n,
        "volatility_pct": _pct_str(volatility),
        "trend_pct": _pct_str(trend),
        "reason": reason,
    }


# ---------------------------------------------------------------------------
# Sync Trigger
# ---------------------------------------------------------------------------

def _run_market_sync(repo: InventoryRepository) -> None:
    """Background task body: refresh raw prices, then graded, then denormalize.

    Mirrors ``scripts/daily_sync.py``'s order — the depth pass writes the catalog
    prices ``refresh_inventory_market_values`` then denormalizes — but only the
    refresh steps; the two snapshot steps stay on the scheduled job.

    **The graded step is RFC 0009 T7's fix to a bug open since Round 2**: this
    button was raw-only, so pressing it left every slab exactly as unpriced as
    before. The mismatch was narrower than the old note claimed — the
    denormalization below always copied a slab's STORED value onto the item —
    but until T6 there was no provider to FETCH one from, so a slab nobody had
    hand-priced could never get a number here no matter how often this ran.

    An unconfigured graded provider costs the graded step and nothing else. The
    raw half is what this button has always been for, and taking it down over a
    key that only slabs need would be a strictly worse trade.
    """
    try:
        with TcgdexClient() as client:
            price_summary = refresh_held_prices(repo, client, date.today())

        provider = build_pricing_provider()
        if provider is None:
            logger.warning("market sync: graded pricing skipped, no provider "
                           "is configured")
            graded_summary = {}
        else:
            graded_summary = refresh_graded_prices(repo, provider)

        updated_items = refresh_inventory_market_values(repo)
        _SYNC_STATUS.update({
            "state": "completed",
            "finished_at": datetime.now(tz=timezone.utc).isoformat(),
            "priced_cards": price_summary.get("cards_updated", 0),
            "priced_slabs": graded_summary.get("graded_priced", 0),
            "updated_items": updated_items,
            "error": None,
        })
    except Exception as exc:  # noqa: BLE001 - report the failure, don't crash the worker
        _SYNC_STATUS.update({
            "state": "failed",
            "finished_at": datetime.now(tz=timezone.utc).isoformat(),
            "error": str(exc),
        })


@router.post("/sync", status_code=202)
def trigger_market_sync(
    background_tasks: BackgroundTasks,
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, str]:
    """Kick off a price sync (TCGdex depth pass + inventory denormalization).

    Runs in the background so the request returns immediately; poll
    ``GET /admin/market/sync/status`` for progress.
    """
    if _SYNC_STATUS["state"] == "running":
        raise HTTPException(status_code=409, detail="A market sync is already running")

    _SYNC_STATUS.update({
        "state": "running",
        "started_at": datetime.now(tz=timezone.utc).isoformat(),
        "finished_at": None,
        "priced_cards": None,
        "priced_slabs": None,
        "updated_items": None,
        "error": None,
    })
    background_tasks.add_task(_run_market_sync, repo)
    return {"state": "started"}


@router.get("/sync/status")
def market_sync_status() -> dict[str, Any]:
    """Return the current (or most recent) sync run's status."""
    return _SYNC_STATUS


# ---------------------------------------------------------------------------
# Catalog Sync Trigger (Task 2.8) — incremental "check for new sets"
# ---------------------------------------------------------------------------

# A SEPARATE module-level status dict from `_SYNC_STATUS` above, by design: the
# price sync (depth pass, held cards only) and the catalog sync (breadth,
# newly released sets only) are different jobs that must be independently
# runnable and independently reportable. A single shared dict would make one
# job's "running" block the other's trigger, and one job's completion would
# clobber the other's last-run report.
_CATALOG_SYNC_STATUS: dict[str, Any] = {
    "state": "idle",
    "started_at": None,
    "finished_at": None,
    "sets_checked": None,
    "new_sets": None,
    "cards_added": None,
    "error": None,
}


def _run_catalog_sync(repo: InventoryRepository) -> None:
    """Background task body: check for newly released sets and seed identity rows.

    Wrapped end-to-end in try/except: a crash here must set `state="failed"`
    with an `error`, never leave the status stuck on `"running"` -- that would
    permanently 409 every future trigger of this endpoint.
    """
    try:
        with TcgdexClient() as client:
            summary = sync_new_sets(repo, client)
        _CATALOG_SYNC_STATUS.update({
            "state": "completed",
            "finished_at": datetime.now(tz=timezone.utc).isoformat(),
            "sets_checked": summary.get("sets_checked", 0),
            "new_sets": summary.get("new_sets", []),
            "cards_added": summary.get("cards_added", 0),
            "error": None,
        })
    except Exception as exc:  # noqa: BLE001 - report the failure, don't crash the worker
        _CATALOG_SYNC_STATUS.update({
            "state": "failed",
            "finished_at": datetime.now(tz=timezone.utc).isoformat(),
            "error": str(exc),
        })


@router.post("/catalog-sync", status_code=202)
def trigger_catalog_sync(
    background_tasks: BackgroundTasks,
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, str]:
    """Kick off an incremental catalog sync for newly released sets.

    Runs in the background so the request returns immediately; poll
    ``GET /admin/market/catalog-sync/status`` for progress. This is the
    button-driven counterpart to the CLI-only full-catalog bootstrap
    (``scripts/seed_catalog.py``): it only touches sets we hold zero cards
    for, so it carries none of the bootstrap's dry-run-by-default rails.
    """
    if _CATALOG_SYNC_STATUS["state"] == "running":
        raise HTTPException(status_code=409, detail="A catalog sync is already running")

    _CATALOG_SYNC_STATUS.update({
        "state": "running",
        "started_at": datetime.now(tz=timezone.utc).isoformat(),
        "finished_at": None,
        "sets_checked": None,
        "new_sets": None,
        "cards_added": None,
        "error": None,
    })
    background_tasks.add_task(_run_catalog_sync, repo)
    return {"state": "started"}


@router.get("/catalog-sync/status")
def catalog_sync_status() -> dict[str, Any]:
    """Return the current (or most recent) catalog sync run's status."""
    return _CATALOG_SYNC_STATUS


# ---------------------------------------------------------------------------
# Coverage Report
# ---------------------------------------------------------------------------

# The weekly cycle's deadline, expressed as a number that can be checked (RFC
# 0010 T17). The cycle re-prices every catalog card within ~6 nights, so a
# `full` row that has gone 8 days without a write means the cycle missed it —
# the healthy value for `catalog_cards_stale` is 0, and any other value means
# the promise is not being kept. 8 rather than 7 so a single lost night, which
# the design absorbs on purpose, does not read as a breach.
_CATALOG_CYCLE_STALE_DAYS = 8


@router.get("/coverage")
def market_coverage(repo: InventoryRepository = Depends(get_repo)) -> dict[str, Any]:
    """Report how much of inventory and the catalog actually carry a price.

    Makes the pricing gap visible: the pipeline can be fully wired and still
    leave every item unpriced if it has never run, or if items don't resolve
    to a catalog card. ``unmatched_sample`` is capped at 50 to keep the
    payload bounded, and it samples ``items_unpriced`` — a hand-valued card is
    not in it, because there is nothing left for anyone to do about it.

    ``catalog_cards_brief`` and ``catalog_cards_stale`` are DIFFERENT facts and
    are deliberately not summed: a ``brief`` row has never had a price fetched
    at all (the weekly cycle has not reached it yet, and counts down to 0 over
    the first ~6 nights), while a stale ``full`` row was priced once and the
    cycle has since missed its slot. Collapsing them would throw away the only
    signal that says whether waiting helps — the same honesty requirement
    ``CatalogCard.detail`` exists to preserve.
    """
    items = repo.list_inventory()
    total_items = len(items)
    items_with_card_id = sum(1 for i in items if getattr(i, "card_id", None))
    items_with_market_value = sum(
        1 for i in items if i.current_market_value is not None
    )
    # RFC 0010 T16 — three categories, and they are a PARTITION of the table:
    # market-priced + hand-valued + unpriced == total_items, by construction
    # rather than by three independent sums that happen to agree.
    #
    # A hand-valued item is one that carries a figure with no catalog link, which
    # is exactly the set ``refresh_inventory_market_values`` skips. It is not a
    # coverage gap — nothing will ever sync it, so the gap can never be closed —
    # and it is not market coverage either, because no provider stands behind the
    # number. Folding it into either one answers neither question, and a worklist
    # that keeps nagging about finished work stops being read.
    items_hand_valued = sum(
        1 for i in items
        if i.current_market_value is not None and not getattr(i, "card_id", None)
    )
    items_market_priced = items_with_market_value - items_hand_valued
    items_unpriced = total_items - items_with_market_value

    cards = _scan_catalog(repo)
    catalog_cards = len(cards)
    catalog_cards_with_prices = sum(1 for c in cards if c.prices)
    catalog_cards_brief = sum(1 for c in cards if c.detail == "brief")
    stale_before = datetime.now(tz=timezone.utc) - timedelta(
        days=_CATALOG_CYCLE_STALE_DAYS
    )
    catalog_cards_stale = sum(
        1 for c in cards
        if c.detail == "full" and as_utc(c.last_synced_at) < stale_before
    )

    if total_items:
        pct = (Decimal(items_with_market_value) / Decimal(total_items) * 100).quantize(
            Decimal("0.1")
        )
        item_coverage_pct = str(pct)
    else:
        item_coverage_pct = "0"

    unmatched_sample = [
        {
            "item_id": i.item_id,
            "name": admin_item_name(i, "?"),
        }
        for i in items
        if i.current_market_value is None
    ][:50]

    return {
        "total_items": total_items,
        "items_with_card_id": items_with_card_id,
        "items_with_market_value": items_with_market_value,
        "items_market_priced": items_market_priced,
        "items_hand_valued": items_hand_valued,
        "items_unpriced": items_unpriced,
        "catalog_cards": catalog_cards,
        "catalog_cards_with_prices": catalog_cards_with_prices,
        "catalog_cards_brief": catalog_cards_brief,
        "catalog_cards_stale": catalog_cards_stale,
        "catalog_stale_threshold_days": _CATALOG_CYCLE_STALE_DAYS,
        "item_coverage_pct": item_coverage_pct,
        "unmatched_sample": unmatched_sample,
    }


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

def _with_display_price(card) -> dict[str, Any]:
    """One serialized catalog card, plus the picker's price column.

    A card picker must show name, image AND price (CLAUDE.md). ``prices`` is a
    dict keyed by finish, so "the price of this card" needs a *choice* — and
    the frontend cannot make it: a catalog result has no item, therefore no
    finish, and ``_market_price`` returns ``None`` without one. Passing
    ``"normal"`` as the default buys the entire fallback walk for free.

    **Do not re-implement that walk in a caller** (in TypeScript or anywhere
    else); ``models.inventory._market_price``'s docstring names the divergence
    that produced — 174 of 213 live items silently unpriced.

    ``display_price`` is a string, matching how pydantic already serializes
    every other ``Decimal`` in this payload, and ``None`` when the card has no
    band at all. **Never ``0``**: ``FinishPrice`` bands are written only when a
    provider actually published a figure, so absent means absent.

    Returns a fresh dict. The cards themselves come from the shared catalog
    cache and must never be mutated (``services/catalog_cache``).
    """
    price, finish = market_price_and_finish(card, "normal")
    data = card.model_dump(mode="json")
    data["display_price"] = str(price) if price is not None else None
    data["display_finish"] = finish
    return data


def _scan_catalog(repo: InventoryRepository):
    """Every catalog card, served from the process cache when it is warm.

    The underlying scan reads the whole table (~11s against the live one), so
    it must not run per request. See ``services/catalog_cache`` for what keeps
    the cached copy honest.
    """
    return catalog_cache.get_catalog_cards(repo.list_all_catalog_cards)


def _pct_str(value: float) -> str:
    """Format a float percentage as a string quantized to one decimal place."""
    return str(Decimal(str(value)).quantize(Decimal("0.1")))
