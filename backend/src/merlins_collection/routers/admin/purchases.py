"""``/admin/purchases`` — Buy session lifecycle.

A buy session is a draft container for cards being purchased. On confirm,
new inventory items are created and PURCHASE transactions are recorded.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from merlins_collection.dependencies import get_repo
from merlins_collection.models.business import ItemCategory, Transaction, TransactionType
from merlins_collection.models.inventory import (
    Condition,
    InventoryItemAdapter,
    Language,
    new_ulid,
)
from merlins_collection.services.dynamodb import InventoryRepository
from merlins_collection.services.locations import validate_location

router = APIRouter(prefix="/purchases", tags=["admin-purchases"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class BuySessionItem(BaseModel):
    card_id: str | None = None
    name: str
    set_name: str | None = None
    number: str | None = None
    condition: str = "NM"
    condition_modifier: str | None = None
    finish: str = "normal"
    language: str = "EN"
    market_value: Decimal | None = None
    buy_price: Decimal
    buy_pct: Decimal | None = None
    location: str = "toploader"


class BuySession(BaseModel):
    buy_id: str
    status: Literal["draft", "confirmed", "cancelled"] = "draft"
    show_id: str | None = None
    created_at: str
    created_by: str = "admin"
    items: list[dict[str, Any]] = []
    total_cost: Decimal | None = None
    payment_method: str | None = None
    counterparty: str | None = None
    notes: str | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("", status_code=201)
def create_buy_session(
    body: dict[str, Any],
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Create a new draft buy session."""
    buy_id = new_ulid()
    session = {
        "buy_id": buy_id,
        "status": "draft",
        "show_id": body.get("show_id"),
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "created_by": body.get("created_by", "admin"),
        "items": [],
        "total_cost": None,
        "payment_method": body.get("payment_method"),
        "counterparty": body.get("counterparty"),
        "notes": body.get("notes"),
    }
    repo.put_buy_session(session)
    return session


