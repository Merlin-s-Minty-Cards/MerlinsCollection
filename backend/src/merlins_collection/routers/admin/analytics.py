"""``/admin/shows/{id}/analytics`` and ``/admin/analytics/`` — Show analytics (A4).

Pre-computed analytics snapshots for completed shows: total sold/bought,
net sales, sell-through rate, item counts.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from merlins_collection.dependencies import get_repo
from merlins_collection.models.business import ShowAnalyticsSnapshot, TransactionType
from merlins_collection.services.dynamodb import InventoryRepository

router = APIRouter(tags=["admin-analytics"])


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

    # Get all transactions for this show
    txns = repo.list_transactions_for_show(show_id)

    total_sold = Decimal("0")
    total_bought = Decimal("0")
    items_sold_count = 0
    items_bought_count = 0
    trade_ids = set()

    for txn in txns:
        if txn.type == TransactionType.SALE:
            total_sold += txn.amount
            if txn.trade_id:
                trade_ids.add(txn.trade_id)
            else:
                items_sold_count += 1
        elif txn.type == TransactionType.PURCHASE:
            total_bought += txn.amount
            if txn.trade_id:
                trade_ids.add(txn.trade_id)
            else:
                items_bought_count += 1

    # Items sold/bought via trades counted by unique trade_ids in sale/purchase
    # but for simplicity, count sale txns as items_sold, purchase txns as items_bought
    items_sold_count = sum(1 for t in txns if t.type == TransactionType.SALE)
    items_bought_count = sum(1 for t in txns if t.type == TransactionType.PURCHASE)
    trades_count = len(trade_ids)

    net_sales = total_sold - total_bought

    snapshot = ShowAnalyticsSnapshot(
        show_id=show_id,
        date=show.date,
        total_sold=total_sold,
        total_bought=total_bought,
        net_sales=net_sales,
        inventory_value_at_start=show.inventory_value_at_start,
        items_sold_count=items_sold_count,
        items_bought_count=items_bought_count,
        trades_count=trades_count,
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
