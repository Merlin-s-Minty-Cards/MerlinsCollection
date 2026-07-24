# Merlin's Minty Cards — Database Redesign

**Date:** 2026-07-17
**Status:** Draft (awaiting user review)
**Branch:** `Database-Redesign`
**Input:** Data Inventory & Database Redesign Report (analysis of the business's operating spreadsheet, 14 tabs)

---

## 0. Context & goal

The business runs on a spreadsheet whose tabs cover far more than the current database models: sealed products, bulk lots, consignments, per-show performance (Vending Net), cash accounts, buying guidelines, and — on every tab — full sale/profit tracking (sold price, date, payment method, fees, net).

The current database (spec 2026-06-22) models only: the PokemonTCG.io catalog, raw + graded inventory items, and price history. This redesign extends the database into the **system of record for the whole business**, so the spreadsheet can eventually retire.

**Decisions made with the user:**

| Question | Decision |
|---|---|
| One database or two? | **One DynamoDB table** (`merlins-cards`). Scale is tiny (~1,500 rows); reports aggregate in the backend. |
| Scope | **Full spreadsheet replacement**: inventory, sales, shows, consignments, cash accounts, buying guidelines. Financial reports become computed endpoints, never stored. |
| Condition granularity | **Keep +/- modifiers** (NM+, LP-, …) — stored as tier + optional modifier. |
| Payment methods | **Open list** (Venmo, cash, others later), each with its own fee rule. |
| Data migration | **In scope** — an import script loads the spreadsheet (CSV exports) into the new schema. |
| Sales venue | Mostly at shows; off-show deals are dated to the nearest show. A sale's show link is **optional**. |
| Customer-visible inventory | Singles, slabs, sealed products, and consignment items. **Not** bulk lots. Only `available` items. |
| Slab grading company (missing in sheet) | Import with a default company, **flagged for manual review**. |
| Location vs. status | **Split**: physical location and item status are separate fields. A "Sealed" *single* means factory-wrapped (premium promo) — a boolean on the card, totally distinct from sealed *products*. |

---

## 1. Approaches considered

**A. Extend the current design minimally** — bolt sealed/bulk onto the card-keyed inventory, put sold-price fields on items, add a shows tab-equivalent. *Rejected:* the current identity model (`card_id` in every key) breaks for sealed products and bulk lots, which have no catalog card; and per-show/per-period reporting from fields scattered across items needs multiple new indexes and still can't represent trades or an item bought at show A and sold at show B.

**B. Unified inventory item + transaction ledger (chosen).** Every physical thing the business holds is one `InventoryItem` with its own `item_id` and a `kind` (raw card, graded slab, sealed product, bulk lot). Money movement is a separate append-only `Transaction` ledger (purchases and sales), grouped by month and indexed by show. Shows, consignors, cash accounts, buying policies, and payment methods are small config-style entities. Reports are computed views over the ledger + items.

**C. Full double-entry accounting.** Debits/credits, journal entries, chart of accounts. *Rejected:* correct but massive overkill for a two-person card business; the ledger in B produces every report the spreadsheet has.

Why B: it matches how the business actually works (each spreadsheet row *is* one physical item; each sale *is* one event), it fixes the identity problem once, and the ledger cleanly answers every aggregation the Vending Net / P&L tabs need — including things the item-field approach can't express (trades, buy-at-show-A-sell-at-show-B).

---

## 2. Entity model

### 2.1 InventoryItem (redesigned)

Identity is a generated `item_id` (ULID — sortable, unique, no coordination). `card_id` becomes an **optional link** to the catalog, present only for kinds that correspond to a catalog card. Each item record is **one physical unit** (matching the spreadsheet's one-row-one-item reality); the old `quantity` field is dropped. A bulk lot is one unit (the lot).

**Shared fields (all kinds):**

| Field | Type | Notes |
|---|---|---|
| `item_id` | str (ULID) | primary identity |
| `kind` | `raw \| graded \| sealed \| bulk` | discriminator (existing `raw`/`graded` literals kept — frontend contract) |
| `status` | enum | `available \| on_hold \| sold \| out_for_grading \| lost \| returned_to_consignor` |
| `location` | str \| None | physical place: `glass`, `toploader`, `binder`, `home`, … (documented values, not a hard enum) |
| `cost_basis` | Decimal | what we paid ("Amount Paid") — never exposed to customers |
| `market_value_at_purchase` | Decimal \| None | "Market @ time of purchase" |
| `current_market_value` | Decimal \| None | denormalized; auto for card-linked raw items, manual for graded/sealed |
| `listed_price` | Decimal \| None | the sticker price |
| `acquired_at` | date | |
| `acquired_show_id` | str \| None | show where we bought it, if any |
| `consignment` | object \| None | see 2.3 — presence means we don't own it |
| `notes` | str \| None | |
| `tcg_url` | str \| None | "TCG Link" column |
| `needs_review` | bool | set by the importer on uncertain mappings |

**Per-kind fields:**

- **`raw`** (a single): `card_id` (optional — importer may fail to match), `finish`, `condition` (tier enum `NM|LP|MP|HP|DMG`), `condition_modifier` (`"+" | "-" | None`), `factory_sealed: bool` (still in plastic wrap — the promo-card premium).
- **`graded`** (a slab): `card_id` (optional), `company` (`PSA|BGS|CGC|SGC`), `grade` (Decimal), `cert_number`.
- **`sealed`** (a product — NEW): `product_name`, `product_type` (`booster_box | etb | bundle | booster_pack | collection_box | other`). No catalog link; market value is manually maintained (like graded).
- **`bulk`** (a lot — NEW): `description`. Nothing else — bulk lots have no per-card identity.

"# of show days had" is **not stored** — it's derived (count of shows between `acquired_at` and sale date), computed by the reporting layer.

### 2.2 Transaction (NEW — the ledger)

An append-only record of money movement. One per purchase and one per sale.

| Field | Type | Notes |
|---|---|---|
| `txn_id` | str (ULID) | |
| `type` | `sale \| purchase` | |
| `item_id` | str | the item bought/sold |
| `category` | `raw \| graded \| sealed \| bulk \| consignment` | denormalized for Vending Net breakdowns |
| `date` | date | |
| `amount` | Decimal | gross price |
| `payment_method` | str | key into the payment-method config (`venmo`, `cash`, …) |
| `fee` | Decimal | computed from the method's fee rule at write time, stored (fees change over time) |
| `show_id` | str \| None | optional link to a show |
| `trade_id` | str \| None | a trade = one sale txn + purchase txn(s) sharing a `trade_id`, `payment_method="trade"` |
| `consignor_payout` | Decimal \| None | sale of a consigned item: what the consignor is owed |

Selling an item = **one atomic `TransactWriteItems`**: create the sale transaction + flip the item's `status` to `sold`. Item and ledger can never disagree. Net profit is always computed (`amount - fee - cost_basis`), never stored.

### 2.3 Consignment (sub-object on InventoryItem) + Consignor (NEW)

A consigned item is a normal item of any kind carrying a `consignment` object: `consignor_id`, `split_percent` (our cut), `minimum_price`, `paid_out: bool`. Customers see it like any other item; the reporting layer excludes consigned items from *our* inventory value and computes payouts owed per consignor.

`Consignor`: `consignor_id`, `name`, `contact`, `notes`.

### 2.4 Show (NEW)

Replaces the Vending Net rows' identity columns. `show_id`, `name`, `date`, `sales_goal`, `cash_at_start`, `inventory_value_at_start` (optional snapshot taken that morning), `notes`. All the Vending Net numeric columns (sold/bought/gross by category, % of inventory sold) are **computed** from the ledger via the show index.

### 2.5 Config entities (NEW, all tiny)

- **CashAccount** — `account` (`venmo | bank | cash`), `balance`, `updated_at`. Manually adjusted snapshots for v1 (deriving balances from the ledger is a future step).
- **BuyingPolicy** — `product_type`, `cash_pct_min/max`, `trade_pct_min/max`. Powers the trade calculator later.
- **PaymentMethod** — `method`, `fee_percent`, `fee_fixed`. Seeded with `venmo` (1.9% + $0.10), `cash` (0).

### 2.6 Catalog (unchanged)

`CARD#<id>` META items, raw/graded price points, `GRADEDPRICE` manual values, the PokemonTCG.io daily sync — all stay exactly as designed in the 2026-06-22 spec. Sealed-product market values are maintained manually on the item (same policy as graded), and the daily sync snapshots them into history the same way it snapshots graded values.

---

## 3. DynamoDB schema

Table `merlins-cards`, existing **GSI1** plus one new **GSI2**.

| Entity | PK | SK | GSI1PK / GSI1SK | GSI2PK / GSI2SK |
|---|---|---|---|---|
| Catalog card / prices / graded price | *(unchanged)* | *(unchanged)* | *(unchanged)* | — |
| **InventoryItem** | `INV#<bucket>` | `ITEM#<item_id>` | `CARD#<card_id>` / `ITEM#<item_id>` *(sparse — card-linked items only)* | — |
| **Transaction** | `TXN#<YYYY-MM>` | `<date>#<txn_id>` | — | `SHOW#<show_id>` / `<date>#<txn_id>` *(sparse)* |
| **Show** | `SHOWLIST` | `SHOW#<date>#<show_id>` | — | — |
| **Consignor** | `CONSIGNORLIST` | `CONSIGNOR#<consignor_id>` | — | — |
| **CashAccount** | `CONFIG` | `CASH#<account>` | — | — |
| **BuyingPolicy** | `CONFIG` | `BUYPOLICY#<product_type>` | — | — |
| **PaymentMethod** | `CONFIG` | `PAYMETHOD#<method>` | — | — |

`bucket = crc32(item_id) % 10` — the sharding scheme survives, re-keyed from `card_id` to `item_id` (fixes the identity problem: sealed/bulk items have no card).

**Access patterns:**

| # | Pattern | Query |
|---|---|---|
| 1 | Customer search / valuation: list all inventory | scatter-gather `INV#0..9`, paginated (unchanged mechanics) |
| 2 | Items for a catalog card | GSI1 `CARD#<id>`, `begins_with ITEM#` |
| 3 | Get/put/delete one item | shard from `item_id` → point op |
| 4 | P&L / totals for a date range | query `TXN#<month>` partitions covering the range, SK `between` dates |
| 5 | Vending Net for a show | GSI2 `SHOW#<id>` → all its transactions |
| 6 | List shows (chronological) | `SHOWLIST`, SK ordered by date |
| 7 | Consignor payouts owed | list consignors + filter sold-unpaid consigned items from pattern 1 |
| 8 | Config reads | point reads / query `CONFIG` |

Everything else (filter search facets, "% of inventory sold", inventory value by category) is in-memory aggregation over patterns 1 and 4 — deliberate at this scale, same philosophy as the current design.

---

## 4. Existing-code impact

- **`models/inventory.py`** — restructured: `item_id` identity, new shared fields, `sealed`/`bulk` kinds added to the discriminated union, `quantity` dropped, `condition_modifier` + `factory_sealed` added. `raw`/`graded` literals and existing field names are kept.
- **`services/dynamodb.py`** — repository re-keyed to `item_id`; new methods for transactions, shows, consignors, config entities.
- **`/inventory/search`** — contract preserved: same flat query params, same response shape. Changes are additive (new kinds, new optional fields). Filter semantics: `condition=LP` matches LP+, LP, and LP-; only `status=available` items of customer-visible kinds (raw, graded, sealed — bulk excluded) are returned; `cost_basis`, `consignment`, and other internal fields are stripped.
- **`catalog_sync.py`** — `refresh_inventory_market_values` updates card-linked items only; graded/sealed snapshot path extended to sealed items.
- **MCP tools / chat** — read through the same repository; updating their summaries for new kinds is a follow-on slice, not this one.
- **`scripts/seed_catalog.py`** — unchanged (catalog side untouched).

**Migration note:** existing dev-seeded inventory items (old card-keyed schema) are discarded — the spreadsheet import repopulates real data. No production data exists yet.

---

## 5. Spreadsheet import

`backend/scripts/import_spreadsheet.py` — reads CSV exports of the tabs (`Sealed`, `Slabs`, `Singles`, `Bulk`, `Consignments`, `Vending Net`, `Cash`, `Buying Guidelines`) from a directory and loads the table.

**Mapping rules:**

| Spreadsheet | Database |
|---|---|
| Condition `D` | tier `DMG` |
| Condition `NM+`, `LP-`, … | tier + `condition_modifier` |
| Location `Glass` / `Toploader` | `location` |
| Location `Sealed` (on a single) | `factory_sealed=true`, location unset |
| Location `Hold` / column `Hold` | `status=on_hold` |
| Location `Lost` | `status=lost` |
| Location `Grading` | `status=out_for_grading` |
| Location `For David` | `status=on_hold` + note (or consignment if it matches a Consignments row) |
| `Sticker` | `listed_price` |
| `Amount Paid` | `cost_basis` |
| `Market @ purchase` | `market_value_at_purchase` |
| Sold columns (`Sold`, `Date Sold`, `Venmo?`, `Venmo Fees`) | a `sale` Transaction; `Venmo?`=yes → `payment_method=venmo` else `cash`; item `status=sold` |
| Vending Net rows (`Day`, `Show`, `Goal`, cash/assets columns) | `Show` entities |
| Sale/purchase dates | matched to the nearest show date → `show_id` (the business already dates off-show deals to the nearest show) |
| Slab company | default `PSA`, `needs_review=true` on every imported slab |
| Cash tab | `CashAccount` rows (skip the `Total` row — computed) |
| Buying Guidelines | `BuyingPolicy` rows |

**Card matching:** singles/slabs are matched to catalog `card_id` by (name, set, card #), exact-then-fuzzy. Unmatched items import with `card_id=None` and `needs_review=true` — never dropped. The importer prints a summary (imported / matched / needs-review counts per tab).

**Idempotency:** `item_id`/`txn_id` are derived deterministically from (tab, row content hash), so re-running the import overwrites rather than duplicates.

---

## 6. Reporting layer (computed, later slices)

The spreadsheet's calculated tabs become admin endpoints — listed here so the schema is validated against them, built in follow-on slices:

- **Inventory Value** — sum of `current_market_value` by kind, excluding consigned/sold/lost.
- **Vending Net per show** — sold/bought/gross by category from GSI2, vs. `sales_goal`, `% of inventory sold` from `inventory_value_at_start`.
- **P&L for a period** — from month-partition ledger queries: gross, fees, cost of goods sold, net.
- **Consignor statement** — sold-unpaid consigned items, payout owed.
- **Cash overview** — the CashAccount rows.

The Trade Calculator stays a live tool (reads BuyingPolicy; stores nothing).

---

## 7. Error handling

Existing policies carry over: Decimal-only money (reject NaN/Infinity), `get_*` → `None` on not-found, boto3 infra errors bubble up. New:

- Sale writes are atomic (`TransactWriteItems`) — a failed transact leaves item + ledger consistent; retries are safe (deterministic keys).
- Selling an already-`sold` item is rejected (condition expression on status).
- A sale transaction referencing a consigned item **requires** `consignor_payout`.
- Importer: a malformed row is logged + skipped with a per-tab failure count, never fatal; ambiguous mappings set `needs_review` rather than guessing silently.

---

## 8. Testing strategy (TDD, moto)

Same boundaries as the current suite (`moto` for DynamoDB, pure tests for models/mappers). RED-first per behavior:

| Area | Coverage |
|---|---|
| Models | union round-trip for all 4 kinds; condition modifier validation; consignment sub-object; Decimal discipline |
| Repository | item CRUD re-keyed on `item_id`; sharding determinism; GSI1 card→items; txn writes + month-partition range query; GSI2 show query; show/consignor/config CRUD; sale transact (item flips to sold atomically); double-sell rejected; pagination |
| Sale flow | fee computed from payment-method config; consignor payout required for consigned items; trade = linked txns |
| Import | each mapping rule in §5 (fixture CSVs); card match hit/miss → `needs_review`; idempotent re-run produces no duplicates; show-date matching |
| Search endpoint | contract unchanged (existing tests keep passing); condition tier-matching includes modifiers; bulk/non-available items excluded; internal fields stripped |

---

## 9. Deliverables of this slice

1. Reshaped Pydantic models (`models/inventory.py`, new `models/business.py` for Transaction/Show/Consignor/config entities)
2. Repository extensions (`services/dynamodb.py`)
3. `/inventory/search` updated to the new item model (contract-preserving)
4. `catalog_sync.py` adjustments (card-linked refresh, sealed snapshots)
5. `backend/scripts/import_spreadsheet.py` + fixture-driven tests

**Explicitly deferred:** reporting endpoints (§6), admin UI for recording sales/shows (required before the spreadsheet can actually retire), MCP tool updates for new kinds, ledger-derived cash balances, automated sealed/graded price feeds.
