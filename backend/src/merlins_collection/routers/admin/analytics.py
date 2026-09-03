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

import logging
from datetime import date, datetime, timedelta, timezone
from datetime import date as _date_type
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, ValidationError, field_validator

from merlins_collection.dependencies import get_repo, require_admin
from merlins_collection.models.auth import AuthenticatedUser
from merlins_collection.models.business import (
    Show,
    ShowAnalyticsSnapshot,
    Transaction,
    TransactionEdit,
    TransactionFieldChange,
    TransactionType,
)
from merlins_collection.services.dynamodb import (
    InventoryRepository,
    LedgerReversalConflictError,
    TransactionEditConflictError,
)
from merlins_collection.services.ledger import countable
from merlins_collection.services.shows_sort import SORT_FIELDS as SHOW_SORT_FIELDS
from merlins_collection.services.shows_sort import parse_sort as parse_show_sort
from merlins_collection.services.shows_sort import sort_shows
from merlins_collection.services.transactions_sort import (
    SORT_FIELDS as TXN_SORT_FIELDS,
)
from merlins_collection.services.transactions_sort import (
    parse_sort as parse_txn_sort,
)
from merlins_collection.services.transactions_sort import sort_transactions

router = APIRouter(tags=["admin-analytics"])
logger = logging.getLogger(__name__)

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

    **Voided rows count toward nothing** — filtered through the one predicate in
    ``services.ledger``, never an inlined ``voided_at is None``.
    """
    txns = countable(txns)
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
    # A voided sale did not sell anything, so an item whose only sale was voided
    # was NOT on hand at the start of the day — it was already gone by other
    # means, or its `sold` status is about to be reversed.
    sold_on_or_after = {
        t.item_id
        for t in countable(repo.list_transactions(day, horizon))
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
    there was no starting inventory to sell through.

    Filters through ``services.ledger`` itself rather than trusting its callers
    to have done it — this is an aggregate, and the invariant is that every
    aggregate applies the predicate.
    """
    if not starting_ids:
        return None
    sold = len({t.item_id for t in countable(sale_txns_on_day)
                if t.item_id in starting_ids})
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
    sort: str | None = Query(None),
    repo: InventoryRepository = Depends(get_repo),
) -> list[dict[str, Any]]:
    """Every show, most recent first. Archived shows are excluded by default.

    ``sort`` (RFC 0013 T4b) overrides the default date-descending order via
    ``services.shows_sort`` — same ``{field}_{direction}`` convention and same
    422-on-unknown-field rule as every other admin list endpoint; a caller
    that sends nothing keeps today's date-desc behavior unchanged.
    """
    if sort is not None and parse_show_sort(sort) is None:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unknown sort {sort!r}. Expected {{field}}_asc or {{field}}_desc, "
                f"where field is one of: {', '.join(sorted(SHOW_SORT_FIELDS))}."
            ),
        )

    shows = repo.list_shows()
    if not include_archived:
        shows = [s for s in shows if not s.archived]
    if sort is None:
        shows.sort(key=lambda s: s.date, reverse=True)
    else:
        shows = sort_shows(shows, sort)
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
    there is deliberately no in-use guard, because nothing is being destroyed.

    RFC 0013: archiving is also the moment a show's numbers stop changing, so
    it's when the analytics snapshot gets generated — without this, every show
    read 0 on the Shows tab until a human pressed "Generate" by hand. The
    snapshot is a CACHE, not the durable state change: a generation failure
    must never turn a successful archive into a failed request, so it's caught
    and logged rather than allowed to propagate. The manual "Generate" button
    (below) stays as the recovery path.
    """
    result = _save_show(repo, _require_show(repo, show_id), {"archived": True})
    try:
        generate_show_analytics(show_id, repo=repo)
    except Exception:
        logger.exception(
            "Failed to auto-generate analytics for show %s on archive", show_id
        )
    return result


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

    # Voided rows are dropped once, here, so every figure below inherits it.
    txns = countable(repo.list_transactions_for_show(show_id))
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
    # A day whose only sale was voided has no activity to show, so it is not
    # offered as a date — the picker would otherwise lead to an empty dashboard.
    dates = {t.date for t in countable(repo.list_transactions(start, end))}
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
    # Dropped once, here: the dashboard's Today tile reads this endpoint too, so
    # this is also what keeps the landing page and this page agreeing.
    txns = countable(repo.list_transactions(date_, date_))
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
    sort: str | None = Query(None),
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Raw ledger rows in a date range, most recent first.

    Unlike the dashboard metrics this is an *archive*: nothing is filtered out,
    trade cash legs included, because the point is to see what was actually
    written. ``total`` is the full match count; ``items`` is capped at 500.

    **This is the one reader that deliberately does NOT call
    ``services.ledger.is_countable``.** A voided row stays visible here, carrying
    its ``voided_at`` / ``voided_by`` / ``void_reason``, because a void is a
    thing that was written — hiding it would make the correction untraceable and
    would leave the operator no way to restore it.

    ``sort`` (RFC 0013 T4c) overrides the default ``(date, txn_id)``-descending
    order via ``services.transactions_sort`` — same convention and 422-on-unknown
    rule as ``list_shows`` above. The History page's grouped rendering sorts
    GROUP order on top of these rows; this endpoint only ever returns flat rows.
    """
    if sort is not None and parse_txn_sort(sort) is None:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unknown sort {sort!r}. Expected {{field}}_asc or {{field}}_desc, "
                f"where field is one of: {', '.join(sorted(TXN_SORT_FIELDS))}."
            ),
        )

    start, end = _default_range(start, end)
    if start > end:
        raise HTTPException(status_code=422, detail="start must be <= end")

    txns = repo.list_transactions(start, end)
    if type is not None:
        txns = [t for t in txns if t.type == type]
    if sort is None:
        txns.sort(key=lambda t: (t.date, t.txn_id), reverse=True)
    else:
        txns = sort_transactions(txns, sort)

    return {
        "items": [t.model_dump(mode="json") for t in txns[:_ARCHIVE_LIMIT]],
        "total": len(txns),
    }


