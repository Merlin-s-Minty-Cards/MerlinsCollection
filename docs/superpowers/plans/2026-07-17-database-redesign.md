# Database Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the DynamoDB data model into the business's system of record: unified inventory items (raw/graded/sealed/bulk) keyed by `item_id`, a purchase/sale transaction ledger, shows, consignors, config entities, and a spreadsheet import script.

**Architecture:** Single table `merlins-cards`, existing GSI1 plus new GSI2 (show→transactions). Items are one physical unit each (no quantity). Money movement lives in an append-only ledger partitioned by month; selling is one atomic `TransactWriteItems`. Reports stay computed (out of scope here). Spec: `docs/superpowers/specs/2026-07-17-database-redesign-design.md`.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, boto3/DynamoDB, moto for tests, `python-ulid` for ids.

## Global Constraints

- All money and grades are `Decimal`; floats never touch prices (DynamoDB rejects floats).
- Keep the `/inventory/search` request/response contract: same flat query params, same response shape; changes additive only. `kind` literals stay `raw` / `graded` (+ new `sealed`).
- Customer search returns only `status == available` items of kinds raw/graded/sealed (never bulk), and strips `cost_basis`, `consignment`, `needs_review`.
- `condition` remains the 5-tier enum `NM|LP|MP|HP|DMG`; the +/- nuance is a separate `condition_modifier` field, so `condition=LP` filter matches LP+, LP, LP-.
- The repository is the only module that knows key formats.
- TDD: every behavior gets a RED test first. Run tests with `python -m pytest backend/tests -q --tb=short` (full) or targeted `python -m pytest backend/tests/<file>::<test> -q` from the repo root.
- Lint must stay clean: `ruff check backend/src` (line length 100).
- Commit after every task (small, frequent commits on branch `Database-Redesign`).

**Spec deviations (agreed at plan time):** none removed; sealed-product price history is implemented as `ITEM#<item_id>` price points (Task 8) since sealed items have no `card_id`.

---

### Task 1: Reshape inventory domain models

**Files:**
- Modify: `backend/src/merlins_collection/models/inventory.py`
- Test: `backend/tests/models/test_inventory.py`
- Modify (mechanical fixture updates): `backend/tests/services/test_dynamodb.py`, `backend/tests/services/test_catalog_sync.py`, `backend/tests/routers/test_inventory.py`, `backend/tests/test_tool_contract.py`
- Modify: `backend/pyproject.toml` (add `python-ulid>=2.2` to runtime deps)

**Interfaces:**
- Consumes: existing `Condition`, `GradingCompany` enums (kept as-is).
- Produces (later tasks rely on these exact names):
  - `new_ulid() -> str` (module function)
  - `ItemStatus` StrEnum: `AVAILABLE="available"`, `ON_HOLD="on_hold"`, `SOLD="sold"`, `OUT_FOR_GRADING="out_for_grading"`, `LOST="lost"`, `RETURNED_TO_CONSIGNOR="returned_to_consignor"`
  - `ConditionModifier` StrEnum: `PLUS="+"`, `MINUS="-"`
  - `SealedProductType` StrEnum: `BOOSTER_BOX="booster_box"`, `ETB="etb"`, `BUNDLE="bundle"`, `BOOSTER_PACK="booster_pack"`, `COLLECTION_BOX="collection_box"`, `OTHER="other"`
  - `ConsignmentTerms(consignor_id: str, split_percent: Decimal, minimum_price: Decimal|None, paid_out: bool=False)`
  - `_ItemBase` shared fields: `item_id: str` (default `new_ulid()`), `status: ItemStatus = AVAILABLE`, `location: str|None`, `cost_basis: Decimal`, `market_value_at_purchase: Decimal|None`, `current_market_value: Decimal|None`, `listed_price: Decimal|None`, `acquired_at: date`, `acquired_show_id: str|None`, `consignment: ConsignmentTerms|None`, `notes: str|None`, `tcg_url: str|None`, `needs_review: bool=False`. **`quantity` is removed.**
  - `RawInventoryItem(kind="raw", card_id: str|None, finish: str, condition: Condition, condition_modifier: ConditionModifier|None, factory_sealed: bool=False)`
  - `GradedInventoryItem(kind="graded", card_id: str|None, company: GradingCompany, grade: Decimal, cert_number: str)`
  - `SealedInventoryItem(kind="sealed", product_name: str, product_type: SealedProductType)`
  - `BulkInventoryItem(kind="bulk", description: str)`
  - `InventoryItem` / `InventoryItemAdapter` union over all four kinds; `EnrichedSealedInventoryItem` and `EnrichedBulkInventoryItem` added alongside the existing enriched raw/graded models, all in `EnrichedInventoryItem`.

- [ ] **Step 1: Add dependency**

In `backend/pyproject.toml` `dependencies`, add `"python-ulid>=2.2",` after the `mcp` line. Run `pip install -e backend[dev]` (or `pip install python-ulid`) so imports resolve.

- [ ] **Step 2: Write the failing tests**

Replace the item-construction tests in `backend/tests/models/test_inventory.py` (keep any enum tests that still apply) with:

```python
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from merlins_collection.models.inventory import (
    BulkInventoryItem,
    ConditionModifier,
    ConsignmentTerms,
    GradedInventoryItem,
    InventoryItemAdapter,
    ItemStatus,
    RawInventoryItem,
    SealedInventoryItem,
    SealedProductType,
)


def _base(**over):
    kw = dict(cost_basis=Decimal("10.00"), acquired_at=date(2026, 1, 5))
    kw.update(over)
    return kw


def test_raw_item_defaults_and_new_fields():
    item = RawInventoryItem(**_base(finish="holofoil", condition="LP",
                                    condition_modifier="+", factory_sealed=True))
    assert item.kind == "raw"
    assert item.card_id is None
    assert item.status is ItemStatus.AVAILABLE
    assert item.condition_modifier is ConditionModifier.PLUS
    assert item.factory_sealed is True
    assert item.listed_price is None
    assert item.consignment is None
    assert item.needs_review is False
    assert len(item.item_id) == 26  # ULID


def test_item_ids_are_unique():
    a = RawInventoryItem(**_base(finish="normal", condition="NM"))
    b = RawInventoryItem(**_base(finish="normal", condition="NM"))
    assert a.item_id != b.item_id


def test_sealed_and_bulk_kinds_round_trip_through_adapter():
    sealed = SealedInventoryItem(**_base(product_name="Evolving Skies Booster Box",
                                         product_type="booster_box"))
    bulk = BulkInventoryItem(**_base(description="5k common/uncommon lot"))
    assert sealed.product_type is SealedProductType.BOOSTER_BOX
    for item in (sealed, bulk):
        again = InventoryItemAdapter.validate_python(item.model_dump(mode="python"))
        assert again == item


def test_consignment_terms_attach_to_any_kind():
    terms = ConsignmentTerms(consignor_id="c-1", split_percent=Decimal("20"),
                             minimum_price=Decimal("50.00"))
    item = GradedInventoryItem(**_base(company="PSA", grade=Decimal("10"),
                                       cert_number="123", consignment=terms))
    assert item.consignment.paid_out is False
    assert item.consignment.split_percent == Decimal("20")


def test_quantity_field_is_gone():
    item = RawInventoryItem(**_base(finish="normal", condition="NM"))
    assert not hasattr(item, "quantity")


def test_invalid_condition_modifier_rejected():
    with pytest.raises(ValidationError):
        RawInventoryItem(**_base(finish="normal", condition="NM",
                                 condition_modifier="++"))
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest backend/tests/models/test_inventory.py -q`
Expected: FAIL (ImportError: `ItemStatus` etc. not defined).

- [ ] **Step 4: Implement the models**

In `backend/src/merlins_collection/models/inventory.py`: keep `Condition` and `GradingCompany`; replace `_ItemBase` and the union with:

```python
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, TypeAdapter
from ulid import ULID


def new_ulid() -> str:
    """Sortable 26-char unique id for items/transactions."""
    return str(ULID())


class ItemStatus(StrEnum):
    AVAILABLE = "available"
    ON_HOLD = "on_hold"
    SOLD = "sold"
    OUT_FOR_GRADING = "out_for_grading"
    LOST = "lost"
    RETURNED_TO_CONSIGNOR = "returned_to_consignor"


class ConditionModifier(StrEnum):
    PLUS = "+"
    MINUS = "-"


class SealedProductType(StrEnum):
    BOOSTER_BOX = "booster_box"
    ETB = "etb"
    BUNDLE = "bundle"
    BOOSTER_PACK = "booster_pack"
    COLLECTION_BOX = "collection_box"
    OTHER = "other"


class ConsignmentTerms(BaseModel):
    """Terms for an item we sell on someone else's behalf (we don't own it)."""

    consignor_id: str
    split_percent: Decimal  # our cut, 0-100
    minimum_price: Decimal | None = None
    paid_out: bool = False


class _ItemBase(BaseModel):
    """Fields shared by every inventory item. One record = one physical unit.

    ``cost_basis`` is internal purchase data and must never reach customers.
    ``current_market_value`` is denormalized by the daily sync (card-linked raw
    items) or maintained manually (graded/sealed).
    """

    item_id: str = Field(default_factory=new_ulid)
    status: ItemStatus = ItemStatus.AVAILABLE
    location: str | None = None
    cost_basis: Decimal
    market_value_at_purchase: Decimal | None = None
    current_market_value: Decimal | None = None
    listed_price: Decimal | None = None
    acquired_at: date
    acquired_show_id: str | None = None
    consignment: ConsignmentTerms | None = None
    notes: str | None = None
    tcg_url: str | None = None
    needs_review: bool = False


class RawInventoryItem(_ItemBase):
    """An ungraded single. ``factory_sealed`` = still in plastic wrap (promo premium)."""

    kind: Literal["raw"] = "raw"
    card_id: str | None = None
    finish: str
    condition: Condition
    condition_modifier: ConditionModifier | None = None
    factory_sealed: bool = False


class GradedInventoryItem(_ItemBase):
    """A slabbed card."""

    kind: Literal["graded"] = "graded"
    card_id: str | None = None
    company: GradingCompany
    grade: Decimal
    cert_number: str


class SealedInventoryItem(_ItemBase):
    """A sealed product (booster box, ETB, ...). No catalog link; manual value."""

    kind: Literal["sealed"] = "sealed"
    product_name: str
    product_type: SealedProductType


class BulkInventoryItem(_ItemBase):
    """A bulk lot sold as one unit; no per-card identity."""

    kind: Literal["bulk"] = "bulk"
    description: str


InventoryItem = Annotated[
    Union[RawInventoryItem, GradedInventoryItem, SealedInventoryItem, BulkInventoryItem],
    Field(discriminator="kind"),
]

InventoryItemAdapter: TypeAdapter[InventoryItem] = TypeAdapter(InventoryItem)
```

Keep `CardSummary` unchanged. Extend the enriched union:

```python
class EnrichedSealedInventoryItem(SealedInventoryItem):
    card: CardSummary | None = None


class EnrichedBulkInventoryItem(BulkInventoryItem):
    card: CardSummary | None = None


EnrichedInventoryItem = Annotated[
    Union[
        EnrichedRawInventoryItem,
        EnrichedGradedInventoryItem,
        EnrichedSealedInventoryItem,
        EnrichedBulkInventoryItem,
    ],
    Field(discriminator="kind"),
]
```

