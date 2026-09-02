# RFC 0024 — Acquisition Economics & Transaction Editing: PROGRESS

**Read this first.** State of the world for anyone picking up a task.

**This file is the tracked progress file — not `claude-progress.md`.**

**Last updated:** 2026-09-02 (planning only — **no task started**)
**Branch:** `feat/round9-rfcs-0021-0025`
**RFC:** [`../../rfcs/0024-acquisition-economics-and-transaction-editing.md`](../../rfcs/0024-acquisition-economics-and-transaction-editing.md)
**Task index:** [`README.md`](README.md)
**Round guide:** [`../round9/README.md`](../round9/README.md)

## Status

| Task | State |
|---|---|
| T1 `acquisition_ratio` both sides | NOT STARTED |
| T2 Deal-row market / paid / ratio | NOT STARTED |
| T3 `PATCH /admin/transactions/{txn_id}` | NOT STARTED |
| T4 Transaction edit dialog | NOT STARTED |
| T5 Richer transaction detail | NOT STARTED |
| T6 Docs + verification | NOT STARTED |

## Next: T1

T3 is equally unblocked. T1+T2 (display) and T3+T4 (ledger) are two independent
halves and either is a clean session.

## Facts established during planning (do not re-derive these)

- **`market_value_at_purchase` ALREADY EXISTS** on `InventoryItem`
  (`models/inventory.py:208`). It is populated on confirm by `purchases.py:117`
  (`buy_item.get("market_value")`) and `trades.py:806`; it is in
  `inventory_filters.py` (RANGE) and `inventory_sort.py`; it has an
  `INVENTORY_COLUMNS` entry and a `CardDetailModal` row; and
  `spreadsheet_import.py` fills it from four different sheet columns. **Nothing
  new needs to be captured.** The gap is entirely derivation and display.
- **`IncomingCardForm` already sends `market_value`** — `card ? parseMoney(String(card.display_price ?? '')) : null`,
  never coerced to 0 for a manual entry or an unpriced card.
- **`customerView` already exists** as page state on `/admin/trade` (line ~81),
  with a toggle in the header, and is already threaded into `DealSummary`, which
  suppresses profit with `showProfit && !customerView`.
- **`DealSearchPanel` renders `item.sticker_price ?? item.current_market_value`**
  for inventory rows — the sell price, not the cost. `cost_basis` and
  `market_value_at_purchase` are already in `/admin/inventory/search`'s response;
  the panel does not read them.
- **Transaction keys:** `PK = TXN#<YYYY-MM>`, `SK = <ISO date>#<txn_id>`, plus
  `GSI2PK = SHOW#<show_id>` / `GSI2SK = <date>#<txn_id>` when a show is set
  (`_txn_keys`). **The date is in both the PK and the SK.**
- **`put_transaction` whole-item `put_item`s**, so a removed `show_id` drops the
  GSI2 attributes with no special handling on a same-date edit.
- **`get_transaction` is deliberately not a point read** — it walks month
  partitions newest-first because the caller does not have to know the date.
  Common case one query, worst case ~37.
- **`/items-brief`'s docstring explicitly forbids returning a price** and gives
  its reasoning. T5 must update it, not quietly contradict it.
- **The trade balance display bug is already fixed** (RFC 0013 — the frontend was
  `+ cashNet` where the backend was `- cash_delta`). Do not re-fix it.

## Decisions made autonomously (with the rejected alternative)

- **A trade leg cannot be edited (400).** `_compute_basis_pool` allocated the
  incoming basis pro-rata across all legs at confirm; a single-leg amount change
  leaves that allocation inconsistent with its own inputs, and re-running it would
  rewrite cost bases on items that may since have been sold or consigned.
  Rejected: allowing it, and re-running the allocation. **This means a mistaken
  trade still has no correction path** — a real recorded limitation, same shape as
  the void feature's "a mistaken buy still has no correction path."
- **A voided transaction cannot be edited (409).** Rejected allowing it: editing a
  row that counts toward nothing produces an incoherent audit trail.
- **The `cost_basis` sync is guarded on equality with the OLD amount, and reports
  a skip reason.** Rejected an unguarded overwrite (destroys a human correction)
  and a silent skip (indistinguishable from success).
- **A date change is one `transact_write_items`.** Rejected two calls: a
  half-applied move duplicates or destroys a ledger row.
- **The ratio is computed server-side and returned, not divided in the client.**
  Rejected client-only: it would put a money rule on the client with nothing
  pinning it, which is the exact shape of `condition-pricing.ts`'s unchecked
  parity claim.
- **`acquisition_ratio` is NOT stored on the item.** Rejected storing + a
  backfill: it is derived from two stored inputs and would go stale the moment
  either changed — including from this RFC's own `cost_basis` sync.
- **Customer view hides the ratio AND `Paid`, keeps `Market`.** The owner said
  "hide percent"; showing "Paid $32" beside a $100 card is strictly worse than
  showing the percentage, so the conservative reading was taken. Trivially
  reversible if the owner meant the literal narrow thing.

## Owner gates on this RFC

None.