# ---------------------------------------------------------------------------
# Transaction void / restore (RFC 0010 T11)
#
# A void, never a delete — the owner's choice from three options, matching the
# precedent already in this codebase (a Show "delete" is an archive precisely so
# analytics can never dangle). A deleted sale would leave no trace it existed
# while silently disagreeing with every snapshot already generated.
#
# SCOPE: sales only in the first cut. Voiding a sale returns an item to stock;
# voiding a PURCHASE should arguably remove an item that may since have been
# sold, traded or re-priced, and a void that leaves a phantom item in stock is
# worse than no void. A purchase gets a clear 400 rather than half a feature.
# ---------------------------------------------------------------------------

_PURCHASE_VOID_MESSAGE = (
    "A purchase cannot be voided yet — remove the item from inventory instead"
)


class VoidRequest(BaseModel):
    """The body of a void. ``voided_by`` is deliberately absent: it is stamped
    from the authenticated principal, and an extra key here is IGNORED rather
    than honoured."""

    reason: str = Field(max_length=500)

    @field_validator("reason")
    @classmethod
    def _must_say_something(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            # The reason is the whole point of choosing void over delete.
            raise ValueError("A void needs a reason")
        return stripped


def _actor(user: AuthenticatedUser) -> str:
    """Who to record as having done this.

    ONE stored value, not two: the email when Cognito supplied one (an audit
    line is read by a human), falling back to the username and finally to the
    opaque-but-always-present ``sub`` so the field is never null.
    """
    return user.email or user.username or user.sub


def _require_transaction(repo: InventoryRepository, txn_id: str) -> Transaction:
    txn = repo.get_transaction(txn_id)
    if txn is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return txn


def _mark_snapshots_stale(repo: InventoryRepository, txn: Transaction) -> None:
    """Flag every stored snapshot the reversal just invalidated.

    Snapshots are point-in-time records, so a void leaves them wrong by
    construction. Never silently rewrite one (that would erase what the show
    actually reported at the time) and never silently serve one.

    Both the transaction's own show AND every show held on its date, because a
    sale entered without a ``show_id`` still lands in that show's day.
    """
    show_ids = {txn.show_id} if txn.show_id else set()
    show_ids |= {s.show_id for s in repo.list_shows() if s.date == txn.date}
    for show_id in show_ids:
        snapshot = repo.get_show_analytics(show_id)
        if snapshot is not None and not snapshot.stale:
            repo.put_show_analytics(snapshot.model_copy(update={"stale": True}))


def _void_timeline_event(txn: Transaction, *, restored: bool) -> dict[str, Any]:
    """The one timeline event describing this row's void state.

    ``txn_id`` carries a ``#void`` suffix so the event lands on its own sort key:
    the original sale event is keyed ``TIMELINE#<date>#<txn_id>``, and a void on
    the same day would otherwise OVERWRITE it. The timeline is a history, and
    history includes the mistake.

    Re-put in place on a restore rather than accompanied by a second event, so
    there is exactly one row per voided transaction and it always states the
    CURRENT state — two events would need an ordering the sort key cannot give
    (both fall on the same date, and ``#restore`` sorts *before* ``#void``).
    """
    event: dict[str, Any] = {
        "item_id": txn.item_id,
        "txn_id": f"{txn.txn_id}#void",
        "type": "void_restored" if restored else "voided",
        "date": date.today().isoformat(),
        "amount": str(txn.amount),
        "voided_txn_id": txn.txn_id,
    }
    if restored:
        event["restored_at"] = datetime.now(tz=timezone.utc).isoformat()
    else:
        event["void_reason"] = txn.void_reason
        event["voided_at"] = (
            txn.voided_at.isoformat()
            if isinstance(txn.voided_at, datetime) else str(txn.voided_at)
        )
        event["voided_by"] = txn.voided_by
    return event


def _require_item_status(repo: InventoryRepository, txn: Transaction,
                         expected: str, explanation: str) -> None:
    item = repo.get_inventory_item(txn.item_id)
    if item is None:
        raise HTTPException(
            status_code=409,
            detail=f"Item {txn.item_id} no longer exists — {explanation}",
        )
    if str(item.status) != expected:
        # Fail loudly rather than resurrect a card somebody else now owns.
        raise HTTPException(
            status_code=409,
            detail=(f"Item {txn.item_id} is {item.status}, not {expected} — "
                    f"{explanation}"),
        )


def _guard_voidable(repo: InventoryRepository, txn: Transaction) -> None:
    """Everything that must be true before a sale can be withdrawn."""
    if txn.voided_at is not None:
        raise HTTPException(status_code=409, detail="Transaction is already voided")
    if txn.type != TransactionType.SALE:
        raise HTTPException(status_code=400, detail=_PURCHASE_VOID_MESSAGE)
    _require_item_status(
        repo, txn, "sold",
        "it has moved on since this sale and cannot be returned to stock",
    )


def _guard_restorable(repo: InventoryRepository, txn: Transaction) -> None:
    if txn.voided_at is None:
        raise HTTPException(status_code=409, detail="Transaction is not voided")
    _require_item_status(
        repo, txn, "available",
        "restoring this sale would claim a card that is no longer in stock",
    )


def _apply_reversal(repo: InventoryRepository, rows: list[Transaction], *,
                    restore: bool) -> None:
    """Write the reversal, then its timeline events and snapshot flags.

    The write is one atomic call for the whole list, so a five-card sale cannot
    end up three-fifths voided. The bookkeeping that follows is best-effort by
    nature (a timeline event is not money) and is deliberately AFTER it.
    """
    try:
        repo.reverse_sales(
            rows,
            to_status="sold" if restore else "available",
            from_status="available" if restore else "sold",
            expect_voided=restore,
        )
    except LedgerReversalConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail=("The transaction or its item changed while writing — "
                    "nothing was written"),
        ) from exc

    for row in rows:
        repo.put_timeline_event(row.item_id, _void_timeline_event(row, restored=restore))
        _mark_snapshots_stale(repo, row)