- [ ] **Step 5: Run the model tests**

Run: `python -m pytest backend/tests/models/test_inventory.py -q`
Expected: PASS.

- [ ] **Step 6: Mechanically fix dependent test fixtures**

The `quantity=` kwarg no longer exists and breaks other suites. In `backend/tests/services/test_dynamodb.py`, `backend/tests/services/test_catalog_sync.py`, `backend/tests/routers/test_inventory.py`, and `backend/tests/test_tool_contract.py`: delete every `quantity=...` argument from `RawInventoryItem(`/`GradedInventoryItem(` constructor calls (search for `quantity`), and delete any assertion on `.quantity`. Do not change anything else.

- [ ] **Step 7: Run the full suite**

Run: `python -m pytest backend/tests -q --tb=short`
Expected: PASS (the repository still keys raw/graded items by `card_id`; fixtures all pass `card_id`, so nothing else breaks yet).

- [ ] **Step 8: Commit**

```bash
git add backend
git commit -m "feat: reshape inventory models — item_id identity, status/location, sealed+bulk kinds"
```

---

### Task 2: Business domain models (`models/business.py`)

**Files:**
- Create: `backend/src/merlins_collection/models/business.py`
- Test: `backend/tests/models/test_business.py`

**Interfaces:**
- Consumes: `new_ulid` from `models/inventory.py`.
- Produces:
  - `TransactionType` StrEnum: `SALE="sale"`, `PURCHASE="purchase"`
  - `ItemCategory` StrEnum: `RAW="raw"`, `GRADED="graded"`, `SEALED="sealed"`, `BULK="bulk"`, `CONSIGNMENT="consignment"`
  - `Transaction(txn_id: str = new_ulid(), type: TransactionType, item_id: str, category: ItemCategory, date: date, amount: Decimal, payment_method: str, fee: Decimal = 0, show_id: str|None, trade_id: str|None, consignor_payout: Decimal|None, notes: str|None)`
  - `Show(show_id: str = new_ulid(), name: str, date: date, sales_goal: Decimal|None, cash_at_start: Decimal|None, inventory_value_at_start: Decimal|None, notes: str|None)`
  - `Consignor(consignor_id: str = new_ulid(), name: str, contact: str|None, notes: str|None)`
  - `CashAccount(account: str, balance: Decimal, updated_at: datetime)`
  - `BuyingPolicy(product_type: str, cash_pct_min: Decimal|None, cash_pct_max: Decimal|None, trade_pct_min: Decimal|None, trade_pct_max: Decimal|None)`
  - `PaymentMethod(method: str, fee_percent: Decimal = 0, fee_fixed: Decimal = 0)` with method `fee_for(amount: Decimal) -> Decimal` (cents-quantized).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/models/test_business.py`:

```python
from datetime import date
from decimal import Decimal

from merlins_collection.models.business import (
    BuyingPolicy,
    CashAccount,
    Consignor,
    ItemCategory,
    PaymentMethod,
    Show,
    Transaction,
    TransactionType,
)


def test_transaction_defaults():
    txn = Transaction(type="sale", item_id="i-1", category="raw",
                      date=date(2026, 3, 1), amount=Decimal("40.00"),
                      payment_method="venmo")
    assert txn.type is TransactionType.SALE
    assert txn.category is ItemCategory.RAW
    assert txn.fee == Decimal("0")
    assert txn.show_id is None and txn.trade_id is None
    assert txn.consignor_payout is None
    assert len(txn.txn_id) == 26


def test_payment_method_fee_percent_plus_fixed_quantized_to_cents():
    venmo = PaymentMethod(method="venmo", fee_percent=Decimal("1.9"),
                          fee_fixed=Decimal("0.10"))
    # 1.9% of 40.00 = 0.76, + 0.10 = 0.86
    assert venmo.fee_for(Decimal("40.00")) == Decimal("0.86")
    # 1.9% of 33.33 = 0.633... -> rounds half-up to 0.63, + 0.10
    assert venmo.fee_for(Decimal("33.33")) == Decimal("0.73")
    cash = PaymentMethod(method="cash")
    assert cash.fee_for(Decimal("100")) == Decimal("0.00")


def test_show_consignor_config_models_construct():
    show = Show(name="Mint City Show", date=date(2026, 4, 12),
                sales_goal=Decimal("500"), cash_at_start=Decimal("200"))
    assert len(show.show_id) == 26
    consignor = Consignor(name="David")
    assert len(consignor.consignor_id) == 26
    cash = CashAccount(account="venmo", balance=Decimal("321.50"))
    assert cash.updated_at is not None
    policy = BuyingPolicy(product_type="slabs", cash_pct_min=Decimal("60"),
                          cash_pct_max=Decimal("75"), trade_pct_min=Decimal("70"),
                          trade_pct_max=Decimal("85"))
    assert policy.trade_pct_max == Decimal("85")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest backend/tests/models/test_business.py -q`
Expected: FAIL (ModuleNotFoundError: `models.business`).

- [ ] **Step 3: Implement**

Create `backend/src/merlins_collection/models/business.py`:

```python
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
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest backend/tests/models/test_business.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/merlins_collection/models/business.py backend/tests/models/test_business.py
git commit -m "feat: add business models — transaction ledger, shows, consignors, config"
```

---

### Task 3: Re-key inventory items to `item_id` in the repository

**Files:**
- Modify: `backend/src/merlins_collection/services/dynamodb.py`
- Test: `backend/tests/services/test_dynamodb.py`

**Interfaces:**
- Consumes: the four item kinds + `InventoryItemAdapter` from Task 1.
- Produces (exact repository signatures later tasks and routers use):
  - `put_inventory_item(item: InventoryItem) -> None` — PK `INV#<crc-bucket of item_id>`, SK `ITEM#<item_id>`; GSI1 keys (`CARD#<card_id>` / `ITEM#<item_id>`) written **only when `card_id` is set**.
  - `get_inventory_item(item_id: str) -> InventoryItem | None` (**signature changed**: takes the id string, not a model)
  - `delete_inventory_item(item_id: str) -> None`
  - `list_inventory() -> list[InventoryItem]` (unchanged shape)
  - `list_inventory_for_card(card_id) -> list[InventoryItem]` (GSI1, unchanged signature)
  - module fn `_bucket(key: str) -> int` (unchanged, now fed `item_id`)

- [ ] **Step 1: Rewrite the inventory-section tests**

In `backend/tests/services/test_dynamodb.py`, replace the inventory tests (leave catalog/price tests alone) with tests using the new identity. Use/adapt the file's existing item-builder helpers:

```python
def _raw_item(**over):
    kw = dict(card_id="xy1-1", finish="holofoil", condition="NM",
              cost_basis=Decimal("5.00"), listed_price=Decimal("12.00"),
              acquired_at=date(2026, 1, 5))
    kw.update(over)
    return RawInventoryItem(**kw)


def test_inventory_item_round_trip_by_item_id(dynamo_repo):
    item = _raw_item()
    dynamo_repo.put_inventory_item(item)
    assert dynamo_repo.get_inventory_item(item.item_id) == item
    dynamo_repo.delete_inventory_item(item.item_id)
    assert dynamo_repo.get_inventory_item(item.item_id) is None


def test_sealed_and_bulk_items_store_without_card_id(dynamo_repo):
    sealed = SealedInventoryItem(product_name="ES Booster Box", product_type="booster_box",
                                 cost_basis=Decimal("400"), acquired_at=date(2026, 1, 5))
    bulk = BulkInventoryItem(description="bulk lot", cost_basis=Decimal("20"),
                             acquired_at=date(2026, 1, 5))
    dynamo_repo.put_inventory_item(sealed)
    dynamo_repo.put_inventory_item(bulk)
    kinds = {i.kind for i in dynamo_repo.list_inventory()}
    assert kinds == {"sealed", "bulk"}


def test_two_identical_cards_are_distinct_items(dynamo_repo):
    a, b = _raw_item(), _raw_item()  # same card/finish/condition, different item_id
    dynamo_repo.put_inventory_item(a)
    dynamo_repo.put_inventory_item(b)
    assert len(dynamo_repo.list_inventory()) == 2


def test_list_inventory_for_card_only_returns_card_linked_items(dynamo_repo):
    dynamo_repo.put_inventory_item(_raw_item(card_id="xy1-1"))
    dynamo_repo.put_inventory_item(_raw_item(card_id="xy1-2"))
    dynamo_repo.put_inventory_item(_raw_item(card_id=None))
    found = dynamo_repo.list_inventory_for_card("xy1-1")
    assert [i.card_id for i in found] == ["xy1-1"]
```

Also update every *other* test in the file that calls `get_inventory_item(item)` / `delete_inventory_item(item)` to pass `item.item_id`, and keep the existing sharding/pagination tests but feed `_bucket` with item ids.

- [ ] **Step 2: Run to verify failures**

Run: `python -m pytest backend/tests/services/test_dynamodb.py -q`
Expected: FAIL (old key composition raises on `card_id=None`, `get_inventory_item` signature mismatch).

- [ ] **Step 3: Implement the re-key**

In `services/dynamodb.py`, replace `_inventory_keys` and the four item methods:

```python
    # ---- inventory (keyed by item_id; card link is a sparse GSI1) ----
    def put_inventory_item(self, item):
        """Insert or overwrite one inventory item (one physical unit)."""
        body = _serialize(item.model_dump(mode="python"))
        record = {
            "PK": f"INV#{_bucket(item.item_id)}",
            "SK": f"ITEM#{item.item_id}",
            "entity": "inventory_item",
            **body,
        }
        card_id = getattr(item, "card_id", None)
        if card_id:
            record["GSI1PK"] = f"CARD#{card_id}"
            record["GSI1SK"] = f"ITEM#{item.item_id}"
        self._table.put_item(Item=record)

    def get_inventory_item(self, item_id: str):
        """Fetch one item by id, or ``None`` if absent."""
        found = self._table.get_item(
            Key={"PK": f"INV#{_bucket(item_id)}", "SK": f"ITEM#{item_id}"}
        ).get("Item")
        return InventoryItemAdapter.validate_python(found) if found else None

    def delete_inventory_item(self, item_id: str):
        """Delete one item by id."""
        self._table.delete_item(
            Key={"PK": f"INV#{_bucket(item_id)}", "SK": f"ITEM#{item_id}"}
        )
```

`list_inventory` is unchanged. `list_inventory_for_card` changes only its `begins_with` prefix from `"INV#"` to `"ITEM#"`. Update the module docstring key table (`inventory_item` → `INV#<shard>` / `ITEM#<item_id>`).

- [ ] **Step 4: Run the full suite; fix ripple**

