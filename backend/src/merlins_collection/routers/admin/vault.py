"""``/admin/vault`` — Merlin's Vault: on-hold items with P&L tracking.

The vault shows all items currently on hold (not for sale), with per-card
profit/loss calculations against cost basis and current market value.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from merlins_collection.dependencies import get_repo
from merlins_collection.models.inventory import (
    InventoryItem,
    InventoryItemAdapter,
    ItemStatus,
)
from merlins_collection.services.dynamodb import InventoryRepository

router = APIRouter(prefix="/vault", tags=["admin-vault"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class VaultItem(BaseModel):
    item_id: str
    name: str
    kind: str
    cost_basis: str
    current_market_value: str | None
    sticker_price: str | None
    location: str | None
    condition: str | None
    dollar_net: str | None  # market - cost
    percent_net: str | None  # (market - cost) / cost * 100


class VaultSummary(BaseModel):
    total_items: int
    total_cost_basis: str
    total_market_value: str
    total_dollar_gain: str
    total_percent_gain: str | None


class VaultResponse(BaseModel):
    items: list[VaultItem]
    summary: VaultSummary


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=VaultResponse)
def get_vault(
    repo: InventoryRepository = Depends(get_repo),
) -> VaultResponse:
    """Get all on_hold items with P&L calculations."""
    all_items = repo.list_inventory()
    on_hold = [i for i in all_items if i.status == ItemStatus.ON_HOLD]

    vault_items: list[VaultItem] = []
    total_cost = Decimal("0")
    total_market = Decimal("0")

    for item in on_hold:
        cost = item.cost_basis
        market = item.current_market_value
        total_cost += cost

        dollar_net = None
        percent_net = None
        if market is not None:
            total_market += market
            delta = market - cost
            dollar_net = str(delta.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
            if cost > 0:
                pct = (delta / cost * Decimal("100")).quantize(
                    Decimal("0.1"), rounding=ROUND_HALF_UP
                )
                percent_net = str(pct)
        else:
            # If no market value, use cost for total_market to not skew
            total_market += cost

        # Get name from various possible fields
        name = (
            getattr(item, "display_name", None)
            or getattr(item, "product_name", None)
            or getattr(item, "description", None)
            or ""
        )

        vault_items.append(
            VaultItem(
                item_id=item.item_id,
                name=name,
                kind=item.kind,
                cost_basis=str(cost),
                current_market_value=str(market) if market is not None else None,
                sticker_price=str(item.sticker_price) if item.sticker_price is not None else None,
                location=getattr(item, "location", None),
                condition=str(getattr(item, "condition", None)) if getattr(item, "condition", None) else None,
                dollar_net=dollar_net,
                percent_net=percent_net,
            )
        )

    # Summary
    total_gain = total_market - total_cost
    total_pct = None
    if total_cost > 0:
        total_pct = str(
            (total_gain / total_cost * Decimal("100")).quantize(
                Decimal("0.1"), rounding=ROUND_HALF_UP
            )
        )

    summary = VaultSummary(
        total_items=len(vault_items),
        total_cost_basis=str(total_cost.quantize(Decimal("0.01"))),
        total_market_value=str(total_market.quantize(Decimal("0.01"))),
        total_dollar_gain=str(total_gain.quantize(Decimal("0.01"))),
        total_percent_gain=total_pct,
    )

    return VaultResponse(items=vault_items, summary=summary)


@router.post("/{item_id}/hold")
def move_to_vault(
    item_id: str,
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Move an available item to the vault (set status to on_hold)."""
    item = repo.get_inventory_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    if item.status not in (ItemStatus.AVAILABLE, ItemStatus.ON_HOLD):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot vault item with status '{item.status}'"
        )
    if item.status == ItemStatus.ON_HOLD:
        return {"item_id": item_id, "status": "on_hold", "message": "Already in vault"}

    data = item.model_dump(mode="python")
    data["status"] = ItemStatus.ON_HOLD
    updated = InventoryItemAdapter.validate_python(data)
    repo.put_inventory_item(updated)
    return {"item_id": item_id, "status": "on_hold", "message": "Moved to vault"}


@router.post("/{item_id}/release")
def release_from_vault(
    item_id: str,
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Release an item from the vault (set status back to available)."""
    item = repo.get_inventory_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    if item.status != ItemStatus.ON_HOLD:
        raise HTTPException(
            status_code=409,
            detail=f"Item is not in vault (status: '{item.status}')"
        )

    data = item.model_dump(mode="python")
    data["status"] = ItemStatus.AVAILABLE
    updated = InventoryItemAdapter.validate_python(data)
    repo.put_inventory_item(updated)
    return {"item_id": item_id, "status": "available", "message": "Released from vault"}
