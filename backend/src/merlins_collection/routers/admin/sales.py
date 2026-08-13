"""``/admin/sales`` — Sell session lifecycle.

A sell session is a draft container for items being sold. On confirm, each
item's status is flipped to SOLD and a SALE transaction is recorded atomically.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from merlins_collection.dependencies import get_repo
from merlins_collection.models.business import ItemCategory, Transaction, TransactionType
from merlins_collection.models.inventory import ItemStatus, new_ulid
from merlins_collection.services.card_text import admin_item_name
from merlins_collection.services.dynamodb import InventoryRepository, ItemAlreadySoldError
from merlins_collection.services.money import coerce_decimal

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
    net_revenue: Decimal | None = None


# ---------------------------------------------------------------------------
# Fee calculation
# ---------------------------------------------------------------------------

# Payment method fee schedules (built-in, no DB lookup needed for these common ones)
_PAYMENT_FEES: dict[str, tuple[Decimal, Decimal]] = {
    # method: (percent_rate, fixed_fee)
    "cash": (Decimal("0"), Decimal("0")),
    "card": (Decimal("0"), Decimal("0")),
    "venmo": (Decimal("1.9"), Decimal("0.10")),
    "zelle": (Decimal("0"), Decimal("0")),
    "epayment": (Decimal("0"), Decimal("0")),
}


def _calculate_method_fee(amount: Decimal, method: str) -> Decimal:
    """Calculate fee for a payment method. Venmo: (amount x 1.9%) + $0.10."""
    pct_rate, fixed = _PAYMENT_FEES.get(method, (Decimal("0"), Decimal("0")))
    if pct_rate == 0 and fixed == 0:
        return Decimal("0")
    pct_fee = (amount * pct_rate / Decimal("100")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return (pct_fee + fixed).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


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


@router.get("/calculate-fee")
def calculate_fee(
    amount: Decimal = Query(...),
    payment_method: str = Query("cash"),
) -> dict[str, Any]:
    """Calculate the fee for a given amount and payment method.

    Fee schedules:
    - cash: no fee
    - card: no fee (handled by card reader hardware)
    - venmo: (amount x 1.9%) + $0.10
    - zelle: no fee
    - epayment: no fee (generic e-payment)
    """
    fee = _calculate_method_fee(amount, payment_method)
    net = amount - fee
    return {
        "amount": str(amount),
        "payment_method": payment_method,
        "fee": str(fee),
        "net": str(net),
    }


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
    for key in ("counterparty", "payment_method", "fee", "notes", "show_id", "sale_date"):
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
        raise HTTPException(
            status_code=409,
            detail=f"Item {item_id} is not available (status: {item.status})",
        )

    # Check not already in session
    existing_ids = {i["item_id"] for i in session.get("items", [])}
    if item_id in existing_ids:
        raise HTTPException(status_code=409, detail=f"Item {item_id} already in session")

    sell_item = {
        "item_id": item_id,
        "name": body.get("name", admin_item_name(item)),
        "agreed_price": body.get("agreed_price"),
        "original_price": body.get("original_price"),
        "discount_pct": body.get("discount_pct"),
    }
    session.setdefault("items", []).append(sell_item)
    repo.put_sell_session(session)
    return session


@router.patch("/{sell_id}/items/{item_id}")
def update_sell_item_price(
    sell_id: str,
    item_id: str,
    body: dict[str, Any],
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Reprice one staged item — the route a discount at the table travels on.

    Without this the Sell page could only ever send the price ``add_sell_item``
    posted: its per-item field and its bulk-discount button both edited local
    state, and confirm carried no per-item body. So a card discounted at a show
    was handed over at the lower price and BOOKED at the higher one, overstating
    revenue and profit on every discounted sale (follow-ups.md, T1).

    Draft-only, for the same reason the ledger's correction path is a void
    rather than an edit: once a sale is confirmed the transaction is written,
    and quietly changing what it says is how two sets of books come to disagree.

    ``agreed_price`` is the ONLY field here on purpose. ``discount_pct`` is
    stored on the staged item but the client computes the discounted figure, and
    accepting both would make two fields authoritative for one number — the
    exact shape of the bug this route exists to close.
    """
    session = repo.get_sell_session(sell_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Sell session not found")
    if session.get("status") != "draft":
        raise HTTPException(status_code=409, detail="Can only reprice draft sessions")

    try:
        # minimum=0, not a truthiness check: a free throw-in is a real sale at a
        # show, so ZERO is allowed and only a negative is refused.
        price = coerce_decimal(
            body.get("agreed_price"), "agreed_price",
            required=True, minimum=Decimal(0),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    for sell_item in session.get("items", []):
        if sell_item["item_id"] == item_id:
            sell_item["agreed_price"] = str(price)
            break
    else:
        raise HTTPException(status_code=404, detail=f"Item {item_id} not in session")

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

    payment_method = session.get("payment_method") or "cash"
    show_id = session.get("show_id")
    total_revenue = Decimal("0")
    items_sold = 0

    # Use sale_date if set (for backdating), otherwise today
    sale_date_str = session.get("sale_date")
    txn_date = date.fromisoformat(sale_date_str) if sale_date_str else date.today()

    # Calculate total first for fee computation
    for sell_item in items:
        total_revenue += Decimal(str(sell_item["agreed_price"]))

    # Calculate fee based on payment method
    fee = _calculate_method_fee(total_revenue, payment_method)

    # Reset and process each item
    total_revenue = Decimal("0")
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
            date=txn_date,
            amount=price,
            payment_method=payment_method,
            fee=fee / len(items) if fee else Decimal("0"),  # Split fee across items
            show_id=show_id,
            batch_id=sell_id,
        )

        try:
            repo.record_sale(txn)
            items_sold += 1
            repo.put_timeline_event(sell_item["item_id"], {
                "item_id": sell_item["item_id"], "txn_id": txn.txn_id, "type": "sale",
                "date": txn_date.isoformat(), "amount": str(price),
                "payment_method": payment_method, "show_id": show_id,
            })
        except ItemAlreadySoldError:
            raise HTTPException(
                status_code=409,
                detail=f"Item {sell_item['item_id']} is already sold or unavailable",
            )

    # Update session status
    session["status"] = "confirmed"
    session["total_revenue"] = str(total_revenue)
    session["fee"] = str(fee)
    repo.put_sell_session(session)

    net_revenue = total_revenue - fee
    return {
        "sell_id": sell_id,
        "status": "confirmed",
        "items_sold": items_sold,
        "total_revenue": str(total_revenue),
        "fee": str(fee),
        "net_revenue": str(net_revenue),
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