Run: `python -m pytest backend/tests -q --tb=short`
Expected: `test_dynamodb.py` passes. If `routers/test_inventory.py` or `test_catalog_sync.py` call `get_inventory_item(item)`/`delete_inventory_item(item)` with a model, change those call sites (test and src — `catalog_sync.py` uses only `put_inventory_item`, which is unchanged) to pass `item.item_id`. Re-run until green.

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "feat: re-key inventory on item_id; sealed/bulk items storable"
```

---

### Task 4: Repository — shows, consignors, config entities

**Files:**
- Modify: `backend/src/merlins_collection/services/dynamodb.py`
- Test: `backend/tests/services/test_dynamodb.py`

**Interfaces:**
- Consumes: `Show`, `Consignor`, `CashAccount`, `BuyingPolicy`, `PaymentMethod` from Task 2.
- Produces:
  - `put_show(show: Show) -> None` / `list_shows() -> list[Show]` (chronological) / `get_show(show_id) -> Show | None`
  - `put_consignor(c: Consignor) -> None` / `list_consignors() -> list[Consignor]`
  - `put_cash_account(a: CashAccount) -> None` / `list_cash_accounts() -> list[CashAccount]`
  - `put_buying_policy(p: BuyingPolicy) -> None` / `list_buying_policies() -> list[BuyingPolicy]`
  - `put_payment_method(m: PaymentMethod) -> None` / `get_payment_method(method: str) -> PaymentMethod | None` / `list_payment_methods() -> list[PaymentMethod]`
- Key layout (§3 of spec): shows `SHOWLIST` / `SHOW#<iso-date>#<show_id>`; consignors `CONSIGNORLIST` / `CONSIGNOR#<id>`; config `CONFIG` / `CASH#<account>` | `BUYPOLICY#<product_type>` | `PAYMETHOD#<method>`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/services/test_dynamodb.py`:

```python
def test_shows_round_trip_chronological(dynamo_repo):
    later = Show(name="B Show", date=date(2026, 5, 2))
    earlier = Show(name="A Show", date=date(2026, 4, 4))
    dynamo_repo.put_show(later)
    dynamo_repo.put_show(earlier)
    names = [s.name for s in dynamo_repo.list_shows()]
    assert names == ["A Show", "B Show"]  # SK sorts by date
    assert dynamo_repo.get_show(later.show_id) == later
    assert dynamo_repo.get_show("nope") is None


def test_consignors_round_trip(dynamo_repo):
    c = Consignor(name="David", contact="555-1234")
    dynamo_repo.put_consignor(c)
    assert dynamo_repo.list_consignors() == [c]


def test_config_entities_round_trip(dynamo_repo):
    dynamo_repo.put_cash_account(CashAccount(account="venmo", balance=Decimal("100")))
    dynamo_repo.put_buying_policy(BuyingPolicy(product_type="slabs",
                                               cash_pct_min=Decimal("60")))
    venmo = PaymentMethod(method="venmo", fee_percent=Decimal("1.9"),
                          fee_fixed=Decimal("0.10"))
    dynamo_repo.put_payment_method(venmo)
    assert dynamo_repo.list_cash_accounts()[0].balance == Decimal("100")
    assert dynamo_repo.list_buying_policies()[0].product_type == "slabs"
    assert dynamo_repo.get_payment_method("venmo") == venmo
    assert dynamo_repo.get_payment_method("zelle") is None
    assert [m.method for m in dynamo_repo.list_payment_methods()] == ["venmo"]
```

(Import the new models at the top of the test file.)

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest backend/tests/services/test_dynamodb.py -q -k "shows or consignors or config"`
Expected: FAIL (AttributeError: no `put_show`).

- [ ] **Step 3: Implement**

Append to `InventoryRepository` (import the business models at the top):

```python
    # ---- shows ----
    def put_show(self, show: Show):
        body = _serialize(show.model_dump(mode="python"))
        self._table.put_item(Item={
            "PK": "SHOWLIST",
            "SK": f"SHOW#{show.date.isoformat()}#{show.show_id}",
            "entity": "show", **body,
        })

    def list_shows(self):
        items = self._query_all(KeyConditionExpression=Key("PK").eq("SHOWLIST"))
        return [Show.model_validate(i) for i in items]

    def get_show(self, show_id: str):
        # SK embeds the date, so a point-read needs it; the show list is tiny.
        return next((s for s in self.list_shows() if s.show_id == show_id), None)

    # ---- consignors ----
    def put_consignor(self, consignor: Consignor):
        body = _serialize(consignor.model_dump(mode="python"))
        self._table.put_item(Item={
            "PK": "CONSIGNORLIST",
            "SK": f"CONSIGNOR#{consignor.consignor_id}",
            "entity": "consignor", **body,
        })

    def list_consignors(self):
        items = self._query_all(KeyConditionExpression=Key("PK").eq("CONSIGNORLIST"))
        return [Consignor.model_validate(i) for i in items]

    # ---- config entities (CONFIG partition) ----
    def _put_config(self, sk: str, entity: str, model):
        body = _serialize(model.model_dump(mode="python"))
        self._table.put_item(Item={"PK": "CONFIG", "SK": sk, "entity": entity, **body})

    def _list_config(self, prefix: str, model_cls):
        items = self._query_all(
            KeyConditionExpression=Key("PK").eq("CONFIG") & Key("SK").begins_with(prefix)
        )
        return [model_cls.model_validate(i) for i in items]

    def put_cash_account(self, account: CashAccount):
        self._put_config(f"CASH#{account.account}", "cash_account", account)

    def list_cash_accounts(self):
        return self._list_config("CASH#", CashAccount)

    def put_buying_policy(self, policy: BuyingPolicy):
        self._put_config(f"BUYPOLICY#{policy.product_type}", "buying_policy", policy)

    def list_buying_policies(self):
        return self._list_config("BUYPOLICY#", BuyingPolicy)

    def put_payment_method(self, method: PaymentMethod):
        self._put_config(f"PAYMETHOD#{method.method}", "payment_method", method)

    def get_payment_method(self, method: str):
        item = self._table.get_item(
            Key={"PK": "CONFIG", "SK": f"PAYMETHOD#{method}"}
        ).get("Item")
        return PaymentMethod.model_validate(item) if item else None

    def list_payment_methods(self):
        return self._list_config("PAYMETHOD#", PaymentMethod)
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest backend/tests/services/test_dynamodb.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "feat: repository support for shows, consignors, and config entities"
```

---

### Task 5: Repository — transaction ledger + GSI2

**Files:**
- Modify: `backend/src/merlins_collection/services/dynamodb.py` (`create_table` gains GSI2; new txn methods)
- Test: `backend/tests/services/test_dynamodb.py`

**Interfaces:**
- Consumes: `Transaction` from Task 2.
- Produces:
  - `put_transaction(txn: Transaction) -> None` — PK `TXN#<YYYY-MM>`, SK `<iso-date>#<txn_id>`; sparse GSI2 (`GSI2PK=SHOW#<show_id>`, `GSI2SK=<iso-date>#<txn_id>`) only when `show_id` set.
  - `list_transactions(start: date, end: date) -> list[Transaction]` — queries each month partition in the range with SK `between`.
  - `list_transactions_for_show(show_id: str) -> list[Transaction]` — GSI2 query.
- **Note for prod infra:** the real table needs GSI2 added (infra change, out of code scope; `create_table` here covers tests/local dev).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/services/test_dynamodb.py`:

```python
def _txn(**over):
    kw = dict(type="sale", item_id="i-1", category="raw", date=date(2026, 3, 10),
              amount=Decimal("40.00"), payment_method="cash")
    kw.update(over)
    return Transaction(**kw)


def test_transactions_query_by_date_range_across_months(dynamo_repo):
    feb = _txn(date=date(2026, 2, 27))
    mar = _txn(date=date(2026, 3, 5))
    apr = _txn(date=date(2026, 4, 1))
    for t in (feb, mar, apr):
        dynamo_repo.put_transaction(t)
    found = dynamo_repo.list_transactions(date(2026, 2, 1), date(2026, 3, 31))
    assert sorted(t.txn_id for t in found) == sorted([feb.txn_id, mar.txn_id])
    # sub-month range bounds within the partition
    found = dynamo_repo.list_transactions(date(2026, 3, 1), date(2026, 3, 4))
    assert found == []


