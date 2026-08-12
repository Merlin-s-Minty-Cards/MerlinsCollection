"""``/admin/purchases`` — Buy session lifecycle.

A buy session is a draft container for cards being purchased. On confirm,
new inventory items are created and PURCHASE transactions are recorded.
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
    new_ulid,
)
from merlins_collection.services.dynamodb import InventoryRepository
from merlins_collection.services.locations import validate_location

router = APIRouter(prefix="/purchases", tags=["admin-purchases"])


def _review_reason_for_buy(buy_item: dict[str, Any]) -> str | None:
    """Why a bought item is going to Triage, or ``None`` if it is not.

    The Buy flow used to set the bare ``needs_review`` boolean, so these landed
    in Triage with no chip explaining what to fix — a queue with no stated
    problem, which the task doc rightly calls "not a worklist"
    (follow-ups.md, T11 row 8).

    Returns a value from ``MACHINE_REVIEW_REASONS`` only. That membership is
    load-bearing: the re-flag guard in ``admin_update_item`` uses it to tell
    automation from a human, and a reason outside the set would be mistaken for
    an admin's own note.

    An item can qualify both ways. ``manual_entry`` wins because it is the more
    actionable statement — it says a human typed this row rather than that a
    matcher came up empty.
    """
    if buy_item.get("manual_entry"):
        return "manual_entry"
    if buy_item.get("card_id") is None:
        return "no_catalog_link"
    return None


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

#: Fields a graded item cannot be staged without. Enforced HERE, at add time,
#: rather than at confirm: a session that swallows a bad item and explodes on
#: commit loses the whole staged batch, which is the failure the batch design
#: exists to prevent.
#:
#: `cert_number` is required because without one it is not a slab, it is just a
#: normal card (owner, 2026-08-08) -- and it is the key of the CERT# pointer
#: row, so there is nowhere to file the item without it.
_GRADED_REQUIRED_FIELDS = ("company", "grade", "cert_number")

#: Numeric fields on a staged item, as ``(field, required)``. Every one of them
#: reaches ``Decimal`` or pydantic during confirm, so every one of them can take
#: the whole batch down mid-write if it is malformed.
_STAGED_NUMERIC_FIELDS = (
    ("buy_price", True),
    ("market_value", False),
    ("buy_pct", False),
)


def _coerce_decimal(value: Any, field: str, *, required: bool) -> Decimal | None:
    """Coerce a JSON number or numeric string to an exact ``Decimal``.

    Raises ``ValueError`` with an operator-readable message rather than letting
    ``InvalidOperation`` escape as an unhandled 500.

    Two traps this exists for:

    * ``Decimal("NaN")`` and ``Decimal("Infinity")`` both PARSE. A bare
      try/except around the conversion is not enough — ``is_finite()`` is part
      of the check, not a nicety.
    * conversion goes through ``str()`` so a JSON float lands as an exact
      ``Decimal`` rather than its binary approximation (CLAUDE.md, Ops).

    Accepts a number or a numeric string on purpose: MCP and curl are real
    clients, and the backend is the last line rather than a mirror of one
    form's habits.
    """
    if value is None or value == "":
        if required:
            raise ValueError(f"{field} is required")
        return None
    try:
        dec = Decimal(str(value))
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an amount, got {value!r}") from exc
    if not dec.is_finite():
        raise ValueError(f"{field} must be a finite amount, got {value!r}")
    return dec


def _build_purchase(
    buy_item: dict[str, Any],
    *,
    txn_date: date,
    payment_method: str,
    show_id: str | None,
    batch_id: str | None = None,
) -> tuple[Any, Transaction, dict[str, Any]]:
    """Build the inventory item, transaction and timeline event for one row.

    Pure: it writes nothing. Raises ``ValueError`` (which pydantic's
    ``ValidationError`` subclasses) if the row cannot be turned into a valid
    purchase, so the caller can reject the whole batch before touching the repo.
    """
    # The numeric fields are coerced explicitly rather than left to pydantic:
    # `buy_price` becomes `cost_basis` BEFORE validation, so an unusable amount
    # would otherwise raise `InvalidOperation` here rather than a readable
    # error, and `market_value`/`buy_pct` never reach a validator at all.
    for field, required in _STAGED_NUMERIC_FIELDS:
        _coerce_decimal(buy_item.get(field), field, required=required)
    buy_price = _coerce_decimal(buy_item["buy_price"], "buy_price", required=True)

    new_item_id = new_ulid()
    common = {
        "item_id": new_item_id,
        "card_id": buy_item.get("card_id"),
        "status": "available",
        "language": buy_item.get("language", "EN"),
        "location": buy_item.get("location", "toploader"),
        "cost_basis": str(buy_price),
        "market_value_at_purchase": buy_item.get("market_value"),
        "current_market_value": buy_item.get("market_value"),
        "acquired_at": txn_date.isoformat(),
        "acquired_show_id": show_id,
        "display_name": buy_item.get("name"),
        "needs_review": bool(buy_item.get("manual_entry")) or buy_item.get("card_id") is None,
        "review_reason": _review_reason_for_buy(buy_item),
    }

    if buy_item.get("kind") == "graded":
        _coerce_decimal(buy_item.get("grade"), "grade", required=True)
        # `str()` on grade before validation, deliberately: the frontend
        # sends 9.5 as a JSON number, and routing it through str() gives
        # pydantic an exact Decimal("9.5") instead of a binary float.
        item_data = {
            **common,
            "kind": "graded",
            "company": buy_item["company"],
            "grade": str(buy_item["grade"]),
            "cert_number": str(buy_item["cert_number"]),
            "grade_label": buy_item.get("grade_label"),
            "cert_verified_at": buy_item.get("cert_verified_at"),
            "cert_image_url": buy_item.get("cert_image_url"),
            "price_source_id": buy_item.get("price_source_id"),
        }
        category = ItemCategory.GRADED
    else:
        item_data = {
            **common,
            "kind": "raw",
            "finish": buy_item.get("finish", "normal"),
            "condition": buy_item.get("condition", "NM"),
            "condition_modifier": buy_item.get("condition_modifier"),
        }
        category = ItemCategory.RAW

    inv_item = InventoryItemAdapter.validate_python(item_data)
    txn = Transaction(
        type=TransactionType.PURCHASE,
        item_id=new_item_id,
        category=category,
        date=txn_date,
        amount=buy_price,
        payment_method=payment_method,
        show_id=show_id,
        batch_id=batch_id,
    )
    event = {
        "item_id": new_item_id, "txn_id": txn.txn_id, "type": "purchase",
        "date": txn_date.isoformat(), "amount": str(buy_price),
        "payment_method": payment_method, "show_id": show_id,
    }
    return inv_item, txn, event


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

    # At ADD, not at confirm. `Number("1,300")` is NaN, which JSON-serialises to
    # `null`, and the presence check above waves it straight through — the item
    # then explodes mid-write on commit. Same reasoning as
    # `_GRADED_REQUIRED_FIELDS`: a session that swallows a bad item and blows up
    # on commit loses the whole staged batch.
    try:
        _coerce_decimal(body["buy_price"], "buy_price", required=True)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    kind = body.get("kind", "raw")
    if kind == "graded":
        # `in (None, "")` rather than falsiness: a grade of 0 is not a real PSA
        # grade, but the check should reject blanks, not numeric edge cases.
        missing = [f for f in _GRADED_REQUIRED_FIELDS if body.get(f) in (None, "")]
        if missing:
            raise HTTPException(
                status_code=422,
                detail=f"graded items require: {', '.join(missing)}",
            )

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
        "kind": kind,
        "company": body.get("company"),
        "grade": body.get("grade"),
        "cert_number": body.get("cert_number"),
        "grade_label": body.get("grade_label"),
        "cert_verified_at": body.get("cert_verified_at"),
        "cert_image_url": body.get("cert_image_url"),
        "price_source_id": body.get("price_source_id"),
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

    purchase_date_str = session.get("purchase_date")
    txn_date = date.fromisoformat(purchase_date_str) if purchase_date_str else date.today()

    # ---- Pass 1: BUILD every row. Nothing is written here. -----------------
    #
    # Confirm writes an inventory item, a PURCHASE transaction and a timeline
    # event per row, with no rollback and `status` set to `confirmed` only at
    # the end. When it was one pass, a five-row batch with a bad amount on row 3
    # left rows 1-2 as real inventory with real transactions, the session still
    # `draft`, and the UI reporting "Nothing was created; the batch is intact"
    # — which was false. Pressing Commit again then duplicated rows 1-2.
    #
    # Building everything first is simpler and stronger than compensating after
    # a partial write, and it fixes partial write as a CLASS: a bad `condition`,
    # `company` or `location` fails pydantic in here, where nothing has been
    # written yet, instead of halfway down the batch.
    problems: list[str] = []
    built: list[tuple[Any, Transaction, dict[str, Any]]] = []
    for idx, buy_item in enumerate(items, start=1):
        try:
            built.append(_build_purchase(
                buy_item,
                txn_date=txn_date,
                payment_method=payment_method,
                show_id=show_id,
                # Every row of this batch carries the session that produced it,
                # so a five-card buy reads as one transaction.
                batch_id=buy_id,
            ))
        except ValueError as exc:
            # ValueError covers pydantic's ValidationError, which subclasses it.
            # 1-based, to match the row the operator is looking at.
            problems.append(f"row {idx}: {exc}")
    if problems:
        raise HTTPException(
            status_code=422,
            detail=f"Nothing was written. Fix and retry — {'; '.join(problems)}",
        )

    # ---- Pass 2: WRITE. Everything here has already been validated. --------
    total_cost = Decimal("0")
    for inv_item, txn, event in built:
        repo.put_inventory_item(inv_item)
        repo.put_transaction(txn)
        repo.put_timeline_event(inv_item.item_id, event)
        total_cost += txn.amount
    items_created = len(built)

    # Update session
    session["status"] = "confirmed"
    session["total_cost"] = str(total_cost)
    repo.put_buy_session(session)

    return {
        "buy_id": buy_id,
        "status": "confirmed",
        "items_created": items_created,
        # WHAT was created, not just how many (RFC 0010 T12). Slab intake prices
        # the batch immediately after committing, scoped to these ids — without
        # them the only options are a second pricing path or an unscoped refresh
        # that spends the whole day's 50-lookup budget on the existing shelf.
        # Additive: every existing caller ignores it.
        "item_ids": [inv_item.item_id for inv_item, _txn, _event in built],
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
