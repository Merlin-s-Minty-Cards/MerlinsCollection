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

from pydantic import BaseModel, Field, model_validator

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


class ExpenseCategory(StrEnum):
    """Which expense tab a cost came from (all six share one ``Expense`` shape)."""

    SHOW_FEE = "show_fee"
    OTHER_COGS = "other_cogs"
    MARKETING = "marketing"
    SUPPLIES = "supplies"
    EMPLOYEE_WAGE = "employee_wage"
    EMPLOYEE_EXPENSE = "employee_expense"


class Expense(BaseModel):
    """A business cost. ``amount`` is signed: negative means money came *in*
    (a refund/credit), matching the sheet's own "neg numbers is money coming in"
    convention. Kept in its own ``EXP#<month>`` ledger, never on the show GSI2."""

    expense_id: str = Field(default_factory=new_ulid)
    category: ExpenseCategory
    date: date_type
    amount: Decimal
    payment_method: str = "cash"
    description: str | None = None
    reason: str | None = None
    person: str | None = None  # for wages / per-person employee expenses
    show_id: str | None = None
    paid: bool = True
    notes: str | None = None


class Show(BaseModel):
    show_id: str = Field(default_factory=new_ulid)
    name: str
    date: date_type
    # Optional structured location. Both default to None and are populated only
    # when the import source carries dedicated columns — rows stored before these
    # fields existed validate to None (backward-compatible; no data migration).
    venue: str | None = None   # physical venue name, e.g. "Lloyd Center"
    city: str | None = None    # "Portland, OR"
    sales_goal: Decimal | None = None
    cash_at_start: Decimal | None = None
    inventory_value_at_start: Decimal | None = None
    notes: str | None = None
    # "Deleted" in the admin UI. Nothing is ever destroyed: a mistakenly
    # archived show with real transaction history stays recoverable and the
    # analytics snapshots that reference it never dangle. Rows stored before
    # this field existed carry no ``archived`` attribute and default to False.
    archived: bool = False


class ShowAnalyticsSnapshot(BaseModel):
    """Pre-computed analytics for a completed show (A4)."""

    show_id: str
    date: date_type
    total_sold: Decimal = Decimal("0")
    total_bought: Decimal = Decimal("0")
    net_sales: Decimal = Decimal("0")
    inventory_value_at_start: Decimal | None = None
    sell_through_rate: Decimal | None = None
    items_sold_count: int = 0
    items_bought_count: int = 0
    trades_count: int = 0
    cash_at_start: Decimal | None = None
    snapshot_generated_at: datetime | None = None


class DebtDirection(StrEnum):
    OWED_TO_US = "owed_to_us"
    WE_OWE = "we_owe"


class Debt(BaseModel):
    """A single outstanding (or cleared) debt, in either direction."""

    debt_id: str = Field(default_factory=new_ulid)
    direction: DebtDirection
    date: date_type
    amount: Decimal
    counterparty: str
    reason: str | None = None
    cleared: bool = False


class Consignor(BaseModel):
    consignor_id: str = Field(default_factory=new_ulid)
    name: str
    contact: str | None = None  # legacy — kept for backward compat
    email: str | None = None
    phone: str | None = None
    payout_percent: Decimal = Decimal("50")  # default payout % to consignor
    # "Deleted" in the admin UI, and the same contract as ``Show.archived``:
    # nothing is ever destroyed, so a consignment ledger can never lose its
    # counterparty and an archived consignor stays recoverable.
    archived: bool = False
    notes: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _archived_from_legacy_active(cls, data):
        """Read a pre-RFC-0010 row's ``active: False`` as ``archived: True``.

        ``active`` meant exactly this under a worse name and was read almost
        nowhere — only written at create and by the soft delete. It is gone as a
        field, because two live booleans for one concept is how the next reader
        introduces a bug, and ``archived`` is the name CLAUDE.md's archiving
        contract already established.

        The mapping is not hypothetical: the owner had already soft-deleted a
        consignor before this landed, so at least one production row carries
        ``active: False`` and must render as archived rather than as active.

        An explicit ``archived`` always wins; ``active`` is consulted only when
        the row predates the field, so an old client's payload is migrated
        rather than rejected.
        """
        if isinstance(data, dict) and "active" in data and data.get("archived") is None:
            data = dict(data)
            data["archived"] = not bool(data.pop("active"))
        return data


class Payout(BaseModel):
    """A profit-split payment to a business partner for one event. Distinct from
    a consignor payout (which rides on the sale transaction).

    The Payouts tab carries no per-payout date or payment method and no reliable
    show linkage (its ``Event`` label is free text), so those fields are omitted
    until a source column and a consumer actually exist (YAGNI)."""

    payout_id: str = Field(default_factory=new_ulid)
    event: str
    partner: str
    amount: Decimal
    percent: Decimal | None = None
    notes: str | None = None


class BalanceSheetSection(StrEnum):
    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"


class BalanceSheetLine(BaseModel):
    section: BalanceSheetSection
    label: str
    amount: Decimal
    note: str | None = None


class BalanceSheetSnapshot(BaseModel):
    """A point-in-time balance sheet, stored whole so a frozen baseline can later
    be compared against the live "current" one. ``frozen`` marks the immutable
    baseline; the current snapshot keeps changing until the next freeze."""

    snapshot_id: str = Field(default_factory=new_ulid)
    label: str
    date: date_type | None = None
    frozen: bool = False
    lines: list[BalanceSheetLine] = Field(default_factory=list)
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
