# RFC 0007: Database & Interface Enhancements — Data Layer

**Status:** Draft  
**Author:** design-doc agent  
**Date:** 2025-07-27  
**Scope:** Tasks A1–A5 (Advanced Trade Engine, Cosigner Management, Transaction History & Lineage, Show Analytics Data Layer, Enhanced Inventory Search)

## Summary

Extends the single-table DynamoDB schema and FastAPI service layer to support multi-asset trades with vendor margin splits, cosigner management with payout tracking, transaction lineage (full lifecycle history per item), date-based show analytics aggregation, and granular inventory search filters (card number, artist, location, price range).

## Motivation

The existing trade engine handles basic card-for-card + cash trades but cannot represent Venmo/Zelle payment methods on individual legs, vendor-to-vendor margin splits, or multi-payment-method cash components. Cosigner profiles exist as a bare `Consignor` model with no asset linkage or payout percentage. Transaction history exists per-month in a flat ledger but has no per-item timeline or trade-chain lineage. Show analytics are computed ad-hoc with no persistent aggregation. Inventory search lacks filters for card number, artist, and physical location.

## Detailed Design

### A1: Advanced Trade Engine

**Current state:** `TradeSession` is a dict stored at `PK=TRADE#{id}, SK=META`. It supports `outgoing_legs` (our items), `incoming_legs` (their cards), and a single `cash` component with `direction` (they_pay/we_pay), `amount`, and `payment_method`.

**Changes:**

1. Replace the single `cash` component with a `cash_components` list supporting multiple payment methods (cash, Venmo, Zelle, card) each with its own direction and amount.
2. Add a `mode` field that distinguishes `customer` (default) from `vendor` trades.
3. ~~For `vendor` mode, add `margin_split` metadata: a manual percentage override that adjusts incoming card cost bases to reflect the negotiated profit split.~~ **Superseded by Task 3.0** (2026-08-04): `margin_split` is retired. Replaced by three named `basis_mode` values — see below.
4. The balance endpoint computes `is_balanced` using the sum of all cash components.
5. ~~Incoming leg cost basis = `agreed_value` by default; in vendor mode with margin split, cost basis = `agreed_value * (1 - margin_split_pct / 100)`.~~ **Superseded by Task 3.0** (2026-08-04): cost basis is determined by the named `basis_mode`, not a percent formula. See the three modes below.

**New fields on trade session dict:**

```python
# Replaces single "cash" key
"cash_components": [
    {
        "direction": "they_pay" | "we_pay",
        "amount": Decimal,
        "payment_method": "cash" | "venmo" | "zelle" | "card",
    },
    ...
],
# RETIRED (Task 3.0, 2026-08-04) — kept on legacy sessions for read-back only.
# Replaced by basis_mode + manual_basis.
"margin_split": {
    "enabled": bool,
    "percent": Decimal,
} | None,
# Task 3.0: Three named basis modes (replaces percent-based margin split)
"basis_mode": "transfer" | "split" | "manual",  # default "transfer" when absent
"manual_basis": Decimal | None,                  # required iff basis_mode == "manual"
```

