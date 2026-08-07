"""``/admin/shows``, ``/admin/analytics/`` and ``/admin/transactions`` (A4, spec §8/§9).

Show CRUD (RFC 0008 T7) plus pre-computed analytics snapshots for completed
shows and the per-date dashboard feeds: the list of dates that actually have
activity, one day's metrics, and the raw transaction archive.

Shows are archived, never deleted — see ``Show.archived`` and the CRUD section
below.

Every route lives in this module (rather than a new router) so
``routers/admin/__init__.py`` stays untouched; the analytics router is included
with no prefix under ``/admin``, so ``/shows`` and ``/transactions`` resolve to
``/admin/shows`` and ``/admin/transactions``.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ValidationError

from merlins_collection.dependencies import get_repo
from merlins_collection.models.business import (
    Show,
    ShowAnalyticsSnapshot,
    Transaction,
    TransactionType,
)
from merlins_collection.services.dynamodb import InventoryRepository

router = APIRouter(tags=["admin-analytics"])

# Default lookback for the range-defaulted feeds (~6 months).
_DEFAULT_LOOKBACK_DAYS = 183

# Hard cap on the transaction archive page so one query can never drag the
# whole ledger into a JSON response.
_ARCHIVE_LIMIT = 500


# ---------------------------------------------------------------------------
# Shared metric helpers (used by BOTH the daily dashboard and per-show snapshots)
# ---------------------------------------------------------------------------

def is_trade_cash_leg(txn: Transaction) -> bool:
    """True for the *cash* component of a trade, which must never hit totals.

    ``trades.py`` confirm writes the cash side of a trade as an ordinary
    transaction whose ``item_id`` is the trade id itself (there is no inventory
    item behind a pile of cash), alongside one transaction per card leg valued
    at its ``agreed_value``. Counting both double-counts the trade.

    Worked example — trade OUT a $25 card, receive a $20 card + $5 cash:
        SALE     item_id=card-out  amount=25  trade_id=tr-1   <- card leg, counts
        PURCHASE item_id=card-in   amount=20  trade_id=tr-1   <- card leg, counts
        SALE     item_id=tr-1      amount=5   trade_id=tr-1   <- cash leg, SKIPPED
    Correct result: total_sold=25, total_bought=20 — NOT total_sold=30.
    """
    return txn.trade_id is not None and txn.item_id == txn.trade_id


def summarize_transactions(txns: list[Transaction]) -> dict[str, Any]:
    """Totals/counts for a set of transactions, with trade cash legs excluded.

    Card legs (priced at ``agreed_value``) stay in, per spec §9: totals include
    trade valuations.
    """
    total_sold = Decimal("0")
    total_bought = Decimal("0")
    items_sold_count = 0
    items_bought_count = 0
    trade_ids: set[str] = set()

    for txn in txns:
        if txn.trade_id:
            trade_ids.add(txn.trade_id)
        if is_trade_cash_leg(txn):
            continue
        if txn.type == TransactionType.SALE:
            total_sold += txn.amount
            items_sold_count += 1
        elif txn.type == TransactionType.PURCHASE:
            total_bought += txn.amount
            items_bought_count += 1

    return {
        "total_sold": total_sold,
        "total_bought": total_bought,
        "net_sales": total_sold - total_bought,
        "items_sold_count": items_sold_count,
        "items_bought_count": items_bought_count,
        "trades_count": len(trade_ids),
    }


def starting_inventory(
    repo: InventoryRepository, day: date
) -> tuple[set[str], Decimal]:
    """The inventory on hand at the START of ``day``: ``(item_ids, total_value)``.

    An item counts when it was acquired *strictly before* ``day`` (so same-day
    acquisitions — flips bought and sold at the same show — are excluded, per
    spec §8 "Inventory Snapshot") AND it was still unsold at that moment: either
    it is not sold today, or it is sold but its SALE transaction is dated on or
    after ``day``.

    Item value = ``current_market_value`` when set, else ``cost_basis``.
    """
    horizon = max(day, date.today())
    sold_on_or_after = {
        t.item_id
        for t in repo.list_transactions(day, horizon)
        if t.type == TransactionType.SALE
    }

    ids: set[str] = set()
    total = Decimal("0")
    for item in repo.list_inventory():
        if item.acquired_at >= day:
            continue
        if str(item.status) == "sold" and item.item_id not in sold_on_or_after:
            continue
        ids.add(item.item_id)
        value = item.current_market_value
        if value is None:
            value = item.cost_basis
        total += value
    return ids, total


def sell_through_rate(
    sale_txns_on_day: list[Transaction], starting_ids: set[str]
) -> Decimal | None:
    """Fraction of the starting inventory that sold on the day. ``None`` when
    there was no starting inventory to sell through."""
    if not starting_ids:
        return None
    sold = len({t.item_id for t in sale_txns_on_day if t.item_id in starting_ids})
    rate = Decimal(sold) / Decimal(len(starting_ids))
    # Cap the repeating-decimal tail, then drop trailing zeros so an exact half
    # reads "0.5" rather than "0.5000".
    return rate.quantize(Decimal("0.0001")).normalize()


def _default_range(start: date | None, end: date | None) -> tuple[date, date]:
    end = end or date.today()
    start = start or (end - timedelta(days=_DEFAULT_LOOKBACK_DAYS))
    return start, end


# ---------------------------------------------------------------------------
# Show CRUD (T7). "Delete" is an archive flag — see ``Show.archived``.
#
# Only THIS listing hides archived shows. ``repo.list_shows`` and
# ``repo.get_show`` stay archive-agnostic on purpose: an archived show is
# hidden, not gone, so its stored analytics snapshot must still resolve and
# ``/shows/{id}/analytics`` must not start 404ing the moment it is archived.
# ---------------------------------------------------------------------------

@router.get("/shows")
def list_shows(
    include_archived: bool = Query(False),
    repo: InventoryRepository = Depends(get_repo),
) -> list[dict[str, Any]]:
    """Every show, most recent first. Archived shows are excluded by default."""
    shows = repo.list_shows()
    if not include_archived:
        shows = [s for s in shows if not s.archived]
    shows.sort(key=lambda s: s.date, reverse=True)
    return [s.model_dump(mode="json") for s in shows]


@router.post("/shows", status_code=201)
def create_show(
    body: dict[str, Any],
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Create a show. The id is the server's to mint, never the client's."""
    body = {k: v for k, v in body.items() if k != "show_id"}
    try:
        show = Show.model_validate(body)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    repo.put_show(show)
    return show.model_dump(mode="json")


