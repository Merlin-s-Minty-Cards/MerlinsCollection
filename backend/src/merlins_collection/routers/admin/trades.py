"""``/admin/trades`` — Trade session lifecycle.

A trade is the most complex transaction: items going out (ours, sold),
items coming in (theirs, purchased), and an optional cash component to
balance. On confirm, outgoing items are marked SOLD, incoming items are
created as new inventory, and transactions are recorded for both sides.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from merlins_collection.dependencies import get_repo
from merlins_collection.models.business import ItemCategory, Transaction, TransactionType
from merlins_collection.models.inventory import (
    InventoryItemAdapter,
    ItemStatus,
    new_ulid,
)
from merlins_collection.services.dynamodb import InventoryRepository, ItemAlreadySoldError
from merlins_collection.services.locations import validate_location

router = APIRouter(prefix="/trades", tags=["admin-trades"])

CENTS = Decimal("0.01")

#: Payment rails we actually accept for the cash side of a trade.
CASH_PAYMENT_METHODS = {"cash", "venmo", "zelle", "card"}


def _money(value: Any) -> Decimal:
    """Coerce an untyped session/leg value to ``Decimal`` (never via ``float``)."""
    return Decimal(str(value or 0))


def _cents(value: Decimal) -> Decimal:
    return value.quantize(CENTS, rounding=ROUND_HALF_UP)


def _validate_payment_method(component: dict[str, Any]) -> None:
    method = component.get("payment_method", "cash")
    if method not in CASH_PAYMENT_METHODS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unsupported payment_method '{method}'. "
                f"Must be one of: {', '.join(sorted(CASH_PAYMENT_METHODS))}."
            ),
        )


def _cash_totals(session: dict[str, Any]) -> tuple[Decimal, Decimal]:
    """Return ``(cash_we_pay, cash_they_pay)`` for a session.

    Reads ``cash_components`` (the multi-asset shape) and falls back to the
    legacy single ``cash`` dict for sessions written before that upgrade. Both
    shapes carry the same keys; only ``"they_pay"`` counts as money coming in,
    every other direction value (including a missing one) is money going out —
    matching how the balance endpoint has always read this field.
    """
    components = session.get("cash_components") or []
    if not components:
        legacy = session.get("cash")
        components = [legacy] if legacy and legacy.get("amount") else []

    we_pay = Decimal("0")
    they_pay = Decimal("0")
    for comp in components:
        amount = _money(comp.get("amount"))
        if comp.get("direction") == "they_pay":
            they_pay += amount
        else:
            we_pay += amount
    return we_pay, they_pay


def _allocate_incoming_basis(
    basis_pool: Decimal, incoming: list[dict[str, Any]]
) -> list[Decimal]:
    """Split ``basis_pool`` across incoming legs pro-rata by ``agreed_value``.

    Allocated by *running cumulative* total rather than by rounding each leg
    independently and dumping the remainder on the last one. Both approaches
    sum to the pool exactly, but this one also guarantees every leg is
    non-negative: each leg is the difference between two non-decreasing
    quantized cumulative totals.

    That guarantee matters. Rounding each leg half-up independently can
    overspend the pool, and the remainder-on-the-last-leg fix-up then goes
    NEGATIVE — e.g. a pool of 0.04 across agreed values [1,1,1,1,1,1,2] lands
    on [0.01 x6, -0.02]. ``cost_basis`` is an unconstrained ``Decimal``, so a
    negative would persist as a negative book cost and read as inflated profit
    on the next sale. Reachable in practice whenever the counterparty's cash
    nearly cancels our outgoing basis across several incoming cards.
    """
    n = len(incoming)
    if n == 0:
        return []

    # Quantize the pool first so the final cumulative step lands on it exactly.
    pool = _cents(basis_pool)

    agreed = [_money(leg.get("agreed_value")) for leg in incoming]
    total = sum(agreed, Decimal("0"))
    # No agreed values to weight by (all zero) — split evenly.
    weights = agreed if total > 0 else [Decimal("1")] * n
    weight_total = total if total > 0 else Decimal(n)

    allocated: list[Decimal] = []
    running = Decimal("0")
    previous_cumulative = Decimal("0")
    for weight in weights:
        running += weight
        cumulative = _cents(pool * running / weight_total)
        allocated.append(cumulative - previous_cumulative)
        previous_cumulative = cumulative
    return allocated


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("", status_code=201)
def create_trade_session(
    body: dict[str, Any],
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Create a new draft trade session."""
    trade_id = new_ulid()
    session = {
        "trade_id": trade_id,
        "status": "draft",
        "mode": body.get("mode", "customer"),
        "show_id": body.get("show_id"),
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "created_by": body.get("created_by", "admin"),
        "outgoing_legs": [],
        "incoming_legs": [],
        "cash": None,
        "cash_components": [],
        "margin_split": None,
        "counterparty": body.get("counterparty"),
        "notes": body.get("notes"),
    }
    repo.put_trade_session(session)
    return session