**Basis mode math (Task 3.0, owner's ruling 2026-08-04):**

| Mode | `basis_pool` | Cash allowed? |
|---|---|---|
| `transfer` | `total_out_basis` | No (422) |
| `split` | `(total_out_basis + total_in_agreed) / 2` | No (422) |
| `manual` | operator-supplied `manual_basis` | Yes (required when cash is present) |

For card-only trades, the invariant holds: total outgoing sale amounts == total incoming cost bases == `basis_pool`.

**Backward compatibility:** The existing `cash` key is preserved for reading old sessions. New writes always use `cash_components`. The balance endpoint reads whichever is present.

### A2: Cosigner Management

**Current state:** `Consignor` model has `consignor_id`, `name`, `contact`, `notes`. Stored at `PK=CONSIGNORLIST, SK=CONSIGNOR#{id}`. `ConsignmentTerms` on `_ItemBase` already links items to a consignor with `split_percent` and `minimum_price`.

**Changes:**

1. Extend `Consignor` model with `payout_percent` (default split), `email`, `phone`, and `active` flag.
2. Add a new admin router `/admin/cosigners` with full CRUD.
3. Add a `GET /admin/cosigners/{id}/assets` endpoint that queries all inventory items where `consignment.consignor_id == id`.
4. Add a `POST /admin/cosigners/{id}/link` endpoint to batch-link item IDs to a cosigner profile.
5. Add a `GET /admin/cosigners/{id}/analytics` endpoint: total items, total value, items sold, total payouts.
6. The inventory search response already has a `consignment` field on `_ItemBase`; the frontend will use this to badge "Cosigned" items.

**New Pydantic model:**

```python
class Consignor(BaseModel):
    consignor_id: str = Field(default_factory=new_ulid)
    name: str
    contact: str | None = None  # legacy — kept for backward compat
    email: str | None = None
    phone: str | None = None
    payout_percent: Decimal = Decimal("50")  # default payout % to consignor
    active: bool = True
    notes: str | None = None
```

**DynamoDB access pattern (unchanged):** `PK=CONSIGNORLIST, SK=CONSIGNOR#{consignor_id}`. Asset lookup uses a full inventory scan filtered by `consignment.consignor_id`. Given the inventory is sharded across 10 `INV#` partitions (~500 items max at this business scale), this is acceptable.

### A3: Transaction History & Lineage

**Current state:** `Transaction` records live at `PK=TXN#{YYYY-MM}, SK={date}#{txn_id}`. Each references one `item_id`. Trade confirmation already sets `trade_id` on every transaction it creates.

**Changes:**

1. Add a new `ItemTimeline` concept: a GSI3 on the main table keyed by `item_id`, returning all transactions for that item in chronological order.
   - Rather than add a GSI3 (requires table recreation in tests), we store an explicit `TIMELINE` item per transaction event under the item's partition:
     - `PK=INV#{bucket(item_id)}, SK=TIMELINE#{date}#{txn_id}`
     - Contains: `txn_id`, `type`, `date`, `amount`, `trade_id`, `counterpart_item_id`, `payment_method`
   - Written atomically alongside the existing transaction record.

2. Add a `lineage_id` field to `_ItemBase`. When an item is created through a trade, its `lineage_id` = the outgoing item's `lineage_id` (or the outgoing item's `item_id` if it has no lineage). When purchased outright, `lineage_id` = own `item_id`.

3. Add `predecessor_item_id` to `_ItemBase`: the item this one was traded from (None for direct purchases).

4. New endpoints:
   - `GET /admin/inventory/{item_id}/timeline` — all timeline events for an item
   - `GET /admin/inventory/{item_id}/lineage` — the full trade chain: walk `predecessor_item_id` backward and forward to reconstruct the chain, computing profit at each step.
   - `GET /admin/transactions/search` — search transactions by name (via item lookup), date range, amount range

**Timeline record schema:**

```python
{
    "PK": f"INV#{bucket(item_id)}",
    "SK": f"TIMELINE#{date}#{txn_id}",
    "entity": "timeline_event",
    "item_id": item_id,
    "txn_id": txn_id,
    "type": "purchase" | "sale" | "trade_in" | "trade_out",
    "date": date_iso,
    "amount": Decimal,
    "trade_id": str | None,
    "counterpart_item_id": str | None,  # the other side of a trade
    "payment_method": str,
    "show_id": str | None,
}
```

**Profit calculation:** For each step in a lineage:
- Purchase: cost = `amount`
- Trade out: realized = `agreed_value - cost_basis`
- Sale: realized = `sale_amount - cost_basis`
- Cumulative profit = sum of realized at each step across the chain.

### A4: Show Analytics Data Layer

**Current state:** Shows are stored at `PK=SHOWLIST`. Transactions link to shows via `GSI2PK=SHOW#{show_id}`. `list_transactions_for_show()` already returns all transactions for a show. `Show` model has `inventory_value_at_start`.

**Changes:**

1. Add a `ShowAnalyticsSnapshot` model, computed and stored after a show is marked complete:

```python
class ShowAnalyticsSnapshot(BaseModel):
    show_id: str
    date: date
    total_sold: Decimal          # cash sales + trade-out valuations
    total_bought: Decimal         # cash purchases + trade-in valuations
    net_sales: Decimal            # sold - bought
    inventory_value_at_start: Decimal | None
    sell_through_rate: Decimal | None  # pct of starting inventory sold
    items_sold_count: int
    items_bought_count: int
    trades_count: int
    cash_at_start: Decimal | None
    snapshot_generated_at: datetime
```

2. Store at `PK=SHOW#{show_id}, SK=ANALYTICS`. This reuses the existing show's partition (trade sessions already use `TRADE#{id}`).

3. Add `POST /admin/shows/{show_id}/analytics/generate` — computes the snapshot from transactions and stores it.

4. Add `GET /admin/shows/{show_id}/analytics` — returns the stored snapshot.

5. Add `GET /admin/analytics/by-date?start=&end=` — returns all show snapshots in a date range (queries `SHOWLIST`, filters by date, fetches analytics for each).

**Computation logic:**
- `total_sold` = sum of `amount` for all SALE transactions on the show (includes trade-out legs which have `payment_method="trade"`)
- `total_bought` = sum of `amount` for all PURCHASE transactions on the show
- `net_sales` = `total_sold - total_bought`
- `sell_through_rate` = `items_sold_count / (inventory_value_at_start_item_count)` (requires knowing starting item count — stored on the Show model or computed from items where `acquired_at < show.date`)
- Items sold/bought/traded counts are derived from transaction type + `trade_id` presence.

### A5: Enhanced Inventory Search

**Current state:** The public `/inventory/search` endpoint supports: `name`, `set_id`, `rarity`, `condition`, `min_price`, `max_price`, `language`, `sort`. The admin `/admin/inventory` endpoint returns all items with optional filtering client-side.

**Changes:**

1. Add new query params to the admin inventory endpoint (server-side filtering):
   - `card_number: str | None` — matches `card.number` from catalog
   - `artist: str | None` — matches `card.artist` from catalog (substring, case-insensitive)
   - `location: str | None` — exact match on `item.location`
   - `min_price / max_price` — filter by `cost_basis` or `current_market_value` (admin sees cost)

2. Add these same filters to the public search endpoint where appropriate:
   - `card_number` and `location` are useful for staff and can be added to the customer-facing search too (card_number is not sensitive; location is stripped from customer response but useful for admin).

3. The catalog `CatalogCard` model already carries `artist` and `number` fields — these just need to be exposed as filter dimensions.

**Implementation approach:** Since DynamoDB does not support ad-hoc multi-attribute queries, filtering continues to be in-memory (same as existing approach). The inventory is small enough (~500 items) that scanning all shards and filtering in Python is practical. For `artist` and `card_number`, the catalog must be joined (same pattern as the existing `name` filter).

## Data Schemas

### DynamoDB Key Patterns (new)

| Entity | PK | SK | GSI1PK | GSI1SK | GSI2PK | GSI2SK |
|--------|----|----|--------|--------|--------|--------|
| Timeline event | `INV#{bucket}` | `TIMELINE#{date}#{txn_id}` | — | — | — | — |
| Show analytics | `SHOW#{show_id}` | `ANALYTICS` | — | — | — | — |
| Trade session (existing) | `TRADE#{id}` | `META` | `TRADES#{status}` | `{created_at}` | — | — |

### DynamoDB Key Patterns (existing, unchanged)

| Entity | PK | SK | GSI1PK | GSI1SK | GSI2PK | GSI2SK |
|--------|----|----|--------|--------|--------|--------|
| Inventory item | `INV#{bucket}` | `ITEM#{item_id}` | `CARD#{card_id}` | `ITEM#{item_id}` | — | — |
| Transaction | `TXN#{YYYY-MM}` | `{date}#{txn_id}` | — | — | `SHOW#{show_id}` | `{date}#{txn_id}` |
| Consignor | `CONSIGNORLIST` | `CONSIGNOR#{id}` | — | — | — | — |
| Show | `SHOWLIST` | `SHOW#{date}#{id}` | — | — | — | — |

