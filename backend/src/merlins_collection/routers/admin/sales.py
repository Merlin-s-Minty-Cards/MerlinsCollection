"""``/admin/sales`` — Sell session lifecycle.

A sell session is a draft container for items being sold. On confirm, each
item's status is flipped to SOLD and a SALE transaction is recorded atomically.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from merlins_collection.dependencies import get_repo
from merlins_collection.models.business import ItemCategory, Transaction, TransactionType
from merlins_collection.models.inventory import ItemStatus, new_ulid
from merlins_collection.services.dynamodb import InventoryRepository, ItemAlreadySoldError

router = APIRouter(prefix="/sales", tags=["admin-sales"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class SellSessionItem(BaseModel):
    item_id: str
    name: str = ""
    agreed_price: Decimal
    original_price: Decimal | None = None
    discount_pct: Decimal | None = None


class SellSession(BaseModel):
    sell_id: str
    status: Literal["draft", "confirmed", "cancelled"] = "draft"
    show_id: str | None = None
    created_at: str
    created_by: str = "admin"
    items: list[SellSessionItem] = []
    total_revenue: Decimal | None = None
    payment_method: str | None = None
    fee: Decimal | None = None
    counterparty: str | None = None
    notes: str | None = None


class SellConfirmResult(BaseModel):
    sell_id: str
    status: str
    items_sold: int
    total_revenue: Decimal
    fee: Decimal


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("", status_code=201)
def create_sell_session(
    body: dict[str, Any],
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Create a new draft sell session."""
    sell_id = new_ulid()
    session = {
        "sell_id": sell_id,
        "status": "draft",
        "show_id": body.get("show_id"),
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "created_by": body.get("created_by", "admin"),
        "items": [],
        "total_revenue": None,
        "payment_method": body.get("payment_method"),
        "fee": body.get("fee"),
        "counterparty": body.get("counterparty"),
        "notes": body.get("notes"),
    }
    repo.put_sell_session(session)
    return session


@router.get("/{sell_id}")
def get_sell_session(
    sell_id: str,
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Get a sell session by id."""
    session = repo.get_sell_session(sell_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Sell session not found")
    return session


@router.patch("/{sell_id}")
def update_sell_session(
    sell_id: str,
    body: dict[str, Any],
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Update sell session metadata (counterparty, payment_method, notes, etc)."""
    session = repo.get_sell_session(sell_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Sell session not found")
    if session.get("status") != "draft":
        raise HTTPException(status_code=409, detail="Can only update draft sessions")

    # Merge allowed fields
    for key in ("counterparty", "payment_method", "fee", "notes", "show_id"):
        if key in body:
            session[key] = body[key]

    repo.put_sell_session(session)
    return session


@router.post("/{sell_id}/items")
def add_sell_item(
    sell_id: str,
    body: dict[str, Any],
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Add an inventory item to the sell session."""
    session = repo.get_sell_session(sell_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Sell session not found")
    if session.get("status") != "draft":
        raise HTTPException(status_code=409, detail="Can only add items to draft sessions")

    item_id = body.get("item_id")
    if not item_id:
        raise HTTPException(status_code=422, detail="item_id required")

    # Verify item exists and is available
    item = repo.get_inventory_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Item {item_id} not found")
    if item.status != ItemStatus.AVAILABLE:
        raise HTTPException(status_code=409, detail=f"Item {item_id} is not available (status: {item.status})")

    # Check not already in session
    existing_ids = {i["item_id"] for i in session.get("items", [])}
    if item_id in existing_ids:
        raise HTTPException(status_code=409, detail=f"Item {item_id} already in session")

    sell_item = {
        "item_id": item_id,
        "name": body.get("name", getattr(item, "display_name", None) or ""),
        "agreed_price": body.get("agreed_price"),
        "original_price": body.get("original_price"),
        "discount_pct": body.get("discount_pct"),
    }
    session.setdefault("items", []).append(sell_item)
    repo.put_sell_session(session)
    return session


@router.delete("/{sell_id}/items/{item_id}")
def remove_sell_item(
    sell_id: str,
    item_id: str,
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Remove an item from the sell session."""
    session = repo.get_sell_session(sell_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Sell session not found")
    if session.get("status") != "draft":
        raise HTTPException(status_code=409, detail="Can only modify draft sessions")

    items = session.get("items", [])
    session["items"] = [i for i in items if i["item_id"] != item_id]
    if len(session["items"]) == len(items):
        raise HTTPException(status_code=404, detail=f"Item {item_id} not in session")

    repo.put_sell_session(session)
    return session


@router.post("/{sell_id}/confirm")
def confirm_sell_session(
    sell_id: str,
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Confirm the sell session: mark items SOLD + record transactions atomically."""
    session = repo.get_sell_session(sell_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Sell session not found")
    if session.get("status") != "draft":
        raise HTTPException(status_code=409, detail="Session is not in draft status")

    items = session.get("items", [])
    if not items:
        raise HTTPException(status_code=422, detail="Cannot confirm empty session")

    fee = Decimal(str(session.get("fee") or "0"))
    payment_method = session.get("payment_method") or "cash"
    show_id = session.get("show_id")
    total_revenue = Decimal("0")
    items_sold = 0

    # Process each item
    for sell_item in items:
        price = Decimal(str(sell_item["agreed_price"]))
        total_revenue += price

        # Determine item category
        inv_item = repo.get_inventory_item(sell_item["item_id"])
        category = ItemCategory(inv_item.kind) if inv_item else ItemCategory.RAW

        txn = Transaction(
            type=TransactionType.SALE,
            item_id=sell_item["item_id"],
            category=category,
            date=date.today(),
            amount=price,
            payment_method=payment_method,
            fee=fee / len(items) if fee else Decimal("0"),  # Split fee across items
            show_id=show_id,
        )

        try:
            repo.record_sale(txn)
            items_sold += 1
        except ItemAlreadySoldError:
            raise HTTPException(
                status_code=409,
                detail=f"Item {sell_item['item_id']} is already sold or unavailable",
            )

    # Update session status
    session["status"] = "confirmed"
    session["total_revenue"] = str(total_revenue)
    repo.put_sell_session(session)

    return {
        "sell_id": sell_id,
        "status": "confirmed",
        "items_sold": items_sold,
        "total_revenue": str(total_revenue),
        "fee": str(fee),
    }


@router.post("/{sell_id}/cancel")
def cancel_sell_session(
    sell_id: str,
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Cancel a draft sell session."""
    session = repo.get_sell_session(sell_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Sell session not found")
    if session.get("status") != "draft":
        raise HTTPException(status_code=409, detail="Can only cancel draft sessions")

    session["status"] = "cancelled"
    repo.put_sell_session(session)
    return {"sell_id": sell_id, "status": "cancelled"}