def _void_rows(rows: list[Transaction], *, reason: str,
               actor: str) -> list[Transaction]:
    stamped_at = datetime.now(tz=timezone.utc)
    return [r.model_copy(update={
        "voided_at": stamped_at, "voided_by": actor, "void_reason": reason,
    }) for r in rows]


def _restored_rows(rows: list[Transaction]) -> list[Transaction]:
    return [r.model_copy(update={
        "voided_at": None, "voided_by": None, "void_reason": None,
    }) for r in rows]


def _require_batch(repo: InventoryRepository, batch_id: str) -> list[Transaction]:
    """Every leg of one real transaction, refusing a batch too big to be atomic.

    Chunking a huge batch would reintroduce the partial write the atomic write
    exists to prevent, so an oversized one is refused with an instruction the
    operator can act on rather than quietly split.
    """
    rows = repo.list_transactions_by_batch(batch_id)
    if not rows:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if len(rows) > InventoryRepository.MAX_REVERSAL_LEGS:
        raise HTTPException(
            status_code=422,
            detail=(f"This transaction has {len(rows)} cards, more than the "
                    f"{InventoryRepository.MAX_REVERSAL_LEGS} that can be reversed "
                    "in one atomic write. Void them one at a time."),
        )
    return rows


@router.post("/transactions/{txn_id}/void")
def void_transaction(
    txn_id: str,
    body: VoidRequest,
    repo: InventoryRepository = Depends(get_repo),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    """Withdraw ONE sale leg: stamp the ledger row, return the card to stock.

    The partial correction. For the whole transaction — which is what an
    operator who rang up the wrong customer actually wants — see the batch
    route below.
    """
    txn = _require_transaction(repo, txn_id)
    _guard_voidable(repo, txn)
    [voided] = _void_rows([txn], reason=body.reason, actor=_actor(user))
    _apply_reversal(repo, [voided], restore=False)
    return voided.model_dump(mode="json")


@router.post("/transactions/{txn_id}/restore")
def restore_transaction(
    txn_id: str,
    repo: InventoryRepository = Depends(get_repo),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    """Undo a void: clear the three fields and re-apply the original sale.

    "Archiving that cannot be undone is just a slower delete" is already the
    phrasing ``unarchive_show`` uses, and the same logic applies here.
    """
    txn = _require_transaction(repo, txn_id)
    _guard_restorable(repo, txn)
    [restored] = _restored_rows([txn])
    _apply_reversal(repo, [restored], restore=True)
    return restored.model_dump(mode="json")


# --- the whole transaction, keyed on T10's ``batch_id`` --------------------
#
# A five-card sale is ONE thing the operator did, so undoing it is one thing
# too. ``batch_id`` is the key that says which rows belong to it — deliberately
# reusing T10's field rather than inventing a second grouping key, and
# deliberately NOT a (date, payment_method, type) heuristic, which cannot tell
# two separate cash sales on one show day from a single two-card sale.

@router.post("/transactions/batch/{batch_id}/void")
def void_transaction_batch(
    batch_id: str,
    body: VoidRequest,
    repo: InventoryRepository = Depends(get_repo),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    """Withdraw every leg of one real transaction, atomically.

    Every leg is guarded BEFORE anything is written, and the write itself is one
    transaction — so a batch containing one card that has moved on since voids
    nothing at all, rather than leaving the ledger half-corrected.
    """
    rows = _require_batch(repo, batch_id)
    for row in rows:
        _guard_voidable(repo, row)
    voided = _void_rows(rows, reason=body.reason, actor=_actor(user))
    _apply_reversal(repo, voided, restore=False)
    return {
        "batch_id": batch_id,
        "voided": len(voided),
        "items": [r.model_dump(mode="json") for r in voided],
    }


@router.post("/transactions/batch/{batch_id}/restore")
def restore_transaction_batch(
    batch_id: str,
    repo: InventoryRepository = Depends(get_repo),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    """Undo a whole-transaction void, on the same all-or-nothing terms."""
    rows = _require_batch(repo, batch_id)
    for row in rows:
        _guard_restorable(repo, row)
    restored = _restored_rows(rows)
    _apply_reversal(repo, restored, restore=True)
    return {
        "batch_id": batch_id,
        "restored": len(restored),
        "items": [r.model_dump(mode="json") for r in restored],
    }


# ---------------------------------------------------------------------------
# Transaction edit — a typo correction path, distinct from void (RFC 0024 T3)
#
# A void says "this sale did not happen"; this says "this happened, I typed
# $150 instead of $105". Voiding and re-entering a typo would lose the
# original date, the batch grouping, and the item's timeline continuity, and
# would leave a struck-through phantom in the archive that misrepresents what
# occurred. See CLAUDE.md's "THE LEDGER HAS A CORRECTION PATH" section.
# ---------------------------------------------------------------------------

# Fields a client may never touch. Re-pointing a leg (`item_id`) or its
# `type`/`category` rewrites two items' histories from one edit — the correct
# expression of "this was the wrong card" is a void plus a fresh entry, not an
# edit. `extra="forbid"` turns any of these (or an unknown key) into a 422
# rather than a silent no-op.
_TRADE_LEG_EDIT_MESSAGE = (
    "A trade leg cannot be edited — its incoming cost basis was allocated "
    "across every leg at confirm time, and a single-leg edit would leave that "
    "allocation inconsistent with its own inputs. Void the whole trade "
    "instead (a mistaken trade currently has no correction path)."
)

# These four correspond to genuinely required, non-nullable fields on
# `Transaction` — sending one explicitly as `null` is not "clearing" it (there
# is nothing sensible to clear it TO), so it is rejected rather than silently
# accepted and left to fail `Transaction`'s own validation invisibly (a plain
# `model_copy(update=...)` does not revalidate).
_NON_NULLABLE_EDIT_FIELDS = frozenset({"amount", "date", "payment_method", "fee"})


class TransactionEditRequest(BaseModel):
    """Any subset of these six fields. Anything else is a 422 via
    ``extra="forbid"`` — the same rule ``LocationLabelUpdate`` already
    follows for exactly this reason."""

    model_config = {"extra": "forbid"}

    amount: Decimal | None = None
    # Aliased import: a field literally named ``date`` would otherwise shadow
    # the ``datetime.date`` class its own annotation refers to (Python 3.14's
    # deferred annotation evaluation resolves ``date`` against the class's own
    # namespace, not the module's, once the field exists) — the exact reason
    # ``models/business.py`` already imports ``date as date_type`` for
    # ``Transaction.date``.
    date: _date_type | None = None
    payment_method: str | None = None
    fee: Decimal | None = None
    show_id: str | None = None
    notes: str | None = None


def _edit_repr(value: Any) -> str | None:
    """Render one field's value for `TransactionFieldChange` — a plain string
    so the audit trail survives round-tripping a `date`/`Decimal` through JSON
    without a second serializer to keep in sync with the model's own."""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _edit_timeline_event(txn: Transaction, changes: list[TransactionFieldChange]) -> dict[str, Any]:
    """The one timeline event describing this transaction's most recent edit.

    Keyed ``<txn_id>#edit`` and re-put rather than appended, mirroring
    ``_void_timeline_event`` exactly and for the identical reason: the
    original sale event is keyed ``TIMELINE#<date>#<txn_id>``, so a same-day
    edit — the common case, a typo caught minutes later — would otherwise
    overwrite the sale itself.
    """
    return {
        "item_id": txn.item_id,
        "txn_id": f"{txn.txn_id}#edit",
        "type": "edited",
        "date": date.today().isoformat(),
        "amount": str(txn.amount),
        "edited_txn_id": txn.txn_id,
        "edited_at": (
            txn.edited_at.isoformat()
            if isinstance(txn.edited_at, datetime) else str(txn.edited_at)
        ),
        "edited_by": txn.edited_by,
        "changes": [c.model_dump(mode="json") for c in changes],
    }


@router.patch("/transactions/{txn_id}")
def edit_transaction(
    txn_id: str,
    body: TransactionEditRequest,
    repo: InventoryRepository = Depends(get_repo),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    """Correct a typo in the ledger, with a server-stamped audit trail.

    Refuses: a voided transaction (409 — restore first, editing a row that
    counts toward nothing produces an incoherent audit trail); a trade leg
    (400 — see ``_TRADE_LEG_EDIT_MESSAGE``); an unknown ``txn_id`` (404); a
    disallowed field or an unreadable value (422, via ``extra="forbid"`` and
    each field's own Pydantic type).
    """
    old_txn = _require_transaction(repo, txn_id)
    if old_txn.voided_at is not None:
        raise HTTPException(
            status_code=409,
            detail="Transaction is voided — restore it before editing",
        )
    if old_txn.trade_id is not None:
        raise HTTPException(status_code=400, detail=_TRADE_LEG_EDIT_MESSAGE)

    provided = body.model_dump(exclude_unset=True)
    for field in _NON_NULLABLE_EDIT_FIELDS & provided.keys():
        if provided[field] is None:
            raise HTTPException(
                status_code=422,
                detail=f"'{field}' cannot be cleared — supply a value or omit it",
            )

    field_changes: list[TransactionFieldChange] = []
    update: dict[str, Any] = {}
    for field, new_value in provided.items():
        old_value = getattr(old_txn, field)
        if new_value == old_value:
            continue
        field_changes.append(TransactionFieldChange(
            field=field, old=_edit_repr(old_value), new=_edit_repr(new_value),
        ))
        update[field] = new_value

    if not field_changes:
        # Every provided value already matched what was stored — nothing
        # happened, so no audit entry, no timeline event, and no snapshot
        # is marked stale over a no-op.
        return {
            **old_txn.model_dump(mode="json"),
            "cost_basis_updated": False,
            "cost_basis_skipped_reason": None,
        }

    actor = _actor(user)
    stamped_at = datetime.now(tz=timezone.utc)
    history = [
        *old_txn.edit_history,
        TransactionEdit(at=stamped_at, by=actor, changes=field_changes),
    ][-20:]
    new_txn = old_txn.model_copy(update={
        **update,
        "edited_at": stamped_at,
        "edited_by": actor,
        "edit_history": history,
    })

    # cost_basis follows a corrected PURCHASE amount, guarded on equality with
    # the OLD amount so a hand-correction the admin already made on the item
    # (RFC 0022 made this the COMMON case, not a rare one) is never silently
    # overwritten. Decided BEFORE the write, from a plain read — the atomic
    # write's own ConditionExpression re-checks the same equality only as a
    # concurrency guard against a race in the gap between this read and that
    # write, not as the decision itself.
    cost_basis_item_id: str | None = None
    new_cost_basis: Decimal | None = None
    old_cost_basis_expected: Decimal | None = None
    cost_basis_updated = False
    cost_basis_skipped_reason: str | None = None

    if old_txn.type == TransactionType.PURCHASE and "amount" in update:
        item = repo.get_inventory_item(old_txn.item_id)
        if item is None:
            cost_basis_skipped_reason = "item not found"
        elif item.cost_basis != old_txn.amount:
            cost_basis_skipped_reason = "cost basis was changed manually since"
        else:
            cost_basis_item_id = old_txn.item_id
            new_cost_basis = new_txn.amount
            old_cost_basis_expected = old_txn.amount
            cost_basis_updated = True

    try:
        repo.edit_transaction(
            old_txn=old_txn,
            new_txn=new_txn,
            cost_basis_item_id=cost_basis_item_id,
            new_cost_basis=new_cost_basis,
            old_cost_basis_expected=old_cost_basis_expected,
        )
    except TransactionEditConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail="The transaction or its item changed while writing — nothing was written",
        ) from exc

    repo.put_timeline_event(new_txn.item_id, _edit_timeline_event(new_txn, field_changes))

    # Both the OLD and the NEW show/date are marked stale — if the date moved
    # between shows, both snapshots are now wrong. `_mark_snapshots_stale`
    # already resolves "every show whose date matches", so calling it once per
    # transaction state covers both without duplicating that resolution here.
    _mark_snapshots_stale(repo, old_txn)
    _mark_snapshots_stale(repo, new_txn)

    return {
        **new_txn.model_dump(mode="json"),
        "cost_basis_updated": cost_basis_updated,
        "cost_basis_skipped_reason": cost_basis_skipped_reason,
    }