### New/Modified Pydantic Models

| Model | File | Change |
|-------|------|--------|
| `Consignor` | `models/business.py` | Add `email`, `phone`, `payout_percent`, `active` |
| `ShowAnalyticsSnapshot` | `models/business.py` | New model |
| `_ItemBase` | `models/inventory.py` | Add `lineage_id`, `predecessor_item_id` |
| Trade session dict | (untyped dict) | Add `cash_components`, `margin_split` |

## API Contracts

### A1: Multi-Asset Trade

**PUT `/admin/trades/{trade_id}/cash`** — updated to accept list:

```json
// Request
{
  "cash_components": [
    { "direction": "they_pay", "amount": "50.00", "payment_method": "venmo" },
    { "direction": "we_pay", "amount": "10.00", "payment_method": "cash" }
  ]
}
```

**PATCH `/admin/trades/{trade_id}`** — new fields:

```json
{
  "mode": "vendor",
  "margin_split": { "enabled": true, "percent": "15" }
}
```

**GET `/admin/trades/{trade_id}/balance`** — response now includes:

```json
{
  "trade_id": "...",
  "total_out_value": "150.00",
  "total_in_value": "120.00",
  "total_cost_basis": "100.00",
  "cash_components_net": "40.00",
  "margin_pct": "60.0",
  "margin_split_applied": true,
  "is_balanced": true
}
```

### A2: Cosigner CRUD

| Method | Route | Auth | Description |
|--------|-------|------|-------------|
| POST | `/admin/cosigners` | admin | Create cosigner |
| GET | `/admin/cosigners` | admin | List all cosigners |
| GET | `/admin/cosigners/{id}` | admin | Get one cosigner |
| PATCH | `/admin/cosigners/{id}` | admin | Update cosigner |
| DELETE | `/admin/cosigners/{id}` | admin | Deactivate cosigner |
| GET | `/admin/cosigners/{id}/assets` | admin | List linked inventory |
| POST | `/admin/cosigners/{id}/link` | admin | Link item IDs to cosigner |
| GET | `/admin/cosigners/{id}/analytics` | admin | Cosigner performance stats |

**POST `/admin/cosigners`** request:
```json
{
  "name": "Alice",
  "email": "alice@example.com",
  "phone": "555-0101",
  "payout_percent": "60",
  "notes": "Local collector"
}
```

**POST `/admin/cosigners/{id}/link`** request:
```json
{
  "item_ids": ["01ITEM1", "01ITEM2"],
  "split_percent": "0.60",
  "minimum_price": "25.00"
}
```

### A3: Transaction History & Lineage

| Method | Route | Auth | Description |
|--------|-------|------|-------------|
| GET | `/admin/inventory/{item_id}/timeline` | admin | Item event history |
| GET | `/admin/inventory/{item_id}/lineage` | admin | Full trade chain |
| GET | `/admin/transactions/search` | admin | Search transactions |

**GET `/admin/inventory/{item_id}/timeline`** response:
```json
{
  "item_id": "...",
  "events": [
    {
      "txn_id": "...",
      "type": "purchase",
      "date": "2025-03-15",
      "amount": "15.00",
      "payment_method": "cash",
      "trade_id": null,
      "show_id": "SHOW1"
    },
    {
      "txn_id": "...",
      "type": "trade_out",
      "date": "2025-04-01",
      "amount": "20.00",
      "payment_method": "trade",
      "trade_id": "TRADE1",
      "counterpart_item_id": "ITEM_B"
    }
  ]
}
```

**GET `/admin/inventory/{item_id}/lineage`** response:
```json
{
  "lineage_id": "...",
  "chain": [
    { "item_id": "A", "name": "Card A", "acquired_cost": "15.00", "exit_value": "20.00", "profit": "5.00" },
    { "item_id": "B", "name": "Card B", "acquired_cost": "20.00", "exit_value": "25.00", "profit": "5.00" },
    { "item_id": "C", "name": "Card C", "acquired_cost": "25.00", "exit_value": "30.00", "profit": "5.00" }
  ],
  "cumulative_profit": "15.00",
  "status": "complete"
}
```