def test_transactions_query_by_show(dynamo_repo):
    at_show = _txn(show_id="show-1")
    off_show = _txn()
    dynamo_repo.put_transaction(at_show)
    dynamo_repo.put_transaction(off_show)
    found = dynamo_repo.list_transactions_for_show("show-1")
    assert [t.txn_id for t in found] == [at_show.txn_id]
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest backend/tests/services/test_dynamodb.py -q -k transactions`
Expected: FAIL (no `put_transaction`).

- [ ] **Step 3: Implement**

In `create_table`, add to `AttributeDefinitions`: `{"AttributeName": "GSI2PK", "AttributeType": "S"}, {"AttributeName": "GSI2SK", "AttributeType": "S"}`; add a second entry to `GlobalSecondaryIndexes`:

```python
                {
                    "IndexName": "GSI2",
                    "KeySchema": [
                        {"AttributeName": "GSI2PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI2SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
```

Append the methods:

```python
    # ---- transaction ledger ----
    @staticmethod
    def _txn_keys(txn: Transaction) -> dict:
        keys = {
            "PK": f"TXN#{txn.date.strftime('%Y-%m')}",
            "SK": f"{txn.date.isoformat()}#{txn.txn_id}",
        }
        if txn.show_id:
            keys["GSI2PK"] = f"SHOW#{txn.show_id}"
            keys["GSI2SK"] = f"{txn.date.isoformat()}#{txn.txn_id}"
        return keys

    def put_transaction(self, txn: Transaction):
        """Append one ledger record (purchase or sale)."""
        body = _serialize(txn.model_dump(mode="python"))
        self._table.put_item(Item={**self._txn_keys(txn), "entity": "transaction", **body})

    def list_transactions(self, start: date, end: date):
        """All ledger records with start <= date <= end (month-partition walk)."""
        results = []
        year, month = start.year, start.month
        while (year, month) <= (end.year, end.month):
            results.extend(self._query_all(
                KeyConditionExpression=Key("PK").eq(f"TXN#{year:04d}-{month:02d}")
                & Key("SK").between(start.isoformat(), end.isoformat() + "#~"),
            ))
            month += 1
            if month == 13:
                year, month = year + 1, 1
        return [Transaction.model_validate(i) for i in results]

    def list_transactions_for_show(self, show_id: str):
        items = self._query_all(
            IndexName="GSI2",
            KeyConditionExpression=Key("GSI2PK").eq(f"SHOW#{show_id}"),
        )
        return [Transaction.model_validate(i) for i in items]
```

(`"#~"` suffix: `~` sorts after every txn-id character, making the `between` upper bound inclusive of the end date.)

- [ ] **Step 4: Run tests**

Run: `python -m pytest backend/tests/services/test_dynamodb.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "feat: transaction ledger — month partitions + show GSI2"
```

---

### Task 6: Atomic sale flow

**Files:**
- Create: `backend/src/merlins_collection/services/sales.py`
- Modify: `backend/src/merlins_collection/services/dynamodb.py` (add `record_sale`, `ItemAlreadySoldError`)
- Test: `backend/tests/services/test_sales.py`

**Interfaces:**
- Consumes: `Transaction`, `PaymentMethod`, item kinds, repository from earlier tasks.
- Produces:
  - `dynamodb.ItemAlreadySoldError(Exception)`
  - `InventoryRepository.record_sale(txn: Transaction) -> None` — atomic `TransactWriteItems`: put the sale txn + set the item's `status` to `sold`, condition-guarded so a sold/missing item raises `ItemAlreadySoldError`.
  - `sales.build_sale_transaction(item: InventoryItem, *, amount: Decimal, method: PaymentMethod, sale_date: date, show_id: str|None = None, trade_id: str|None = None) -> Transaction` — sets `category` (item's kind, or `consignment` when the item has consignment terms), `fee = method.fee_for(amount)`, and `consignor_payout` (`amount - our split`, cents-quantized) for consigned items.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/services/test_sales.py`:

```python
from datetime import date
from decimal import Decimal

import pytest

from merlins_collection.models.business import PaymentMethod
from merlins_collection.models.inventory import (
    ConsignmentTerms,
    ItemStatus,
    RawInventoryItem,
)
from merlins_collection.services.dynamodb import ItemAlreadySoldError
from merlins_collection.services.sales import build_sale_transaction

VENMO = PaymentMethod(method="venmo", fee_percent=Decimal("1.9"), fee_fixed=Decimal("0.10"))
CASH = PaymentMethod(method="cash")


def _item(**over):
    kw = dict(card_id="xy1-1", finish="normal", condition="NM",
              cost_basis=Decimal("10.00"), acquired_at=date(2026, 1, 5))
    kw.update(over)
    return RawInventoryItem(**kw)


def test_build_sale_computes_fee_and_category():
    item = _item()
    txn = build_sale_transaction(item, amount=Decimal("40.00"), method=VENMO,
                                 sale_date=date(2026, 3, 10), show_id="show-1")
    assert txn.type == "sale"
    assert txn.item_id == item.item_id
    assert txn.category == "raw"
    assert txn.fee == Decimal("0.86")
    assert txn.show_id == "show-1"
    assert txn.consignor_payout is None


def test_build_sale_for_consigned_item_computes_payout():
    terms = ConsignmentTerms(consignor_id="c-1", split_percent=Decimal("20"))
    item = _item(consignment=terms)
    txn = build_sale_transaction(item, amount=Decimal("100.00"), method=CASH,
                                 sale_date=date(2026, 3, 10))
    assert txn.category == "consignment"
    assert txn.consignor_payout == Decimal("80.00")  # consignor gets 100 - our 20%


def test_record_sale_is_atomic_and_flips_status(dynamo_repo):
    item = _item()
    dynamo_repo.put_inventory_item(item)
    txn = build_sale_transaction(item, amount=Decimal("40.00"), method=CASH,
                                 sale_date=date(2026, 3, 10))
    dynamo_repo.record_sale(txn)
    assert dynamo_repo.get_inventory_item(item.item_id).status is ItemStatus.SOLD
    assert dynamo_repo.list_transactions(date(2026, 3, 1), date(2026, 3, 31)) == [txn]


def test_record_sale_rejects_double_sell(dynamo_repo):
    item = _item()
    dynamo_repo.put_inventory_item(item)
    txn = build_sale_transaction(item, amount=Decimal("40.00"), method=CASH,
                                 sale_date=date(2026, 3, 10))
    dynamo_repo.record_sale(txn)
    with pytest.raises(ItemAlreadySoldError):
        dynamo_repo.record_sale(build_sale_transaction(
            item, amount=Decimal("45.00"), method=CASH, sale_date=date(2026, 3, 11)))


def test_record_sale_rejects_missing_item(dynamo_repo):
    txn = build_sale_transaction(_item(), amount=Decimal("40.00"), method=CASH,
                                 sale_date=date(2026, 3, 10))
    with pytest.raises(ItemAlreadySoldError):
        dynamo_repo.record_sale(txn)
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest backend/tests/services/test_sales.py -q`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement `record_sale` in the repository**

In `services/dynamodb.py` add at module level:

```python
class ItemAlreadySoldError(Exception):
    """The sale's target item is already sold (or doesn't exist)."""
```

and in `InventoryRepository` (uses the low-level client — `TransactWriteItems` needs marshalled values, so serialize via `boto3.dynamodb.types.TypeSerializer`; add `from boto3.dynamodb.types import TypeSerializer` and `from botocore.exceptions import ClientError` to imports):

```python
    def record_sale(self, txn: Transaction):
        """Atomically append the sale txn and flip its item to ``sold``.

        Condition-guarded: if the item is missing or already sold, nothing is
        written and ``ItemAlreadySoldError`` is raised.
        """
        ser = TypeSerializer()
        txn_item = {**self._txn_keys(txn), "entity": "transaction",
                    **_serialize(txn.model_dump(mode="python"))}
        try:
            self._resource.meta.client.transact_write_items(TransactItems=[
                {"Put": {
                    "TableName": self._table_name,
                    "Item": {k: ser.serialize(v) for k, v in txn_item.items()},
                }},
                {"Update": {
                    "TableName": self._table_name,
                    "Key": {
                        "PK": {"S": f"INV#{_bucket(txn.item_id)}"},
                        "SK": {"S": f"ITEM#{txn.item_id}"},
                    },
                    "UpdateExpression": "SET #status = :sold",
                    "ConditionExpression":
                        "attribute_exists(PK) AND #status <> :sold",
                    "ExpressionAttributeNames": {"#status": "status"},
                    "ExpressionAttributeValues": {":sold": {"S": "sold"}},
                }},
            ])
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "TransactionCanceledException":
                raise ItemAlreadySoldError(txn.item_id) from exc
            raise
```

- [ ] **Step 4: Implement `build_sale_transaction`**

Create `backend/src/merlins_collection/services/sales.py`:

```python
"""Sale construction: fee + consignor-payout math for the transaction ledger."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from merlins_collection.models.business import (
    ItemCategory,
    PaymentMethod,
    Transaction,
    TransactionType,
)
from merlins_collection.models.inventory import InventoryItem


def build_sale_transaction(
    item: InventoryItem,
    *,
    amount: Decimal,
    method: PaymentMethod,
    sale_date: date,
    show_id: str | None = None,
    trade_id: str | None = None,
) -> Transaction:
    """Build (not persist) the ledger record for selling ``item``.

    Consigned items are categorized ``consignment`` and carry the payout the
    consignor is owed: the gross minus our ``split_percent`` cut.
    """
    if item.consignment is not None:
        category = ItemCategory.CONSIGNMENT
        our_cut = (amount * item.consignment.split_percent / Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        payout = amount - our_cut
    else:
        category = ItemCategory(item.kind)
        payout = None
    return Transaction(
        type=TransactionType.SALE,
        item_id=item.item_id,
        category=category,
        date=sale_date,
        amount=amount,
        payment_method=method.method,
        fee=method.fee_for(amount),
        show_id=show_id,
        trade_id=trade_id,
        consignor_payout=payout,
    )
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest backend/tests/services/test_sales.py backend/tests/services/test_dynamodb.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend
git commit -m "feat: atomic sale flow — record_sale transact + fee/payout builder"
```

---

### Task 7: Update `/inventory/search` (contract-preserving)

**Files:**
- Modify: `backend/src/merlins_collection/routers/inventory.py`
- Test: `backend/tests/routers/test_inventory.py`

**Interfaces:**
- Consumes: new item model; existing `repo.list_inventory()`, `repo.batch_get_catalog_cards()`.
- Produces: same endpoint, same params (`name, set_id, rarity, condition, min_price, max_price`), same response shape. New semantics:
  - Only `status == available` items of kinds `raw|graded|sealed` returned (bulk and non-available always excluded).
  - Price filters compare against `listed_price`, falling back to `current_market_value`; items with neither are excluded when a price filter is set.
  - `condition=LP` matches modifier variants (modifier is a separate field, so the existing equality already does — a test locks it in).
  - Response strips `cost_basis`, `consignment`, and `needs_review`.
  - `_enrich` handles all four kinds (sealed/bulk get `card=None`); `_load_catalog` skips `card_id is None`.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/routers/test_inventory.py` (reuse the file's existing auth/repo fixtures and item builders; adapt builder defaults to the Task 1 model):

```python
def test_search_excludes_bulk_and_non_available_items(inventory_client, seeded_repo):
    seeded_repo.put_inventory_item(_raw(status="sold"))
    seeded_repo.put_inventory_item(_raw(status="on_hold"))
    seeded_repo.put_inventory_item(BulkInventoryItem(
        description="lot", cost_basis=Decimal("5"), acquired_at=date(2026, 1, 1)))
    available = _raw()
    seeded_repo.put_inventory_item(available)
    body = inventory_client.get("/inventory/search").json()
    assert [i["item_id"] for i in body["items"]] == [available.item_id]


def test_search_returns_sealed_products_with_null_card(inventory_client, seeded_repo):
    sealed = SealedInventoryItem(product_name="ES Booster Box", product_type="booster_box",
                                 cost_basis=Decimal("400"), listed_price=Decimal("550"),
                                 acquired_at=date(2026, 1, 1))
    seeded_repo.put_inventory_item(sealed)
    body = inventory_client.get("/inventory/search").json()
    match = next(i for i in body["items"] if i["kind"] == "sealed")
    assert match["product_name"] == "ES Booster Box"
    assert match["card"] is None


def test_condition_filter_matches_modifier_variants(inventory_client, seeded_repo):
    seeded_repo.put_inventory_item(_raw(condition="LP", condition_modifier="+"))
    seeded_repo.put_inventory_item(_raw(condition="LP", condition_modifier="-"))
    seeded_repo.put_inventory_item(_raw(condition="NM"))
    body = inventory_client.get("/inventory/search?condition=LP").json()
    assert body["total"] == 2


def test_price_filter_falls_back_to_market_value(inventory_client, seeded_repo):
    seeded_repo.put_inventory_item(_raw(listed_price=Decimal("30")))
    seeded_repo.put_inventory_item(_raw(listed_price=None,
                                        current_market_value=Decimal("80")))
    seeded_repo.put_inventory_item(_raw(listed_price=None, current_market_value=None))
    body = inventory_client.get("/inventory/search?min_price=50").json()
    assert body["total"] == 1


def test_response_strips_internal_fields(inventory_client, seeded_repo):
    terms = ConsignmentTerms(consignor_id="c-1", split_percent=Decimal("20"))
    seeded_repo.put_inventory_item(_raw(consignment=terms, needs_review=True))
    item = inventory_client.get("/inventory/search").json()["items"][0]
    assert "cost_basis" not in item
    assert "consignment" not in item
    assert "needs_review" not in item
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest backend/tests/routers/test_inventory.py -q`
Expected: new tests FAIL (bulk items visible, consignment leaks, etc.).

- [ ] **Step 3: Implement**

In `routers/inventory.py`:

1. Extend `response_model_exclude` to `{"items": {"__all__": {"cost_basis", "consignment", "needs_review"}}}`.
2. After `items = repo.list_inventory()`, add visibility filtering:

```python
    CUSTOMER_KINDS = {"raw", "graded", "sealed"}
    items = [
        i for i in items
        if i.kind in CUSTOMER_KINDS and i.status == ItemStatus.AVAILABLE
    ]
```

3. Replace the price filters with a fallback helper:

```python
def _price(item) -> Decimal | None:
    return item.listed_price if item.listed_price is not None else item.current_market_value
```

```python
    if min_price is not None:
        items = [i for i in items if _price(i) is not None and _price(i) >= min_price]
    if max_price is not None:
        items = [i for i in items if _price(i) is not None and _price(i) <= max_price]
```

4. Card-dependent filters must not crash on `card_id=None`: in `_load_catalog`, build `missing` from `{i.card_id for i in items if getattr(i, "card_id", None)}`; in the set/name/rarity filters use `getattr(i, "card_id", None)` as the lookup key (sealed items simply never match card filters).
5. `_enrich` dispatches on kind:

```python
_ENRICHED = {
    "raw": EnrichedRawInventoryItem,
    "graded": EnrichedGradedInventoryItem,
    "sealed": EnrichedSealedInventoryItem,
    "bulk": EnrichedBulkInventoryItem,
}


def _enrich(item, card):
    summary = CardSummary.from_catalog(card) if card is not None else None
    return _ENRICHED[item.kind](**item.model_dump(), card=summary)
```

(Import `ItemStatus` and the new enriched classes.)

- [ ] **Step 4: Run the router suite, then the full suite**

Run: `python -m pytest backend/tests/routers/test_inventory.py -q` then `python -m pytest backend/tests -q --tb=short`
Expected: PASS (existing contract tests untouched and green).

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "feat: search visibility rules for new item model (contract preserved)"
```

---

### Task 8: Catalog-sync adjustments + sealed price snapshots

**Files:**
- Modify: `backend/src/merlins_collection/services/catalog_sync.py`
- Modify: `backend/src/merlins_collection/services/dynamodb.py` (item-level price points)
- Test: `backend/tests/services/test_catalog_sync.py`, `backend/tests/services/test_dynamodb.py`

**Interfaces:**
- Produces:
  - `InventoryRepository.append_item_price_point(item_id: str, day: date, value: Decimal) -> None` — item `{"PK": f"ITEM#{item_id}", "SK": f"PRICE#{day.isoformat()}", "entity": "item_price_point", "item_id", "date", "market_value"}`.
  - `InventoryRepository.get_item_price_history(item_id: str) -> list[dict]` (raw dicts, date-sorted by SK).
  - `catalog_sync.snapshot_sealed_prices(repo, today: date) -> dict` — one point per sealed item with a `current_market_value`; wired into `run_daily_sync`.
  - `refresh_inventory_market_values` and `snapshot_graded_prices` skip items with `card_id is None`.

- [ ] **Step 1: Write the failing tests**

In `test_dynamodb.py`:

```python
def test_item_price_points_round_trip_sorted(dynamo_repo):
    dynamo_repo.append_item_price_point("item-1", date(2026, 3, 2), Decimal("410"))
    dynamo_repo.append_item_price_point("item-1", date(2026, 3, 1), Decimal("400"))
    history = dynamo_repo.get_item_price_history("item-1")
    assert [h["market_value"] for h in history] == [Decimal("400"), Decimal("410")]
```

In `test_catalog_sync.py`:

```python
def test_sync_skips_unlinked_items_and_snapshots_sealed(dynamo_repo):
    unlinked = RawInventoryItem(card_id=None, finish="normal", condition="NM",
                                cost_basis=Decimal("1"), acquired_at=date(2026, 1, 1))
    sealed = SealedInventoryItem(product_name="Box", product_type="booster_box",
                                 cost_basis=Decimal("400"),
                                 current_market_value=Decimal("500"),
                                 acquired_at=date(2026, 1, 1))
    dynamo_repo.put_inventory_item(unlinked)
    dynamo_repo.put_inventory_item(sealed)
    # must not raise on card_id=None:
    assert refresh_inventory_market_values(dynamo_repo) == 0
    summary = snapshot_sealed_prices(dynamo_repo, date(2026, 3, 1))
    assert summary == {"sealed_points_written": 1}
    assert len(dynamo_repo.get_item_price_history(sealed.item_id)) == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest backend/tests/services/test_catalog_sync.py backend/tests/services/test_dynamodb.py -q -k "sealed or item_price"`
Expected: FAIL.

- [ ] **Step 3: Implement**

Repository:

```python
    # ---- per-item price history (sealed/bulk have no card to hang history on) ----
    def append_item_price_point(self, item_id: str, day: date, value: Decimal):
        self._table.put_item(Item={
            "PK": f"ITEM#{item_id}", "SK": f"PRICE#{day.isoformat()}",
            "entity": "item_price_point", "item_id": item_id,
            "date": day.isoformat(), "market_value": value,
        })

    def get_item_price_history(self, item_id: str):
        return self._query_all(
            KeyConditionExpression=Key("PK").eq(f"ITEM#{item_id}")
            & Key("SK").begins_with("PRICE#")
        )
```

`catalog_sync.py`:
- In `snapshot_graded_prices` and `refresh_inventory_market_values`, guard the top of each loop body: `if getattr(item, "card_id", None) is None: continue` (in `refresh_...`, also `if item.kind not in ("raw", "graded"): continue`).
- Add:

```python
def snapshot_sealed_prices(repo, today: date) -> dict:
    """Append a daily history point for each sealed item with a market value."""
    written = 0
    for item in repo.list_inventory():
        if item.kind != "sealed" or item.current_market_value is None:
            continue
        repo.append_item_price_point(item.item_id, today, item.current_market_value)
        written += 1
    return {"sealed_points_written": written}
```

- In `run_daily_sync`, after the graded snapshot line: `summary.update(snapshot_sealed_prices(repo, today))`.

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest backend/tests -q --tb=short`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "feat: sync skips unlinked items; sealed items get daily price snapshots"
```

---

### Task 9: Importer core — parsing helpers + Singles tab

**Files:**
- Create: `backend/src/merlins_collection/services/spreadsheet_import.py`
- Test: `backend/tests/services/test_spreadsheet_import.py`

**Interfaces:**
- Consumes: repository + models from earlier tasks.
- Produces (later import tasks reuse these exact helpers):
  - `parse_money(text: str|None) -> Decimal|None` — handles `"$1,234.56"`, `"1234.56"`, `""`/`None`/`"-"` → `None`.
  - `parse_date(text: str|None) -> date|None` — `M/D/YYYY` and `YYYY-MM-DD`; blank → `None`.
  - `parse_bool(text: str|None) -> bool` — truthy: `yes/y/true/x/1` (case-insensitive).
  - `parse_condition(text: str) -> tuple[Condition, ConditionModifier|None]` — `"LP +"/"LP+"` → `(LP, PLUS)`, `"D"` → `(DMG, None)`, unknown raises `ValueError`.
  - `map_location(text: str|None) -> dict` — returns kwargs `{location, status, factory_sealed, notes_extra}` per the spec §5 table (`Glass`→location `glass`; `Toploader`→`toploader`; `Sealed`→`factory_sealed=True`; `Hold`→status `on_hold`; `Lost`→`lost`; `Grading`→`out_for_grading`; `For David`→status `on_hold` + notes_extra `"For David"`; unknown value → location as-is lowercased).
  - `deterministic_id(tab: str, row: dict) -> str` — 26-char sha1-hex prefix of `tab + "|" + json.dumps(row, sort_keys=True)`.
  - `ImportContext(repo, shows: list[Show], catalog_index: dict)` dataclass; `nearest_show_id(day: date, shows: list[Show]) -> str|None` (closest by absolute day distance; `None` if no shows).
  - `import_singles(rows: list[dict], ctx: ImportContext) -> dict` — one `RawInventoryItem` per row (+ sale `Transaction` when sold); returns `{"imported": n, "sales": n, "skipped": n, "needs_review": n}`.
- CSV headers for Singles (verbatim from the sheet): `Date, Location, Name, Card #, Condition, Market @ purchase, Amount Paid, Percent, Sold, Date Sold, Venmo?, Net, Sticker, Notes, TCG Link, # of Show days had, Venmo Fees`.

- [ ] **Step 1: Write the failing helper tests**

Create `backend/tests/services/test_spreadsheet_import.py`:

```python
from datetime import date
from decimal import Decimal

import pytest

from merlins_collection.models.business import Show
from merlins_collection.models.inventory import Condition, ConditionModifier
from merlins_collection.services.spreadsheet_import import (
    deterministic_id,
    map_location,
    nearest_show_id,
    parse_bool,
    parse_condition,
    parse_date,
    parse_money,
)


def test_parse_money():
    assert parse_money("$1,234.56") == Decimal("1234.56")
    assert parse_money("40") == Decimal("40")
    assert parse_money("") is None
    assert parse_money(None) is None
    assert parse_money("-") is None


def test_parse_date():
    assert parse_date("3/7/2026") == date(2026, 3, 7)
    assert parse_date("2026-03-07") == date(2026, 3, 7)
    assert parse_date("") is None


def test_parse_bool():
    assert parse_bool("Yes") and parse_bool("y") and parse_bool("TRUE") and parse_bool("x")
    assert not parse_bool("No") and not parse_bool("") and not parse_bool(None)


def test_parse_condition():
    assert parse_condition("LP +") == (Condition.LP, ConditionModifier.PLUS)
    assert parse_condition("LP-") == (Condition.LP, ConditionModifier.MINUS)
    assert parse_condition("NM") == (Condition.NM, None)
    assert parse_condition("D") == (Condition.DMG, None)
    with pytest.raises(ValueError):
        parse_condition("Mint-ish")


def test_map_location():
    assert map_location("Glass")["location"] == "glass"
    assert map_location("Sealed")["factory_sealed"] is True
    assert map_location("Hold")["status"] == "on_hold"
    assert map_location("Lost")["status"] == "lost"
    assert map_location("Grading")["status"] == "out_for_grading"
    fd = map_location("For David")
    assert fd["status"] == "on_hold" and fd["notes_extra"] == "For David"


def test_deterministic_id_stable_and_distinct():
    row = {"Name": "Pikachu", "Sold": "40"}
    assert deterministic_id("Singles", row) == deterministic_id("Singles", row)
    assert deterministic_id("Singles", row) != deterministic_id("Slabs", row)
    assert len(deterministic_id("Singles", row)) == 26


def test_nearest_show_id():
    shows = [Show(show_id="a", name="A", date=date(2026, 3, 1)),
             Show(show_id="b", name="B", date=date(2026, 3, 20))]
    assert nearest_show_id(date(2026, 3, 5), shows) == "a"
    assert nearest_show_id(date(2026, 3, 18), shows) == "b"
    assert nearest_show_id(date(2026, 3, 5), []) is None
```

- [ ] **Step 2: Run to verify failure, then implement the helpers**

Run: `python -m pytest backend/tests/services/test_spreadsheet_import.py -q` → ImportError. Then create `backend/src/merlins_collection/services/spreadsheet_import.py`:

```python
"""One-shot importer: spreadsheet CSV exports -> the DynamoDB schema.

Each tab has an ``import_<tab>`` function taking parsed CSV rows plus an
``ImportContext``. Ids are deterministic (tab + row content hash) so re-running
the import overwrites instead of duplicating. Ambiguity never guesses silently:
unmappable rows are skipped-and-counted, uncertain mappings set
``needs_review=True``.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from merlins_collection.models.business import (
    ItemCategory,
    Show,
    Transaction,
    TransactionType,
)
from merlins_collection.models.inventory import Condition, ConditionModifier

logger = logging.getLogger(__name__)


def parse_money(text) -> Decimal | None:
    if text is None:
        return None
    cleaned = str(text).strip().replace("$", "").replace(",", "")
    if cleaned in ("", "-"):
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def parse_date(text) -> date | None:
    if not text or not str(text).strip():
        return None
    cleaned = str(text).strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def parse_bool(text) -> bool:
    return str(text or "").strip().lower() in ("yes", "y", "true", "x", "1")


def parse_condition(text: str) -> tuple[Condition, ConditionModifier | None]:
    cleaned = str(text).strip().upper().replace(" ", "")
    modifier = None
    if cleaned.endswith("+"):
        modifier, cleaned = ConditionModifier.PLUS, cleaned[:-1]
    elif cleaned.endswith("-"):
        modifier, cleaned = ConditionModifier.MINUS, cleaned[:-1]
    if cleaned == "D":
        cleaned = "DMG"
    if cleaned not in Condition.__members__:
        raise ValueError(f"unknown condition: {text!r}")
    return Condition[cleaned], modifier


def map_location(text) -> dict:
    """Split the sheet's Location column into location/status/factory_sealed."""
    out = {"location": None, "status": "available", "factory_sealed": False,
           "notes_extra": None}
    cleaned = str(text or "").strip()
    if not cleaned:
        return out
    lowered = cleaned.lower()
    if lowered == "sealed":
        out["factory_sealed"] = True
    elif lowered == "hold":
        out["status"] = "on_hold"
    elif lowered == "lost":
        out["status"] = "lost"
    elif lowered == "grading":
        out["status"] = "out_for_grading"
    elif lowered == "for david":
        out["status"] = "on_hold"
        out["notes_extra"] = cleaned
    else:
        out["location"] = lowered
    return out


def deterministic_id(tab: str, row: dict) -> str:
    digest = hashlib.sha1(
        (tab + "|" + json.dumps(row, sort_keys=True, default=str)).encode("utf-8")
    ).hexdigest()
    return digest[:26]


def nearest_show_id(day: date, shows: list[Show]) -> str | None:
    if not shows:
        return None
    return min(shows, key=lambda s: abs((s.date - day).days)).show_id


@dataclass
class ImportContext:
    repo: object
    shows: list[Show] = field(default_factory=list)
    catalog_index: dict = field(default_factory=dict)  # (name_lower, number) -> [CatalogCard]
```

Run the helper tests: PASS.

- [ ] **Step 3: Write the failing `import_singles` test**

```python
def _singles_row(**over):
    row = {"Date": "1/5/2026", "Location": "Glass", "Name": "Pikachu", "Card #": "25",
           "Condition": "LP +", "Market @ purchase": "$12.00", "Amount Paid": "$8.00",
           "Percent": "", "Sold": "", "Date Sold": "", "Venmo?": "", "Net": "",
           "Sticker": "$15.00", "Notes": "", "TCG Link": "http://example.com/25",
           "# of Show days had": "", "Venmo Fees": ""}
    row.update(over)
    return row


def test_import_singles_unsold_row(dynamo_repo):
    ctx = ImportContext(repo=dynamo_repo)
    summary = import_singles([_singles_row()], ctx)
    assert summary == {"imported": 1, "sales": 0, "skipped": 0, "needs_review": 1}
    [item] = dynamo_repo.list_inventory()
    assert item.kind == "raw"
    assert item.condition is Condition.LP
    assert item.condition_modifier is ConditionModifier.PLUS
    assert item.location == "glass"
    assert item.cost_basis == Decimal("8.00")
    assert item.market_value_at_purchase == Decimal("12.00")
    assert item.listed_price == Decimal("15.00")
    assert item.tcg_url == "http://example.com/25"
    assert item.card_id is None and item.needs_review is True  # no catalog match
    assert item.notes == "Pikachu #25"  # sheet identity preserved for review


def test_import_singles_sold_row_writes_sale_txn(dynamo_repo):
    show = Show(show_id="s1", name="Show", date=date(2026, 3, 8))
    ctx = ImportContext(repo=dynamo_repo, shows=[show])
    row = _singles_row(Sold="$40.00", **{"Date Sold": "3/7/2026", "Venmo?": "Yes",
                                         "Venmo Fees": "$0.86"})
    summary = import_singles([row], ctx)
    assert summary["sales"] == 1
    [item] = dynamo_repo.list_inventory()
    assert item.status.value == "sold"
    [txn] = dynamo_repo.list_transactions(date(2026, 3, 1), date(2026, 3, 31))
    assert txn.amount == Decimal("40.00")
    assert txn.payment_method == "venmo"
    assert txn.fee == Decimal("0.86")
    assert txn.show_id == "s1"          # nearest show
    assert txn.item_id == item.item_id


def test_import_singles_is_idempotent(dynamo_repo):
    ctx = ImportContext(repo=dynamo_repo)
    rows = [_singles_row()]
    import_singles(rows, ctx)
    import_singles(rows, ctx)
    assert len(dynamo_repo.list_inventory()) == 1


def test_import_singles_skips_malformed_row(dynamo_repo):
    ctx = ImportContext(repo=dynamo_repo)
    summary = import_singles([_singles_row(Condition="???")], ctx)
    assert summary["skipped"] == 1
    assert dynamo_repo.list_inventory() == []
```

Run: FAIL (no `import_singles`).

- [ ] **Step 4: Implement `import_singles`**

```python
def _match_card(ctx: ImportContext, name: str, number: str):
    """Exact match on (name, number); a unique hit returns its card_id."""
    hits = ctx.catalog_index.get((name.strip().lower(), str(number).strip()), [])
    return hits[0].card_id if len(hits) == 1 else None


def _record_sheet_sale(ctx, item, *, sold, date_sold, venmo, venmo_fees, category):
    """Persist the item as sold + its ledger record (import path)."""
    from merlins_collection.models.inventory import ItemStatus

    ctx.repo.put_inventory_item(item.model_copy(update={"status": ItemStatus.SOLD}))
    txn = Transaction(
        txn_id=deterministic_id("txn", {"item": item.item_id}),
        type=TransactionType.SALE,
        item_id=item.item_id,
        category=(ItemCategory.CONSIGNMENT if item.consignment else category),
        date=date_sold,
        amount=sold,
        payment_method="venmo" if venmo else "cash",
        fee=venmo_fees or Decimal("0"),
        show_id=nearest_show_id(date_sold, ctx.shows),
    )
    ctx.repo.put_transaction(txn)


def import_singles(rows: list[dict], ctx: ImportContext) -> dict:
    from merlins_collection.models.inventory import RawInventoryItem

    summary = {"imported": 0, "sales": 0, "skipped": 0, "needs_review": 0}
    for row in rows:
        try:
            condition, modifier = parse_condition(row["Condition"])
            loc = map_location(row.get("Location"))
            card_id = _match_card(ctx, row["Name"], row.get("Card #", ""))
            needs_review = card_id is None
            notes = " — ".join(x for x in (
                f"{row['Name']} #{row.get('Card #', '')}".strip(" #"),
                str(row.get("Notes") or "").strip() or None,
                loc["notes_extra"],
            ) if x)
            item = RawInventoryItem(
                item_id=deterministic_id("Singles", row),
                card_id=card_id,
                finish="normal",
                condition=condition,
                condition_modifier=modifier,
                factory_sealed=loc["factory_sealed"],
                status=loc["status"],
                location=loc["location"],
                cost_basis=parse_money(row.get("Amount Paid")) or Decimal("0"),
                market_value_at_purchase=parse_money(row.get("Market @ purchase")),
                listed_price=parse_money(row.get("Sticker")),
                acquired_at=parse_date(row.get("Date")) or date(2026, 1, 1),
                notes=notes or None,
                tcg_url=str(row.get("TCG Link") or "").strip() or None,
                needs_review=needs_review,
            )
            ctx.repo.put_inventory_item(item)
            summary["imported"] += 1
            summary["needs_review"] += int(needs_review)
            sold = parse_money(row.get("Sold"))
            date_sold = parse_date(row.get("Date Sold"))
            if sold is not None and date_sold is not None:
                _record_sheet_sale(
                    ctx, item, sold=sold, date_sold=date_sold,
                    venmo=parse_bool(row.get("Venmo?")),
                    venmo_fees=parse_money(row.get("Venmo Fees")),
                    category=ItemCategory.RAW,
                )
                summary["sales"] += 1
        except Exception:
            logger.exception("Singles row skipped: %r", row.get("Name"))
            summary["skipped"] += 1
    return summary
```

- [ ] **Step 5: Run tests, lint, commit**

Run: `python -m pytest backend/tests/services/test_spreadsheet_import.py -q` → PASS; `ruff check backend/src` → clean.

```bash
git add backend
git commit -m "feat: spreadsheet importer — parsing helpers + Singles tab"
```

---

### Task 10: Importer — Slabs, Sealed, Bulk tabs

**Files:**
- Modify: `backend/src/merlins_collection/services/spreadsheet_import.py`
- Test: `backend/tests/services/test_spreadsheet_import.py`

**Interfaces:**
- Produces:
  - `import_slabs(rows, ctx) -> dict` — headers: `Date Recieved, Name, Set, card#, Grade, Cert #, Market @ purchase, Amount Paid, Percentage, Sold, Date Sold, Venmo?, Net, Sticker, Current Market, # Of Show Days had, Venmo Fees`. Every slab: `company=PSA`, `needs_review=True` (spec: default + flag for review). `Grade` via `Decimal`; blank cert → `cert_number="unknown"`.
  - `import_sealed(rows, ctx) -> dict` — headers: `Date, Name, Market @ time of purchase, Amount Paid, Percentage, Sold, Date Sold, Venmo?, Net, Sticker, Current Market (2/25), Hold, TCG Link, of days had, Venmo Fees`. `product_type` guessed from name keywords (`booster box`→booster_box, `etb`/`elite trainer`→etb, `bundle`→bundle, else `other` + needs_review). `Hold` truthy → `status=on_hold`.
  - `import_bulk(rows, ctx) -> dict` — headers: `Name, Amount Paid, Sold, Date Sold, Venmo?, Net, Venmo Fees`. One `BulkInventoryItem` per row; no acquisition date column → `acquired_at=date(2026, 1, 1)`.
  - All three reuse `_record_sheet_sale`, `deterministic_id`, the same summary dict shape as `import_singles`, and skip-and-count on malformed rows.

- [ ] **Step 1: Write the failing tests**

```python
def test_import_slabs_defaults_psa_needs_review(dynamo_repo):
    ctx = ImportContext(repo=dynamo_repo)
    row = {"Date Recieved": "1/5/2026", "Name": "Charizard", "Set": "Base",
           "card#": "4", "Grade": "9.5", "Cert #": "12345678",
           "Market @ purchase": "$300", "Amount Paid": "$250", "Percentage": "",
           "Sold": "", "Date Sold": "", "Venmo?": "", "Net": "", "Sticker": "",
           "Current Market": "", "# Of Show Days had": "", "Venmo Fees": ""}
    summary = import_slabs([row], ctx)
    assert summary["imported"] == 1
    [item] = dynamo_repo.list_inventory()
    assert item.kind == "graded"
    assert item.company.value == "PSA"
    assert item.grade == Decimal("9.5")
    assert item.cert_number == "12345678"
    assert item.needs_review is True


def test_import_sealed_maps_product_type_and_hold(dynamo_repo):
    ctx = ImportContext(repo=dynamo_repo)
    row = {"Date": "1/5/2026", "Name": "Evolving Skies Booster Box",
           "Market @ time of purchase": "$400", "Amount Paid": "$350",
           "Percentage": "", "Sold": "", "Date Sold": "", "Venmo?": "", "Net": "",
           "Sticker": "", "Current Market (2/25)": "", "Hold": "TRUE",
           "TCG Link": "", "of days had": "", "Venmo Fees": ""}
    import_sealed([row], ctx)
    [item] = dynamo_repo.list_inventory()
    assert item.kind == "sealed"
    assert item.product_type.value == "booster_box"
    assert item.status.value == "on_hold"


def test_import_bulk_sold_lot(dynamo_repo):
    ctx = ImportContext(repo=dynamo_repo)
    row = {"Name": "5k bulk lot", "Amount Paid": "$50", "Sold": "$80",
           "Date Sold": "3/7/2026", "Venmo?": "No", "Net": "", "Venmo Fees": ""}
    summary = import_bulk([row], ctx)
    assert summary == {"imported": 1, "sales": 1, "skipped": 0, "needs_review": 0}
    [txn] = dynamo_repo.list_transactions(date(2026, 3, 1), date(2026, 3, 31))
    assert txn.category.value == "bulk"
    assert txn.payment_method == "cash"
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest backend/tests/services/test_spreadsheet_import.py -q -k "slabs or sealed or bulk"`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement the three functions**

```python
def import_slabs(rows: list[dict], ctx: ImportContext) -> dict:
    from merlins_collection.models.inventory import GradedInventoryItem

    summary = {"imported": 0, "sales": 0, "skipped": 0, "needs_review": 0}
    for row in rows:
        try:
            card_id = _match_card(ctx, row["Name"], row.get("card#", ""))
            item = GradedInventoryItem(
                item_id=deterministic_id("Slabs", row),
                card_id=card_id,
                company="PSA",  # sheet has no company column; flagged for review
                grade=Decimal(str(row["Grade"]).strip()),
                cert_number=str(row.get("Cert #") or "").strip() or "unknown",
                cost_basis=parse_money(row.get("Amount Paid")) or Decimal("0"),
                market_value_at_purchase=parse_money(row.get("Market @ purchase")),
                listed_price=parse_money(row.get("Sticker")),
                acquired_at=parse_date(row.get("Date Recieved")) or date(2026, 1, 1),
                notes=f"{row['Name']} — {row.get('Set', '')} #{row.get('card#', '')}",
                needs_review=True,
            )
            ctx.repo.put_inventory_item(item)
            summary["imported"] += 1
            summary["needs_review"] += 1
            sold = parse_money(row.get("Sold"))
            date_sold = parse_date(row.get("Date Sold"))
            if sold is not None and date_sold is not None:
                _record_sheet_sale(ctx, item, sold=sold, date_sold=date_sold,
                                   venmo=parse_bool(row.get("Venmo?")),
                                   venmo_fees=parse_money(row.get("Venmo Fees")),
                                   category=ItemCategory.GRADED)
                summary["sales"] += 1
        except Exception:
            logger.exception("Slabs row skipped: %r", row.get("Name"))
            summary["skipped"] += 1
    return summary


_PRODUCT_KEYWORDS = [("booster box", "booster_box"), ("elite trainer", "etb"),
                     ("etb", "etb"), ("bundle", "bundle"),
                     ("booster pack", "booster_pack"), ("collection", "collection_box")]


def _guess_product_type(name: str) -> tuple[str, bool]:
    lowered = name.lower()
    for keyword, ptype in _PRODUCT_KEYWORDS:
        if keyword in lowered:
            return ptype, False
    return "other", True  # unrecognized -> needs review


def import_sealed(rows: list[dict], ctx: ImportContext) -> dict:
    from merlins_collection.models.inventory import SealedInventoryItem

    summary = {"imported": 0, "sales": 0, "skipped": 0, "needs_review": 0}
    for row in rows:
        try:
            product_type, needs_review = _guess_product_type(row["Name"])
            item = SealedInventoryItem(
                item_id=deterministic_id("Sealed", row),
                product_name=str(row["Name"]).strip(),
                product_type=product_type,
                status="on_hold" if parse_bool(row.get("Hold")) else "available",
                cost_basis=parse_money(row.get("Amount Paid")) or Decimal("0"),
                market_value_at_purchase=parse_money(row.get("Market @ time of purchase")),
                listed_price=parse_money(row.get("Sticker")),
                acquired_at=parse_date(row.get("Date")) or date(2026, 1, 1),
                tcg_url=str(row.get("TCG Link") or "").strip() or None,
                needs_review=needs_review,
            )
            ctx.repo.put_inventory_item(item)
            summary["imported"] += 1
            summary["needs_review"] += int(needs_review)
            sold = parse_money(row.get("Sold"))
            date_sold = parse_date(row.get("Date Sold"))
            if sold is not None and date_sold is not None:
                _record_sheet_sale(ctx, item, sold=sold, date_sold=date_sold,
                                   venmo=parse_bool(row.get("Venmo?")),
                                   venmo_fees=parse_money(row.get("Venmo Fees")),
                                   category=ItemCategory.SEALED)
                summary["sales"] += 1
        except Exception:
            logger.exception("Sealed row skipped: %r", row.get("Name"))
            summary["skipped"] += 1
    return summary


def import_bulk(rows: list[dict], ctx: ImportContext) -> dict:
    from merlins_collection.models.inventory import BulkInventoryItem

    summary = {"imported": 0, "sales": 0, "skipped": 0, "needs_review": 0}
    for row in rows:
        try:
            item = BulkInventoryItem(
                item_id=deterministic_id("Bulk", row),
                description=str(row["Name"]).strip(),
                cost_basis=parse_money(row.get("Amount Paid")) or Decimal("0"),
                acquired_at=date(2026, 1, 1),  # tab has no acquisition date
            )
            ctx.repo.put_inventory_item(item)
            summary["imported"] += 1
            sold = parse_money(row.get("Sold"))
            date_sold = parse_date(row.get("Date Sold"))
            if sold is not None and date_sold is not None:
                _record_sheet_sale(ctx, item, sold=sold, date_sold=date_sold,
                                   venmo=parse_bool(row.get("Venmo?")),
                                   venmo_fees=parse_money(row.get("Venmo Fees")),
                                   category=ItemCategory.BULK)
                summary["sales"] += 1
        except Exception:
            logger.exception("Bulk row skipped: %r", row.get("Name"))
            summary["skipped"] += 1
    return summary
```

- [ ] **Step 4: Run tests + lint**

Run: `python -m pytest backend/tests/services/test_spreadsheet_import.py -q` and `ruff check backend/src`
Expected: PASS / clean.

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "feat: importer — Slabs, Sealed, Bulk tabs"
```

---

### Task 11: Importer — Shows, Consignments, Cash, Buying Guidelines + CLI script

**Files:**
- Modify: `backend/src/merlins_collection/services/spreadsheet_import.py`
- Create: `backend/scripts/import_spreadsheet.py`
- Test: `backend/tests/services/test_spreadsheet_import.py`

**Interfaces:**
- Produces:
  - `import_shows(rows, ctx) -> dict` — Vending Net headers used: `Day, Show, Goal, Cash at Beginning of Every Show Day, Assets At start of every show day, Inventory Value at Beginning of show`. One `Show` per row with a parseable `Day`; `show_id = deterministic_id("Show", {"Day":…, "Show":…})`; appends to `ctx.shows`. Returns `{"imported": n, "skipped": n}`.
  - `import_consignments(rows, ctx) -> dict` — headers: `Date recieved, Card Name, Condition, Slab, Card #, Amount we get, Sold, Date Sold, Venmo?, Net, Persons Name, Market, Minimum, To payout, Percentage we get, # of Show Days, Paid Out?, Sold/Returned, Venmo Fees`. Consignors deduped by `Persons Name` (deterministic id from the name); `Slab` truthy → `GradedInventoryItem` (company PSA, grade from Condition if numeric else 10, needs_review) else `RawInventoryItem`; `ConsignmentTerms(split_percent=Percentage we get, minimum_price=Minimum, paid_out=Paid Out?)`; `Sold/Returned == "Returned"` → status `returned_to_consignor`; sold rows → sale txn with `consignor_payout` from `To payout` (fallback: computed from split).
  - `import_cash(rows, ctx) -> dict` — headers `Type, Amount`; skips the `Total` row.
  - `import_buying_guidelines(rows, ctx) -> dict` — headers `Product Type, Cash % Min, Cash % Max, Trade % Min, Trade % Max` (percent values like `"60%"` parsed by stripping `%`).
  - `seed_payment_methods(repo) -> None` — writes `venmo` (1.9% + $0.10) and `cash` (0).
  - `run_import(csv_dir: Path, repo) -> dict` — reads `<Tab>.csv` files present in the dir (`Sealed, Slabs, Singles, Bulk, Consignments, Vending Net, Cash, Buying Guidelines`), builds `catalog_index` from `repo.iter_catalog_cards()`, imports shows FIRST (sales need them), then everything else; returns per-tab summaries.
  - `InventoryRepository.iter_catalog_cards()` — paginated `scan` filtered to `entity = catalog_card`, yielding `CatalogCard`.
- CLI: `python backend/scripts/import_spreadsheet.py <csv_dir> [--table merlins-cards]` prints the summary dict per tab.

- [ ] **Step 1: Write the failing tests**

```python
def test_import_shows_builds_context(dynamo_repo):
    ctx = ImportContext(repo=dynamo_repo)
    rows = [{"Day": "3/8/2026", "Show": "Mint City", "Goal": "$500",
             "Cash at Beginning of Every Show Day": "$200",
             "Assets At start of every show day": "",
             "Inventory Value at Beginning of show": "$3,000"},
            {"Day": "", "Show": "junk row"}]
    summary = import_shows(rows, ctx)
    assert summary == {"imported": 1, "skipped": 1}
    [show] = dynamo_repo.list_shows()
    assert show.name == "Mint City"
    assert show.sales_goal == Decimal("500")
    assert show.inventory_value_at_start == Decimal("3000")
    assert ctx.shows == [show]


def test_import_consignments_creates_consignor_terms_and_payout(dynamo_repo):
    ctx = ImportContext(repo=dynamo_repo)
    row = {"Date recieved": "2/1/2026", "Card Name": "Umbreon VMAX", "Condition": "NM",
           "Slab": "", "Card #": "215", "Amount we get": "", "Sold": "$100",
           "Date Sold": "3/7/2026", "Venmo?": "No", "Net": "", "Persons Name": "David",
           "Market": "$110", "Minimum": "$90", "To payout": "$80",
           "Percentage we get": "20%", "# of Show Days": "", "Paid Out?": "No",
           "Sold/Returned": "Sold", "Venmo Fees": ""}
    summary = import_consignments([row], ctx)
    assert summary["imported"] == 1 and summary["sales"] == 1
    [consignor] = dynamo_repo.list_consignors()
    assert consignor.name == "David"
    [item] = dynamo_repo.list_inventory()
    assert item.consignment.consignor_id == consignor.consignor_id
    assert item.consignment.split_percent == Decimal("20")
    assert item.consignment.minimum_price == Decimal("90")
    [txn] = dynamo_repo.list_transactions(date(2026, 3, 1), date(2026, 3, 31))
    assert txn.category.value == "consignment"
    assert txn.consignor_payout == Decimal("80")


def test_import_cash_and_buying_guidelines(dynamo_repo):
    ctx = ImportContext(repo=dynamo_repo)
    import_cash([{"Type": "Venmo", "Amount": "$321.50"},
                 {"Type": "Total", "Amount": "$999"}], ctx)
    accounts = dynamo_repo.list_cash_accounts()
    assert [a.account for a in accounts] == ["venmo"]
    import_buying_guidelines([{"Product Type": "Slabs", "Cash % Min": "60%",
                               "Cash % Max": "75%", "Trade % Min": "70%",
                               "Trade % Max": "85%"}], ctx)
    [policy] = dynamo_repo.list_buying_policies()
    assert policy.product_type == "slabs"
    assert policy.cash_pct_max == Decimal("75")


def test_run_import_end_to_end(tmp_path, dynamo_repo):
    (tmp_path / "Vending Net.csv").write_text(
        "Day,Show,Goal\n3/8/2026,Mint City,$500\n", encoding="utf-8")
    (tmp_path / "Bulk.csv").write_text(
        "Name,Amount Paid,Sold,Date Sold,Venmo?,Net,Venmo Fees\n"
        "bulk lot,$50,$80,3/7/2026,No,,\n", encoding="utf-8")
    summaries = run_import(tmp_path, dynamo_repo)
    assert summaries["Vending Net"]["imported"] == 1
    assert summaries["Bulk"]["sales"] == 1
    # the bulk sale matched the imported show
    [txn] = dynamo_repo.list_transactions(date(2026, 3, 1), date(2026, 3, 31))
    assert txn.show_id is not None
    # payment methods were seeded
    assert dynamo_repo.get_payment_method("venmo") is not None
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest backend/tests/services/test_spreadsheet_import.py -q -k "shows or consignments or cash or run_import"`
Expected: FAIL.

- [ ] **Step 3: Implement**

Add `iter_catalog_cards` to the repository:

```python
    def iter_catalog_cards(self):
        """Yield every catalog card (paginated scan; import-time only)."""
        from boto3.dynamodb.conditions import Attr

        kwargs = {"FilterExpression": Attr("entity").eq("catalog_card")}
        while True:
            resp = self._table.scan(**kwargs)
            for item in resp.get("Items", []):
                yield CatalogCard.model_validate(item)
            last = resp.get("LastEvaluatedKey")
            if not last:
                return
            kwargs["ExclusiveStartKey"] = last
```

Add to `spreadsheet_import.py`:

```python
def _parse_percent(text) -> Decimal | None:
    return parse_money(str(text or "").replace("%", ""))


def import_shows(rows: list[dict], ctx: ImportContext) -> dict:
    summary = {"imported": 0, "skipped": 0}
    for row in rows:
        day = parse_date(row.get("Day"))
        name = str(row.get("Show") or "").strip()
        if day is None or not name:
            summary["skipped"] += 1
            continue
        show = Show(
            show_id=deterministic_id("Show", {"Day": row.get("Day"), "Show": name}),
            name=name,
            date=day,
            sales_goal=parse_money(row.get("Goal")),
            cash_at_start=parse_money(row.get("Cash at Beginning of Every Show Day")),
            inventory_value_at_start=parse_money(
                row.get("Inventory Value at Beginning of show")),
        )
        ctx.repo.put_show(show)
        ctx.shows.append(show)
        summary["imported"] += 1
    return summary


def import_consignments(rows: list[dict], ctx: ImportContext) -> dict:
    from merlins_collection.models.business import Consignor
    from merlins_collection.models.inventory import (
        ConsignmentTerms,
        GradedInventoryItem,
        RawInventoryItem,
    )

    summary = {"imported": 0, "sales": 0, "skipped": 0, "needs_review": 0}
    consignors: dict[str, Consignor] = {}
    for row in rows:
        try:
            person = str(row["Persons Name"]).strip()
            if person not in consignors:
                consignor = Consignor(
                    consignor_id=deterministic_id("Consignor", {"name": person}),
                    name=person,
                )
                ctx.repo.put_consignor(consignor)
                consignors[person] = consignor
            terms = ConsignmentTerms(
                consignor_id=consignors[person].consignor_id,
                split_percent=_parse_percent(row.get("Percentage we get")) or Decimal("0"),
                minimum_price=parse_money(row.get("Minimum")),
                paid_out=parse_bool(row.get("Paid Out?")),
            )
            returned = str(row.get("Sold/Returned") or "").strip().lower() == "returned"
            common = dict(
                item_id=deterministic_id("Consignments", row),
                status="returned_to_consignor" if returned else "available",
                cost_basis=Decimal("0"),  # not ours; we never paid for it
                market_value_at_purchase=parse_money(row.get("Market")),
                acquired_at=parse_date(row.get("Date recieved")) or date(2026, 1, 1),
                consignment=terms,
                notes=f"{row['Card Name']} #{row.get('Card #', '')}".strip(" #"),
            )
            if parse_bool(row.get("Slab")):
                grade_text = str(row.get("Condition") or "").strip()
                grade = (Decimal(grade_text)
                         if grade_text.replace(".", "", 1).isdigit() else Decimal("10"))
                item = GradedInventoryItem(company="PSA", grade=grade,
                                           cert_number="unknown", needs_review=True,
                                           **common)
                summary["needs_review"] += 1
            else:
                condition, modifier = parse_condition(row.get("Condition") or "NM")
                item = RawInventoryItem(finish="normal", condition=condition,
                                        condition_modifier=modifier, **common)
            ctx.repo.put_inventory_item(item)
            summary["imported"] += 1
            sold = parse_money(row.get("Sold"))
            date_sold = parse_date(row.get("Date Sold"))
            if sold is not None and date_sold is not None and not returned:
                payout = parse_money(row.get("To payout"))
                if payout is None:
                    payout = sold - (sold * terms.split_percent / Decimal("100"))
                from merlins_collection.models.inventory import ItemStatus
                ctx.repo.put_inventory_item(
                    item.model_copy(update={"status": ItemStatus.SOLD}))
                ctx.repo.put_transaction(Transaction(
                    txn_id=deterministic_id("txn", {"item": item.item_id}),
                    type=TransactionType.SALE,
                    item_id=item.item_id,
                    category=ItemCategory.CONSIGNMENT,
                    date=date_sold,
                    amount=sold,
                    payment_method="venmo" if parse_bool(row.get("Venmo?")) else "cash",
                    fee=parse_money(row.get("Venmo Fees")) or Decimal("0"),
                    show_id=nearest_show_id(date_sold, ctx.shows),
                    consignor_payout=payout,
                ))
                summary["sales"] += 1
        except Exception:
            logger.exception("Consignments row skipped: %r", row.get("Card Name"))
            summary["skipped"] += 1
    return summary


def import_cash(rows: list[dict], ctx: ImportContext) -> dict:
    from merlins_collection.models.business import CashAccount

    summary = {"imported": 0, "skipped": 0}
    for row in rows:
        account = str(row.get("Type") or "").strip().lower()
        amount = parse_money(row.get("Amount"))
        if not account or account == "total" or amount is None:
            summary["skipped"] += 1
            continue
        ctx.repo.put_cash_account(CashAccount(account=account, balance=amount))
        summary["imported"] += 1
    return summary


def import_buying_guidelines(rows: list[dict], ctx: ImportContext) -> dict:
    from merlins_collection.models.business import BuyingPolicy

    summary = {"imported": 0, "skipped": 0}
    for row in rows:
        product_type = str(row.get("Product Type") or "").strip().lower()
        if not product_type:
            summary["skipped"] += 1
            continue
        ctx.repo.put_buying_policy(BuyingPolicy(
            product_type=product_type,
            cash_pct_min=_parse_percent(row.get("Cash % Min")),
            cash_pct_max=_parse_percent(row.get("Cash % Max")),
            trade_pct_min=_parse_percent(row.get("Trade % Min")),
            trade_pct_max=_parse_percent(row.get("Trade % Max")),
        ))
        summary["imported"] += 1
    return summary


def seed_payment_methods(repo) -> None:
    from merlins_collection.models.business import PaymentMethod

    repo.put_payment_method(PaymentMethod(method="venmo", fee_percent=Decimal("1.9"),
                                          fee_fixed=Decimal("0.10")))
    repo.put_payment_method(PaymentMethod(method="cash"))


_TAB_IMPORTERS = [  # shows first: everything else matches sales to them
    ("Vending Net", import_shows),
    ("Cash", import_cash),
    ("Buying Guidelines", import_buying_guidelines),
    ("Singles", import_singles),
    ("Slabs", import_slabs),
    ("Sealed", import_sealed),
    ("Bulk", import_bulk),
    ("Consignments", import_consignments),
]


def run_import(csv_dir, repo) -> dict:
    """Import every recognized ``<Tab>.csv`` in ``csv_dir``; returns per-tab summaries."""
    import csv
    from pathlib import Path

    csv_dir = Path(csv_dir)
    seed_payment_methods(repo)
    catalog_index: dict = {}
    for card in repo.iter_catalog_cards():
        catalog_index.setdefault((card.name.lower(), card.number), []).append(card)
    ctx = ImportContext(repo=repo, catalog_index=catalog_index)
    summaries = {}
    for tab, importer in _TAB_IMPORTERS:
        path = csv_dir / f"{tab}.csv"
        if not path.exists():
            continue
        with path.open(newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        summaries[tab] = importer(rows, ctx)
    return summaries
```

Create `backend/scripts/import_spreadsheet.py`:

```python
"""One-shot spreadsheet import: CSV tab exports -> DynamoDB.

Usage: python backend/scripts/import_spreadsheet.py <csv_dir> [--table merlins-cards]
Re-running is safe: ids are deterministic, so rows overwrite instead of duplicate.
"""

import argparse

from merlins_collection.services.dynamodb import InventoryRepository
from merlins_collection.services.spreadsheet_import import run_import


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_dir", help="directory of <Tab>.csv exports")
    parser.add_argument("--table", default="merlins-cards")
    args = parser.parse_args()
    repo = InventoryRepository(args.table)
    for tab, summary in run_import(args.csv_dir, repo).items():
        print(f"{tab}: {summary}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests + lint**

Run: `python -m pytest backend/tests/services/test_spreadsheet_import.py -q` and `ruff check backend/src`
Expected: PASS / clean.

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "feat: importer — shows, consignments, cash, buying guidelines + CLI"
```

---

### Task 12: Full verification + branch finish

**Files:** none new.

- [ ] **Step 1: Full backend suite**

Run: `python -m pytest backend/tests -q --tb=short`
Expected: all PASS.

- [ ] **Step 2: Lint**

Run: `ruff check backend/src`
Expected: clean. Fix anything it flags, re-run tests.

- [ ] **Step 3: Frontend + MCP unaffected check**

Run: `npm test` from the repo root.
Expected: PASS (nothing here touched frontend/mcp-server; this confirms it).

- [ ] **Step 4: Commit any stragglers, then finish the branch**

```bash
git status
git add backend && git commit -m "chore: post-redesign cleanup" # only if changes exist
```

Then use the superpowers:finishing-a-development-branch skill (PR to `main` per CODEOWNERS review flow).