def _save_show(
    repo: InventoryRepository, existing: Show, changes: dict[str, Any]
) -> dict[str, Any]:
    """Merge ``changes`` onto ``existing``, re-validate, store, and serialize.

    Shared by the update and the two archive transitions so all three go through
    one validation path and one write.
    """
    merged = existing.model_dump(mode="python")
    merged.update(changes)
    merged["show_id"] = existing.show_id  # never reassignable
    try:
        updated = Show.model_validate(merged)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    repo.put_show(updated)
    return updated.model_dump(mode="json")


def _require_show(repo: InventoryRepository, show_id: str) -> Show:
    show = repo.get_show(show_id)
    if show is None:
        raise HTTPException(status_code=404, detail="Show not found")
    return show


@router.put("/shows/{show_id}")
def update_show(
    show_id: str,
    body: dict[str, Any],
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Partial update — only the fields present in the body change."""
    return _save_show(repo, _require_show(repo, show_id), body)


@router.post("/shows/{show_id}/archive")
def archive_show(
    show_id: str,
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Hide a show from the default listing. Idempotent, and non-destructive:
    there is deliberately no in-use guard, because nothing is being destroyed."""
    return _save_show(repo, _require_show(repo, show_id), {"archived": True})


@router.post("/shows/{show_id}/unarchive")
def unarchive_show(
    show_id: str,
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Restore an archived show. Archiving that cannot be undone is just a
    slower delete, which is the thing this feature exists to avoid."""
    return _save_show(repo, _require_show(repo, show_id), {"archived": False})


# ---------------------------------------------------------------------------
# Per-show analytics
# ---------------------------------------------------------------------------

@router.post("/shows/{show_id}/analytics/generate")
def generate_show_analytics(
    show_id: str,
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Compute and store an analytics snapshot for a show."""
    show = repo.get_show(show_id)
    if show is None:
        raise HTTPException(status_code=404, detail="Show not found")

    txns = repo.list_transactions_for_show(show_id)
    totals = summarize_transactions(txns)

    starting_ids, starting_value = starting_inventory(repo, show.date)
    inventory_value_at_start = show.inventory_value_at_start
    if inventory_value_at_start is None:
        inventory_value_at_start = starting_value

    sales_on_show_date = [
        t for t in txns
        if t.type == TransactionType.SALE
        and t.date == show.date
        and not is_trade_cash_leg(t)
    ]

    snapshot = ShowAnalyticsSnapshot(
        show_id=show_id,
        date=show.date,
        total_sold=totals["total_sold"],
        total_bought=totals["total_bought"],
        net_sales=totals["net_sales"],
        inventory_value_at_start=inventory_value_at_start,
        sell_through_rate=sell_through_rate(sales_on_show_date, starting_ids),
        items_sold_count=totals["items_sold_count"],
        items_bought_count=totals["items_bought_count"],
        trades_count=totals["trades_count"],
        cash_at_start=show.cash_at_start,
        snapshot_generated_at=datetime.now(tz=timezone.utc),
    )

    repo.put_show_analytics(snapshot)
    return snapshot.model_dump(mode="json")


@router.get("/shows/{show_id}/analytics")
def get_show_analytics(
    show_id: str,
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Retrieve the stored analytics snapshot for a show."""
    snapshot = repo.get_show_analytics(show_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Analytics not found for this show")
    return snapshot.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Cross-show analytics
# ---------------------------------------------------------------------------

@router.get("/analytics/by-date")
def list_analytics_by_date(
    start: date = Query(...),
    end: date = Query(...),
    repo: InventoryRepository = Depends(get_repo),
) -> list[dict[str, Any]]:
    """List all show analytics snapshots within a date range."""
    shows = repo.list_shows()
    # Filter shows by date range
    relevant_shows = [s for s in shows if start <= s.date <= end]

    results = []
    for show in relevant_shows:
        snapshot = repo.get_show_analytics(show.show_id)
        if snapshot is not None:
            results.append(snapshot.model_dump(mode="json"))

    return results


@router.get("/analytics/dates")
def list_analytics_dates(
    start: date | None = Query(None),
    end: date | None = Query(None),
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, list[str]]:
    """Distinct dates that have ledger activity, most recent first.

    Drives the dashboard's date picker so it only offers days that have
    something to show. Defaults to the last six months.
    """
    start, end = _default_range(start, end)
    if start > end:
        raise HTTPException(status_code=422, detail="start must be <= end")
    dates = {t.date for t in repo.list_transactions(start, end)}
    return {"dates": [d.isoformat() for d in sorted(dates, reverse=True)]}


@router.get("/analytics/daily")
def daily_analytics(
    date_: date = Query(..., alias="date"),
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """One day's dashboard metrics.

    Decimals are serialized as strings; ``sell_through_rate`` is a 0–1 string
    or ``null`` when there was no inventory on hand at the start of the day.
    """
    txns = repo.list_transactions(date_, date_)
    totals = summarize_transactions(txns)

    starting_ids, starting_value = starting_inventory(repo, date_)
    sales_today = [
        t for t in txns
        if t.type == TransactionType.SALE and not is_trade_cash_leg(t)
    ]
    rate = sell_through_rate(sales_today, starting_ids)

    return {
        "date": date_.isoformat(),
        "total_sold": str(totals["total_sold"]),
        "total_bought": str(totals["total_bought"]),
        "net_sales": str(totals["net_sales"]),
        "items_sold_count": totals["items_sold_count"],
        "items_bought_count": totals["items_bought_count"],
        "trades_count": totals["trades_count"],
        "inventory_value_at_start": str(starting_value),
        "sell_through_rate": None if rate is None else str(rate),
    }


# ---------------------------------------------------------------------------
# Transaction archive
# ---------------------------------------------------------------------------

@router.get("/transactions")
def list_transactions_archive(
    start: date | None = Query(None),
    end: date | None = Query(None),
    type: TransactionType | None = Query(None),
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Raw ledger rows in a date range, most recent first.

    Unlike the dashboard metrics this is an *archive*: nothing is filtered out,
    trade cash legs included, because the point is to see what was actually
    written. ``total`` is the full match count; ``items`` is capped at 500.
    """
    start, end = _default_range(start, end)
    if start > end:
        raise HTTPException(status_code=422, detail="start must be <= end")

    txns = repo.list_transactions(start, end)
    if type is not None:
        txns = [t for t in txns if t.type == type]
    txns.sort(key=lambda t: (t.date, t.txn_id), reverse=True)

    return {
        "items": [t.model_dump(mode="json") for t in txns[:_ARCHIVE_LIMIT]],
        "total": len(txns),
    }