@router.get("/{trade_id}")
def get_trade_session(
    trade_id: str,
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Get a trade session (full admin view)."""
    session = repo.get_trade_session(trade_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Trade session not found")
    return session


@router.get("/{trade_id}/customer-view")
def get_trade_customer_view(
    trade_id: str,
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Get sanitized customer projection — strips cost_basis, margin, notes."""
    session = repo.get_trade_session(trade_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Trade session not found")

    # Strip internal fields from legs
    def _sanitize_leg(leg: dict) -> dict:
        return {
            "name": leg.get("name", ""),
            "set_name": leg.get("set_name"),
            "condition": leg.get("condition"),
            "finish": leg.get("finish"),
            "language": leg.get("language", "EN"),
            "agreed_value": leg.get("agreed_value"),
            "image_url": leg.get("image_url"),
        }

    outgoing = [_sanitize_leg(l) for l in session.get("outgoing_legs", [])]
    incoming = [_sanitize_leg(l) for l in session.get("incoming_legs", [])]

    total_out = sum(Decimal(str(l.get("agreed_value") or 0)) for l in session.get("outgoing_legs", []))
    total_in = sum(Decimal(str(l.get("agreed_value") or 0)) for l in session.get("incoming_legs", []))
    cash = session.get("cash")

    # Compute balance description
    if cash:
        cash_amount = Decimal(str(cash.get("amount", 0)))
        if cash.get("direction") == "they_pay":
            balance = f"You pay ${cash_amount}"
        else:
            balance = f"We pay ${cash_amount}"
    elif total_out == total_in:
        balance = "Even trade"
    elif total_out > total_in:
        balance = f"You pay ${total_out - total_in}"
    else:
        balance = f"We pay ${total_in - total_out}"

    return {
        "trade_id": session["trade_id"],
        "outgoing_legs": outgoing,
        "incoming_legs": incoming,
        "cash": cash,
        "total_out_value": str(total_out),
        "total_in_value": str(total_in),
        "balance_description": balance,
    }


@router.patch("/{trade_id}")
def update_trade_session(
    trade_id: str,
    body: dict[str, Any],
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Update trade metadata (mode, counterparty, notes, margin_split)."""
    session = repo.get_trade_session(trade_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Trade session not found")
    if session.get("status") != "draft":
        raise HTTPException(status_code=409, detail="Can only update draft sessions")

    for key in ("mode", "counterparty", "notes", "show_id", "trade_date", "margin_split"):
        if key in body:
            session[key] = body[key]

    repo.put_trade_session(session)
    return session


# ---------------------------------------------------------------------------
# Outgoing legs (our items going out)
# ---------------------------------------------------------------------------

@router.post("/{trade_id}/outgoing")
def add_outgoing_leg(
    trade_id: str,
    body: dict[str, Any],
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Add an outgoing leg (one of our items being traded away)."""
    session = repo.get_trade_session(trade_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Trade session not found")
    if session.get("status") != "draft":
        raise HTTPException(status_code=409, detail="Can only modify draft sessions")

    item_id = body.get("item_id")
    if not item_id:
        raise HTTPException(status_code=422, detail="item_id required")

    # Verify item exists and is available
    item = repo.get_inventory_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Item {item_id} not found")
    if item.status != ItemStatus.AVAILABLE:
        raise HTTPException(status_code=409, detail=f"Item {item_id} not available")

    # Check not already in session
    existing_ids = {l.get("item_id") for l in session.get("outgoing_legs", [])}
    if item_id in existing_ids:
        raise HTTPException(status_code=409, detail=f"Item {item_id} already in trade")

    leg = {
        "item_id": item_id,
        "card_id": getattr(item, "card_id", None),
        "name": body.get("name", getattr(item, "display_name", None) or ""),
        "set_name": body.get("set_name"),
        "condition": body.get("condition", getattr(item, "condition", None)),
        "finish": body.get("finish", getattr(item, "finish", None)),
        "language": body.get("language", str(item.language)),
        "market_value": body.get("market_value", str(item.current_market_value or 0)),
        "our_cost_basis": str(item.cost_basis),
        "agreed_value": body.get("agreed_value", str(item.current_market_value or 0)),
        "image_url": body.get("image_url"),
    }
    session.setdefault("outgoing_legs", []).append(leg)
    repo.put_trade_session(session)
    return session


@router.patch("/{trade_id}/outgoing/{item_id}")
def update_outgoing_leg(
    trade_id: str,
    item_id: str,
    body: dict[str, Any],
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Update fields on an outgoing leg (e.g. agreed_value)."""
    session = repo.get_trade_session(trade_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Trade session not found")
    if session.get("status") != "draft":
        raise HTTPException(status_code=409, detail="Can only modify draft sessions")

    legs = session.get("outgoing_legs", [])
    found = False
    for leg in legs:
        if leg.get("item_id") == item_id:
            for key in ("agreed_value", "name", "condition", "finish", "language"):
                if key in body:
                    leg[key] = body[key]
            found = True
            break

    if not found:
        raise HTTPException(status_code=404, detail=f"Item {item_id} not in outgoing legs")

    session["outgoing_legs"] = legs
    repo.put_trade_session(session)
    return session


@router.delete("/{trade_id}/outgoing/{item_id}")
def remove_outgoing_leg(
    trade_id: str,
    item_id: str,
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Remove an outgoing leg."""
    session = repo.get_trade_session(trade_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Trade session not found")
    if session.get("status") != "draft":
        raise HTTPException(status_code=409, detail="Can only modify draft sessions")

    legs = session.get("outgoing_legs", [])
    session["outgoing_legs"] = [l for l in legs if l.get("item_id") != item_id]
    if len(session["outgoing_legs"]) == len(legs):
        raise HTTPException(status_code=404, detail=f"Item {item_id} not in outgoing legs")

    repo.put_trade_session(session)
    return session


# ---------------------------------------------------------------------------
# Incoming legs (their cards coming in)
# ---------------------------------------------------------------------------

@router.post("/{trade_id}/incoming")
def add_incoming_leg(
    trade_id: str,
    body: dict[str, Any],
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Add an incoming leg (a card we're receiving in the trade)."""
    session = repo.get_trade_session(trade_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Trade session not found")
    if session.get("status") != "draft":
        raise HTTPException(status_code=409, detail="Can only modify draft sessions")

    if "name" not in body or "agreed_value" not in body:
        raise HTTPException(status_code=422, detail="name and agreed_value required")

    # Locations are admin-managed (Task 1.1) — never hardcode the list here.
    validate_location(repo, body.get("location"))

    leg = {
        "card_id": body.get("card_id"),
        "location": body.get("location"),
        "name": body["name"],
        "card_number": body.get("card_number"),
        "set_name": body.get("set_name"),
        "condition": body.get("condition"),
        "finish": body.get("finish", "normal"),
        "language": body.get("language", "EN"),
        "market_value": body.get("market_value"),
        "agreed_value": body["agreed_value"],
        "image_url": body.get("image_url"),
    }
    session.setdefault("incoming_legs", []).append(leg)
    repo.put_trade_session(session)
    return session


@router.delete("/{trade_id}/incoming/{index}")
def remove_incoming_leg(
    trade_id: str,
    index: int,
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Remove an incoming leg by index."""
    session = repo.get_trade_session(trade_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Trade session not found")
    if session.get("status") != "draft":
        raise HTTPException(status_code=409, detail="Can only modify draft sessions")

    legs = session.get("incoming_legs", [])
    if index < 0 or index >= len(legs):
        raise HTTPException(status_code=404, detail=f"Index {index} out of range")

    legs.pop(index)
    session["incoming_legs"] = legs
    repo.put_trade_session(session)
    return session


# ---------------------------------------------------------------------------
# Cash component
# ---------------------------------------------------------------------------

@router.put("/{trade_id}/cash")
def set_cash_component(
    trade_id: str,
    body: dict[str, Any],
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Set or update the cash component(s) of a trade.

    Supports two formats:
    - New: ``{"cash_components": [{"direction": ..., "amount": ..., "payment_method": ...}, ...]}``
    - Legacy: ``{"direction": ..., "amount": ..., "payment_method": ...}``

    New writes always store ``cash_components``. Legacy format is converted to a
    single-element list for storage but the ``cash`` key is also kept for backward compat.
    """
    session = repo.get_trade_session(trade_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Trade session not found")
    if session.get("status") != "draft":
        raise HTTPException(status_code=409, detail="Can only modify draft sessions")

    if "cash_components" in body:
        # New multi-asset format
        for comp in body["cash_components"]:
            _validate_payment_method(comp)
        session["cash_components"] = body["cash_components"]
        # Also update legacy cash key with first component for backward compat
        if body["cash_components"]:
            first = body["cash_components"][0]
            session["cash"] = {
                "direction": first.get("direction", "they_pay"),
                "amount": first.get("amount"),
                "payment_method": first.get("payment_method", "cash"),
            }
        else:
            session["cash"] = None
    else:
        # Legacy single-cash format
        legacy_cash = {
            "direction": body.get("direction", "they_pay"),
            "amount": body.get("amount"),
            "payment_method": body.get("payment_method", "cash"),
        }
        _validate_payment_method(legacy_cash)
        session["cash"] = legacy_cash
        # Also store as cash_components for consistency
        session["cash_components"] = [legacy_cash]

    repo.put_trade_session(session)
    return session


@router.delete("/{trade_id}/cash")
def remove_cash_component(
    trade_id: str,
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Remove all cash components."""
    session = repo.get_trade_session(trade_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Trade session not found")
    if session.get("status") != "draft":
        raise HTTPException(status_code=409, detail="Can only modify draft sessions")

    session["cash"] = None
    session["cash_components"] = []
    repo.put_trade_session(session)
    return session


# ---------------------------------------------------------------------------
# Balance
# ---------------------------------------------------------------------------

@router.get("/{trade_id}/balance")
def get_trade_balance(
    trade_id: str,
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Compute trade balance and margins.

    Reads ``cash_components`` first; falls back to legacy ``cash`` key
    for sessions created before the multi-asset upgrade.
    """
    session = repo.get_trade_session(trade_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Trade session not found")

    total_out = sum(
        Decimal(str(l.get("agreed_value") or 0))
        for l in session.get("outgoing_legs", [])
    )
    total_in = sum(
        Decimal(str(l.get("agreed_value") or 0))
        for l in session.get("incoming_legs", [])
    )
    total_cost_out = sum(
        Decimal(str(l.get("our_cost_basis") or 0))
        for l in session.get("outgoing_legs", [])
    )

    # Compute cash delta from cash_components (preferred) or legacy cash key
    cash_delta = Decimal("0")
    cash_components = session.get("cash_components", [])
    if cash_components:
        for comp in cash_components:
            amount = Decimal(str(comp.get("amount") or 0))
            if comp.get("direction") == "they_pay":
                cash_delta += amount
            else:
                cash_delta -= amount
    else:
        # Fallback to legacy single cash key
        cash = session.get("cash")
        if cash and cash.get("amount"):
            amount = Decimal(str(cash["amount"]))
            if cash.get("direction") == "they_pay":
                cash_delta = amount
            else:
                cash_delta = -amount

    # Margin: (value_in + cash_received - cost_of_out) / cost_of_out
    margin_pct = None
    if total_cost_out > 0:
        margin_pct = str(
            ((total_in + cash_delta - total_cost_out) / total_cost_out * 100)
            .quantize(Decimal("0.1"))
        )

    # Check for margin split
    margin_split = session.get("margin_split")
    margin_split_applied = bool(margin_split and margin_split.get("enabled"))

    return {
        "trade_id": session["trade_id"],
        "total_out_value": str(total_out),
        "total_in_value": str(total_in),
        "total_cost_basis": str(total_cost_out),
        "cash_delta": str(cash_delta),
        "cash_components_net": str(cash_delta),
        "margin_pct": margin_pct,
        "margin_split_applied": margin_split_applied,
        "is_balanced": abs(total_out - total_in - cash_delta) < Decimal("0.01"),
    }


# ---------------------------------------------------------------------------
# Confirm
# ---------------------------------------------------------------------------

@router.post("/{trade_id}/confirm")
def confirm_trade_session(
    trade_id: str,
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Atomically execute the trade: sell outgoing, create incoming, record cash."""
    session = repo.get_trade_session(trade_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Trade session not found")
    if session.get("status") != "draft":
        raise HTTPException(status_code=409, detail="Session is not in draft status")

    outgoing = session.get("outgoing_legs", [])
    incoming = session.get("incoming_legs", [])

    if not outgoing and not incoming:
        raise HTTPException(status_code=422, detail="Trade must have at least one leg")

    # Use trade_date if set (for backdating), otherwise today
    trade_date_str = session.get("trade_date")
    txn_date = date.fromisoformat(trade_date_str) if trade_date_str else date.today()

    show_id = session.get("show_id")
    items_sold = 0
    items_created = 0
    txns_created = 0

    # ------------------------------------------------------------------
    # Cost-basis allocation (spec §1 "Cost Basis Logic")
    #
    # A trade is not a realization event by default: the gain rides along in
    # the cards we received. So the incoming items inherit the OUTGOING items'
    # cost basis, adjusted only by cash that actually moved (cash we paid adds
    # to what the incoming cards cost us; cash they paid us returns part of it).
    #
    # A vendor `margin_split` is the exception: it declares that `percent` of
    # the trade's profit is recognized NOW rather than deferred. Recognizing
    # profit raises the incoming basis toward market by that amount, so a 100%
    # split ends at basis == agreed value (nothing left to defer) and a 0% /
    # absent split defers everything. Losses are never "recognized" this way.
    # ------------------------------------------------------------------
    total_out_basis = sum(
        (_money(leg.get("our_cost_basis") or leg.get("agreed_value")) for leg in outgoing),
        Decimal("0"),
    )
    cash_we_pay, cash_they_pay = _cash_totals(session)
    total_in_value = sum((_money(leg.get("agreed_value")) for leg in incoming), Decimal("0"))

    deferred_pool = total_out_basis + cash_we_pay - cash_they_pay
    total_profit = (total_in_value + cash_they_pay - cash_we_pay) - total_out_basis

    recognized = Decimal("0")
    margin_split = session.get("margin_split")
    if margin_split and margin_split.get("enabled") and total_profit > 0:
        # `percent` is the share of profit recognized now (0 = full deferral,
        # 100 = fully recognized ⇒ basis == agreed value).
        pct = _money(margin_split.get("percent"))
        if pct:
            recognized = total_profit * pct / Decimal("100")

    basis_pool = max(deferred_pool + recognized, Decimal("0"))
    incoming_basis = _allocate_incoming_basis(basis_pool, incoming)

    # ------------------------------------------------------------------
    # Lineage — make the resulting card chain walkable from either end.
    #
    # A 1-out/1-in trade is a clean succession, so the incoming item points at
    # the outgoing one. With multiple outgoing legs there is no single parent,
    # so we drop `predecessor_item_id` but still stamp ONE shared `lineage_id`
    # across every item on both sides. That is an approximation for N↔M trades;
    # the `trade_id` on the transactions preserves the full fidelity.
    #
    # We only ADOPT an outgoing item's existing `lineage_id` when every already-
    # chained outgoing item agrees on it. If two outgoing cards come from
    # DIFFERENT chains, rewriting one to the other's id would be destructive:
    # the lineage endpoint resolves a chain by filtering on `lineage_id`
    # (inventory.py), so the rewritten card's own predecessors would drop out of
    # its chain, and their chain would lose the card. Two histories destroyed to
    # record one. In that case we mint a fresh id for this trade's output and
    # leave both existing chains untouched — an item is therefore never moved
    # out of a lineage it already belongs to, only ever given its first one.
    # ------------------------------------------------------------------
    predecessor_item_id = outgoing[0]["item_id"] if len(outgoing) == 1 else None
    outgoing_items = {
        leg["item_id"]: repo.get_inventory_item(leg["item_id"]) for leg in outgoing
    }
    lineage_id: str | None = None
    if outgoing:
        existing_lineages = {
            item.lineage_id for item in outgoing_items.values()
            if item is not None and item.lineage_id
        }
        lineage_id = (
            existing_lineages.pop() if len(existing_lineages) == 1 else new_ulid()
        )

    # Process outgoing legs (our items being sold/traded away)
    for leg in outgoing:
        item_id = leg["item_id"]
        agreed_value = Decimal(str(leg.get("agreed_value") or 0))

        # Stamp the shared lineage BEFORE record_sale. That call flips `status`
        # via a targeted UpdateExpression so it preserves this write, whereas
        # `put_inventory_item` is an unconditional full-item put — running it
        # afterwards would write `status=available` back over the sale and
        # silently un-sell the card.
        #
        # Only ever fills in a MISSING lineage; never moves an item between
        # chains (see the note above).
        out_item = outgoing_items.get(item_id)
        if out_item is not None and out_item.lineage_id is None:
            out_item.lineage_id = lineage_id
            repo.put_inventory_item(out_item)

        txn = Transaction(
            type=TransactionType.SALE,
            item_id=item_id,
            category=ItemCategory.RAW,
            date=txn_date,
            amount=agreed_value,
            payment_method="trade",
            show_id=show_id,
            trade_id=trade_id,
        )
        try:
            repo.record_sale(txn)
            items_sold += 1
            txns_created += 1
            # A3: Write timeline event for outgoing item
            repo.put_timeline_event(item_id, {
                "item_id": item_id,
                "txn_id": txn.txn_id,
                "type": "trade_out",
                "date": txn_date.isoformat(),
                "amount": str(agreed_value),
                "payment_method": "trade",
                "trade_id": trade_id,
                "show_id": show_id,
            })
        except ItemAlreadySoldError:
            raise HTTPException(
                status_code=409,
                detail=f"Item {item_id} is already sold or unavailable",
            )

    # Process incoming legs (their cards becoming our inventory)
    for index, leg in enumerate(incoming):
        new_item_id = new_ulid()
        agreed_value = Decimal(str(leg.get("agreed_value") or 0))
        cost_basis = incoming_basis[index]

        item_data = {
            "kind": "raw",
            "item_id": new_item_id,
            "card_id": leg.get("card_id"),
            "status": "available",
            "finish": leg.get("finish") or "normal",
            "condition": leg.get("condition") or "NM",
            "language": leg.get("language") or "EN",
            "location": leg.get("location") or "toploader",
            "cost_basis": str(cost_basis),
            "market_value_at_purchase": str(leg.get("market_value") or agreed_value),
            "current_market_value": str(leg.get("market_value") or agreed_value),
            "acquired_at": txn_date.isoformat(),
            "acquired_show_id": show_id,
            "display_name": leg.get("name"),
            "lineage_id": lineage_id,
            "predecessor_item_id": predecessor_item_id,
        }
        inv_item = InventoryItemAdapter.validate_python(item_data)
        repo.put_inventory_item(inv_item)
        items_created += 1

        txn = Transaction(
            type=TransactionType.PURCHASE,
            item_id=new_item_id,
            category=ItemCategory.RAW,
            date=txn_date,
            amount=agreed_value,
            payment_method="trade",
            show_id=show_id,
            trade_id=trade_id,
        )
        repo.put_transaction(txn)
        txns_created += 1

        # Timeline event for the incoming item (mirrors the trade_out event
        # written above, plus the item it came across from).
        repo.put_timeline_event(new_item_id, {
            "item_id": new_item_id,
            "txn_id": txn.txn_id,
            "type": "trade_in",
            "date": txn_date.isoformat(),
            "amount": str(agreed_value),
            "payment_method": "trade",
            "trade_id": trade_id,
            "show_id": show_id,
            "counterpart_item_id": predecessor_item_id,
            "cost_basis": str(cost_basis),
        })

    # Process cash component(s)
    cash_components = session.get("cash_components", [])
    if cash_components:
        for comp in cash_components:
            comp_amount = Decimal(str(comp.get("amount") or 0))
            if not comp_amount:
                continue
            if comp.get("direction") == "they_pay":
                txn_type = TransactionType.SALE
            else:
                txn_type = TransactionType.PURCHASE

            cash_txn = Transaction(
                type=txn_type,
                item_id=trade_id,
                category=ItemCategory.RAW,
                date=txn_date,
                amount=comp_amount,
                payment_method=comp.get("payment_method", "cash"),
                show_id=show_id,
                trade_id=trade_id,
                notes=f"Cash component: {comp.get('direction')} via {comp.get('payment_method', 'cash')}",
            )
            repo.put_transaction(cash_txn)
            txns_created += 1
    else:
        # Fallback to legacy single cash key
        cash = session.get("cash")
        if cash and cash.get("amount"):
            cash_amount = Decimal(str(cash["amount"]))
            if cash.get("direction") == "they_pay":
                txn_type = TransactionType.SALE
            else:
                txn_type = TransactionType.PURCHASE

            cash_txn = Transaction(
                type=txn_type,
                item_id=trade_id,
                category=ItemCategory.RAW,
                date=txn_date,
                amount=cash_amount,
                payment_method=cash.get("payment_method", "cash"),
                show_id=show_id,
                trade_id=trade_id,
                notes=f"Cash component: {cash.get('direction')}",
            )
            repo.put_transaction(cash_txn)
            txns_created += 1

    # Compute final totals
    total_out = sum(Decimal(str(l.get("agreed_value") or 0)) for l in outgoing)
    total_in = sum(Decimal(str(l.get("agreed_value") or 0)) for l in incoming)

    # Update session
    session["status"] = "confirmed"
    session["confirmed_at"] = datetime.now(tz=timezone.utc).isoformat()
    session["total_out_value"] = str(total_out)
    session["total_in_value"] = str(total_in)
    repo.put_trade_session(session)

    return {
        "trade_id": trade_id,
        "status": "confirmed",
        "outgoing_count": items_sold,
        "incoming_count": items_created,
        "total_out_value": str(total_out),
        "total_in_value": str(total_in),
        "transactions_created": txns_created,
        "items_created": items_created,
        "items_sold": items_sold,
    }


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------

@router.post("/{trade_id}/cancel")
def cancel_trade_session(
    trade_id: str,
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Cancel a draft trade session."""
    session = repo.get_trade_session(trade_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Trade session not found")
    if session.get("status") != "draft":
        raise HTTPException(status_code=409, detail="Can only cancel draft sessions")

    session["status"] = "cancelled"
    repo.put_trade_session(session)
    return {"trade_id": trade_id, "status": "cancelled"}