**GET `/admin/transactions/search?name=Dragonair&start=2025-01-01&end=2025-06-30&min_amount=10`**

### A4: Show Analytics

| Method | Route | Auth | Description |
|--------|-------|------|-------------|
| POST | `/admin/shows/{show_id}/analytics/generate` | admin | Compute and store snapshot |
| GET | `/admin/shows/{show_id}/analytics` | admin | Retrieve stored snapshot |
| GET | `/admin/analytics/by-date` | admin | List snapshots in date range |

**GET `/admin/shows/{show_id}/analytics`** response:
```json
{
  "show_id": "...",
  "date": "2025-04-15",
  "total_sold": "1250.00",
  "total_bought": "450.00",
  "net_sales": "800.00",
  "inventory_value_at_start": "15000.00",
  "sell_through_rate": "8.3",
  "items_sold_count": 42,
  "items_bought_count": 12,
  "trades_count": 5,
  "cash_at_start": "500.00",
  "snapshot_generated_at": "2025-04-15T22:30:00Z"
}
```

### A5: Enhanced Inventory Search

**GET `/admin/inventory?card_number=181&artist=Mitsuhiro&location=glass&min_price=5&max_price=50`**

New query parameters (all optional, AND-combined):

| Param | Type | Filter Logic |
|-------|------|--------------|
| `card_number` | string | Exact match on catalog `number` field |
| `artist` | string | Case-insensitive substring on catalog `artist` field |
| `location` | string | Exact match on item `location` field |
| `min_price` | decimal | Item `cost_basis >= min_price` |
| `max_price` | decimal | Item `cost_basis <= max_price` |

## Alternatives Considered

1. **GSI3 for timeline queries:** Would allow point-read of an item's history, but requires table recreation in moto tests and adds an unused GSI column to every row. Rejected in favor of co-locating timeline events in the item's own `INV#` partition under a different SK prefix.

2. **Separate analytics table:** Would cleanly separate read-heavy analytics from write-heavy inventory. Rejected because the single-table design is already established, the data volume is tiny (one row per show), and a separate table doubles infra config.

3. **Typed trade session model:** Could replace the untyped `dict` with a full Pydantic model. Rejected for this RFC to minimize blast radius — the existing router works with dicts and the session is stored as-is. A future RFC can introduce typed sessions once the feature is stable.

4. **Real-time analytics computation:** Instead of stored snapshots, compute on every read. Rejected because transaction queries across months are expensive relative to the single-row read of a pre-computed snapshot.

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Timeline writes add latency to trade confirm | Low | Timeline write is a simple `put_item`, not transactional. Failure is logged but does not block the trade. |
| Lineage chain walk is O(n) per chain length | Low | Chains are short (typically 2–5 trades). No card realistically trades 50 times. |
| Inventory scan for cosigner assets is O(all items) | Low | ~500 items across 10 shards. Acceptable at this scale. |
| `cash_components` backward compat with old `cash` | Medium | Balance endpoint reads `cash_components` first, falls back to `cash`. Migration script optional. |
| `lineage_id` / `predecessor_item_id` missing on existing items | Low | Default to `None`. Items without lineage are standalone — the timeline still works via transaction records. |

## Open Questions

1. **Sell-through denominator:** Should `sell_through_rate` use item count or dollar value of starting inventory? (Recommendation: item count — simpler and matches the Implementation Plan wording "Percentage of Inventory Sold".)

2. **Margin split confirmation UX:** Should vendor margin split require a second "confirm" step, or is setting it on the session sufficient? (Recommendation: single step — the confirm-trade endpoint is already the point of no return.)

3. **Timeline event backfill:** Should existing transactions get timeline events written retroactively via a migration script? (Recommendation: yes, as a one-time script in `backend/scripts/`. Not blocking for the feature.)
