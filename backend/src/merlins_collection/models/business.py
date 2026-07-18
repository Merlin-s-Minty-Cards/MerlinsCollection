"""Business entities: the transaction ledger, shows, consignors, and config.

``Transaction`` is the append-only record of money movement (one per purchase
and per sale). Net profit is always computed from transactions + item cost
basis, never stored. Config entities (cash accounts, buying policies, payment
methods) are tiny single-row records under the CONFIG partition.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from pydantic import BaseModel, Field

from merlins_collection.models.inventory import new_ulid


class TransactionType(StrEnum):
    SALE = "sale"
    PURCHASE = "purchase"


class ItemCategory(StrEnum):
    """Denormalized item category for Vending-Net-style breakdowns."""

    RAW = "raw"
    GRADED = "graded"
    SEALED = "sealed"
    BULK = "bulk"
    CONSIGNMENT = "consignment"


class Transaction(BaseModel):
    txn_id: str = Field(default_factory=new_ulid)
    type: TransactionType
    item_id: str
    category: ItemCategory
    date: date_type
    amount: Decimal
    payment_method: str
    fee: Decimal = Decimal("0")
    show_id: str | None = None
    trade_id: str | None = None
    consignor_payout: Decimal | None = None
    notes: str | None = None


class Show(BaseModel):
    show_id: str = Field(default_factory=new_ulid)
    name: str
    date: date_type
    sales_goal: Decimal | None = None
    cash_at_start: Decimal | None = None
    inventory_value_at_start: Decimal | None = None
    notes: str | None = None


class Consignor(BaseModel):
    consignor_id: str = Field(default_factory=new_ulid)
    name: str
    contact: str | None = None
    notes: str | None = None


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


class CashAccount(BaseModel):
    account: str  # venmo | bank | cash
    balance: Decimal
    updated_at: datetime = Field(default_factory=_utcnow)


class BuyingPolicy(BaseModel):
    product_type: str
    cash_pct_min: Decimal | None = None
    cash_pct_max: Decimal | None = None
    trade_pct_min: Decimal | None = None
    trade_pct_max: Decimal | None = None


class PaymentMethod(BaseModel):
    method: str
    fee_percent: Decimal = Decimal("0")
    fee_fixed: Decimal = Decimal("0")

    def fee_for(self, amount: Decimal) -> Decimal:
        """Fee for a gross amount, quantized to cents (half-up, like Venmo)."""
        pct = (amount * self.fee_percent / Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        return (pct + self.fee_fixed).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