@router.get("/{buy_id}")
def get_buy_session(
    buy_id: str,
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Get a buy session by id."""
    session = repo.get_buy_session(buy_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Buy session not found")
    return session


@router.patch("/{buy_id}")
def update_buy_session(
    buy_id: str,
    body: dict[str, Any],
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Update buy session metadata."""
    session = repo.get_buy_session(buy_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Buy session not found")
    if session.get("status") != "draft":
        raise HTTPException(status_code=409, detail="Can only update draft sessions")

    for key in ("counterparty", "payment_method", "notes", "show_id"):
        if key in body:
            session[key] = body[key]

    if "purchase_date" in body:
        try:
            date.fromisoformat(body["purchase_date"])
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="purchase_date must be YYYY-MM-DD")
        session["purchase_date"] = body["purchase_date"]

    repo.put_buy_session(session)
    return session


@router.post("/{buy_id}/items")
def add_buy_item(
    buy_id: str,
    body: dict[str, Any],
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Add an item to the buy session (a card being purchased)."""
    session = repo.get_buy_session(buy_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Buy session not found")
    if session.get("status") != "draft":
        raise HTTPException(status_code=409, detail="Can only add items to draft sessions")

    if "name" not in body or "buy_price" not in body:
        raise HTTPException(status_code=422, detail="name and buy_price required")

    validate_location(repo, body.get("location", "toploader"))

    buy_item = {
        "card_id": body.get("card_id"),
        "name": body["name"],
        "set_name": body.get("set_name"),
        "number": body.get("number"),
        "condition": body.get("condition", "NM"),
        "condition_modifier": body.get("condition_modifier"),
        "finish": body.get("finish", "normal"),
        "language": body.get("language", "EN"),
        "market_value": body.get("market_value"),
        "buy_price": body["buy_price"],
        "buy_pct": body.get("buy_pct"),
        "location": body.get("location", "toploader"),
        "manual_entry": bool(body.get("manual_entry")),
    }
    session.setdefault("items", []).append(buy_item)
    repo.put_buy_session(session)
    return session


@router.delete("/{buy_id}/items/{idx}")
def remove_buy_item(
    buy_id: str,
    idx: int,
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Remove an item from the buy session by index."""
    session = repo.get_buy_session(buy_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Buy session not found")
    if session.get("status") != "draft":
        raise HTTPException(status_code=409, detail="Can only modify draft sessions")

    items = session.get("items", [])
    if idx < 0 or idx >= len(items):
        raise HTTPException(status_code=404, detail=f"Item index {idx} out of range")

    items.pop(idx)
    session["items"] = items
    repo.put_buy_session(session)
    return session


@router.post("/{buy_id}/confirm")
def confirm_buy_session(
    buy_id: str,
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Confirm the buy session: create inventory items + record PURCHASE transactions."""
    session = repo.get_buy_session(buy_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Buy session not found")
    if session.get("status") != "draft":
        raise HTTPException(status_code=409, detail="Session is not in draft status")

    items = session.get("items", [])
    if not items:
        raise HTTPException(status_code=422, detail="Cannot confirm empty session")

    payment_method = session.get("payment_method") or "cash"
    show_id = session.get("show_id")
    total_cost = Decimal("0")
    items_created = 0

    purchase_date_str = session.get("purchase_date")
    txn_date = date.fromisoformat(purchase_date_str) if purchase_date_str else date.today()

    for buy_item in items:
        buy_price = Decimal(str(buy_item["buy_price"]))
        total_cost += buy_price

        # Create a new inventory item
        new_item_id = new_ulid()
        item_data = {
            "kind": "raw",
            "item_id": new_item_id,
            "card_id": buy_item.get("card_id"),
            "status": "available",
            "finish": buy_item.get("finish", "normal"),
            "condition": buy_item.get("condition", "NM"),
            "condition_modifier": buy_item.get("condition_modifier"),
            "language": buy_item.get("language", "EN"),
            "location": buy_item.get("location", "toploader"),
            "cost_basis": str(buy_price),
            "market_value_at_purchase": buy_item.get("market_value"),
            "current_market_value": buy_item.get("market_value"),
            "acquired_at": txn_date.isoformat(),
            "acquired_show_id": show_id,
            "display_name": buy_item.get("name"),
            "needs_review": bool(buy_item.get("manual_entry")) or buy_item.get("card_id") is None,
        }

        inv_item = InventoryItemAdapter.validate_python(item_data)
        repo.put_inventory_item(inv_item)
        items_created += 1

        # Record PURCHASE transaction
        txn = Transaction(
            type=TransactionType.PURCHASE,
            item_id=new_item_id,
            category=ItemCategory.RAW,
            date=txn_date,
            amount=buy_price,
            payment_method=payment_method,
            show_id=show_id,
        )
        repo.put_transaction(txn)

        repo.put_timeline_event(new_item_id, {
            "item_id": new_item_id, "txn_id": txn.txn_id, "type": "purchase",
            "date": txn_date.isoformat(), "amount": str(buy_price),
            "payment_method": payment_method, "show_id": show_id,
        })

    # Update session
    session["status"] = "confirmed"
    session["total_cost"] = str(total_cost)
    repo.put_buy_session(session)

    return {
        "buy_id": buy_id,
        "status": "confirmed",
        "items_created": items_created,
        "total_cost": str(total_cost),
    }


@router.post("/{buy_id}/cancel")
def cancel_buy_session(
    buy_id: str,
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Cancel a draft buy session."""
    session = repo.get_buy_session(buy_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Buy session not found")
    if session.get("status") != "draft":
        raise HTTPException(status_code=409, detail="Can only cancel draft sessions")

    session["status"] = "cancelled"
    repo.put_buy_session(session)
    return {"buy_id": buy_id, "status": "cancelled"}
