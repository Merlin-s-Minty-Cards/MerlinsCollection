"""``/admin/trades`` — Trade session lifecycle.

A trade is the most complex transaction: items going out (ours, sold),
items coming in (theirs, purchased), and an optional cash component to
balance. On confirm, outgoing items are marked SOLD, incoming items are
created as new inventory, and transactions are recorded for both sides.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
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

router = APIRouter(prefix="/trades", tags=["admin-trades"])


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
    """Update trade metadata (mode, counterparty, notes)."""
    session = repo.get_trade_session(trade_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Trade session not found")
    if session.get("status") != "draft":
        raise HTTPException(status_code=409, detail="Can only update draft sessions")

    for key in ("mode", "counterparty", "notes", "show_id"):
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

    leg = {
        "card_id": body.get("card_id"),
        "name": body["name"],
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
    """Set or update the cash component of a trade."""
    session = repo.get_trade_session(trade_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Trade session not found")
    if session.get("status") != "draft":
        raise HTTPException(status_code=409, detail="Can only modify draft sessions")

    session["cash"] = {
        "direction": body.get("direction", "they_pay"),
        "amount": body.get("amount"),
        "payment_method": body.get("payment_method", "cash"),
    }
    repo.put_trade_session(session)
    return session


@router.delete("/{trade_id}/cash")
def remove_cash_component(
    trade_id: str,
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Remove the cash component."""
    session = repo.get_trade_session(trade_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Trade session not found")
    if session.get("status") != "draft":
        raise HTTPException(status_code=409, detail="Can only modify draft sessions")

    session["cash"] = None
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
    """Compute trade balance and margins."""
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

    cash = session.get("cash")
    cash_delta = Decimal("0")
    if cash and cash.get("amount"):
        amount = Decimal(str(cash["amount"]))
        if cash.get("direction") == "they_pay":
            cash_delta = amount  # We receive cash
        else:
            cash_delta = -amount  # We pay cash

    # Margin: (value_in + cash_received - cost_of_out) / cost_of_out
    margin_pct = None
    if total_cost_out > 0:
        margin_pct = str(
            ((total_in + cash_delta - total_cost_out) / total_cost_out * 100)
            .quantize(Decimal("0.1"))
        )

    return {
        "trade_id": session["trade_id"],
        "total_out_value": str(total_out),
        "total_in_value": str(total_in),
        "total_cost_basis": str(total_cost_out),
        "cash_delta": str(cash_delta),
        "margin_pct": margin_pct,
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

    show_id = session.get("show_id")
    items_sold = 0
    items_created = 0
    txns_created = 0

    # Process outgoing legs (our items being sold/traded away)
    for leg in outgoing:
        item_id = leg["item_id"]
        agreed_value = Decimal(str(leg.get("agreed_value") or 0))

        txn = Transaction(
            type=TransactionType.SALE,
            item_id=item_id,
            category=ItemCategory.RAW,
            date=date.today(),
            amount=agreed_value,
            payment_method="trade",
            show_id=show_id,
            trade_id=trade_id,
        )
        try:
            repo.record_sale(txn)
            items_sold += 1
            txns_created += 1
        except ItemAlreadySoldError:
            raise HTTPException(
                status_code=409,
                detail=f"Item {item_id} is already sold or unavailable",
            )

    # Process incoming legs (their cards becoming our inventory)
    for leg in incoming:
        new_item_id = new_ulid()
        agreed_value = Decimal(str(leg.get("agreed_value") or 0))

        item_data = {
            "kind": "raw",
            "item_id": new_item_id,
            "card_id": leg.get("card_id"),
            "status": "available",
            "finish": leg.get("finish", "normal"),
            "condition": leg.get("condition", "NM"),
            "language": leg.get("language", "EN"),
            "location": "toploader",
            "cost_basis": str(agreed_value),
            "market_value_at_purchase": str(leg.get("market_value") or agreed_value),
            "current_market_value": str(leg.get("market_value") or agreed_value),
            "acquired_at": date.today().isoformat(),
            "acquired_show_id": show_id,
            "display_name": leg.get("name"),
        }
        inv_item = InventoryItemAdapter.validate_python(item_data)
        repo.put_inventory_item(inv_item)
        items_created += 1

        txn = Transaction(
            type=TransactionType.PURCHASE,
            item_id=new_item_id,
            category=ItemCategory.RAW,
            date=date.today(),
            amount=agreed_value,
            payment_method="trade",
            show_id=show_id,
            trade_id=trade_id,
        )
        repo.put_transaction(txn)
        txns_created += 1

    # Process cash component
    cash = session.get("cash")
    if cash and cash.get("amount"):
        cash_amount = Decimal(str(cash["amount"]))
        # Cash transaction: if they pay us, it's income on the trade
        # If we pay them, it's an expense
        if cash.get("direction") == "they_pay":
            txn_type = TransactionType.SALE
        else:
            txn_type = TransactionType.PURCHASE

        cash_txn = Transaction(
            type=txn_type,
            item_id=trade_id,  # Use trade_id as item_id for cash transactions
            category=ItemCategory.RAW,
            date=date.today(),
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
