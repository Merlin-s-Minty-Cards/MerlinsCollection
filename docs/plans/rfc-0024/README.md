# RFC 0024 — Task Index

**RFC:** [`docs/rfcs/0024-acquisition-economics-and-transaction-editing.md`](../../rfcs/0024-acquisition-economics-and-transaction-editing.md)
**Round guide:** [`docs/plans/round9/README.md`](../round9/README.md) — read it first.
**Progress:** [`progress.md`](progress.md) · **Follow-ups:** [`follow-ups.md`](follow-ups.md)

Independent of the other RFCs. Easier after 0022 (the dialog reuses nothing from
it, but the codebase will be familiar).

| Task | Title | Depends on | Suite |
|---|---|---|---|
| T1 | `acquisition_ratio` — both sides + cross-boundary test | — | backend, frontend |
| T2 | Market / paid / ratio on every deal row | T1 | frontend |
| T3 | `PATCH /admin/transactions/{txn_id}` | — | backend |
| T4 | Transaction edit dialog | T3 | frontend |
| T5 | Richer transaction detail (`items-brief` + render) | T1, T3 | backend, frontend |
| T6 | Docs + full-suite verification | all | all |

**T1+T2 and T3+T4 are two independent halves.** Either can be a session on its
own.

---

## T1 — `acquisition_ratio`, both sides, pinned

**Files:** `backend/src/merlins_collection/services/acquisition.py` (new),
`frontend/lib/acquisition.ts` (new), `backend/tests/test_cross_boundary.py`.

```python
def acquisition_ratio(item) -> Decimal | None:
    """market_value_at_purchase / cost_basis, as a PERCENT."""
```

**`None` when either figure is absent OR `cost_basis` is zero.** A free card is a
real and routine thing at a buy table (a throw-in, a bulk lot); its ratio is
undefined, not infinite and not zero. Every caller renders an em dash.

Frontend mirror: `acquisitionRatio()`, `formatRatio()`, `ratioTone()`.
Tone bands, defined once in `ratioTone()`: ≥200% good, 100–200% neutral, <100%
bad, `null` → **no chip at all**, not a grey zero.

**The cross-boundary test is the point of this task.** CLAUDE.md records
`mcp-server/src/condition-pricing.ts` claiming cross-language parity that no test
ever checked. Read `backend/tests/test_cross_boundary.py` — it is the existing
precedent for a Python↔TypeScript pin — and build a shared case table covering:
both present, market absent, cost absent, cost zero, cost zero AND market zero,
a fractional result, and a very large result.

**RED first.**

---

## T2 — Market / paid / ratio on every deal row

**Files:** `frontend/components/admin/deal/DealCardRow.tsx`,
`DealSearchPanel.tsx`, `DealStagedColumn.tsx`, `IncomingCardForm.tsx`,
`frontend/app/(admin)/admin/trade/page.tsx`.

`DealRowCard` gains `marketValue`, `pricePaid`, `showRatio`. A third line renders:

```
Market $100.00 · Paid $32.00 · 312%
```

Sources per row kind are in the RFC's §2 table. Two that are easy to get wrong:

- **Catalog search rows:** market is `display_price`, computed server-side by the
  one shared finish-aware `_market_price(card, "normal")` lookup. **Never
  re-implement the finish walk in the frontend** — a second copy of it is how 174
  of 213 live items once went unpriced.
- **Inventory rows:** `DealSearchPanel` currently renders
  `item.sticker_price ?? item.current_market_value`. Add `cost_basis` and
  `market_value_at_purchase` — **both are already in `/admin/inventory/search`'s
  response**; the panel simply does not read them.

**Customer view.** `customerView` already exists as page state on `/admin/trade`
and is already threaded into `DealSummary`. Thread the **same prop, same name**
into the three deal components.

> Under customer view, **hide the ratio AND hide `Paid`. Keep `Market`.**
> Price paid is our cost basis and showing it to the person across the table is
> worse than showing the percentage.

**Rules that must not break:** an absent figure is `—`, never `$0.00`; a catalog
price is a Near Mint market figure and is never presented as a sale price; the
line is always rendered, never behind a hover; the row must not change height as
values resolve (rows that jump make the list move under the cursor mid-click).

---

## T3 — `PATCH /admin/transactions/{txn_id}`

**Files:** `backend/src/merlins_collection/routers/admin/analytics.py` (beside the
four void/restore routes), `backend/src/merlins_collection/models/business.py`,
`backend/src/merlins_collection/services/dynamodb.py`,
`backend/tests/routers/admin/test_analytics.py`.

**Read `reverse_sales` first.** It is the precedent for a guarded, single
`transact_write_items` on the ledger, and this endpoint is the same class of
write.

Accepted fields: `amount`, `date`, `payment_method`, `fee`, `show_id`, `notes`.
Anything else → **422**, never a silent no-op.

Refusals, each deliberate:

| Condition | Status |
|---|---|
| voided transaction | **409** — restore first |
| trade leg (`trade_id` set) | **400** — see the RFC's §3.1 |
| unknown `txn_id` | 404 |

**The date is in BOTH the partition key and the sort key**
(`PK = TXN#<YYYY-MM>`, `SK = <ISO date>#<txn_id>`).

- Same date → `put_transaction` alone. It whole-item `put_item`s, so a removed
  `show_id` drops the GSI2 attributes naturally.
- **Different date → delete the old key + put the new one in ONE
  `transact_write_items`**, the delete guarded by `attribute_exists(SK)`. Never
  two calls; a half-applied date change duplicates or destroys a ledger row.

New `Transaction` fields, all optional with `None`/`[]` defaults so every existing
row validates and **nothing is backfilled**: `edited_at`, `edited_by`,
`edit_history: list[TransactionEdit]` (`{at, by, field, old, new}`, capped at 20 —
the 400 KB item ceiling is why `review_reason` and `void_reason` are bounded too).

**`edited_by` is server-stamped** from `email or username or sub`, exactly like
`voided_by`. Never client-supplied.

**`cost_basis` sync** (purchases only): update the item's `cost_basis` in the
**same** `transact_write_items`, **only when the item's current basis equals the
transaction's OLD amount.** Otherwise skip and report
`cost_basis_skipped_reason`. A silent skip is as bad as a silent overwrite.

**Downstream, all three required:**
- Timeline event keyed **`<txn_id>#edit`**, re-put not appended. The sale's own
  event is `TIMELINE#<date>#<txn_id>`, so a same-day edit would otherwise
  overwrite the sale itself.
- `ShowAnalyticsSnapshot.stale = True` for every affected show — both, if the date
  moved between shows. Reuse void's path.
- **`services/ledger.is_countable` is untouched.** Do not add an `edited_at`
  check to any aggregate. Countability has one definition.

**RED first.** Tests: each refusal; a same-date amount edit; a cross-month date
edit (assert the old key is gone and the new one exists); the `cost_basis` follow;
the `cost_basis` skip-with-reason; the timeline key; the staleness marking; a
disallowed field 422. **Send money as a JSON number in these tests**, not a
string — the suite's string habit is why a production 500 went unnoticed.

---

## T4 — Transaction edit dialog

**Files:** `frontend/components/admin/shared/SaleDetailModal.tsx`,
`frontend/components/admin/shared/TransactionGroups.tsx`, new dialog component.

A per-leg **Edit** action beside the existing per-leg void/restore, opening a
dialog — **not** an RFC 0022 inline cell. An amount change here has a side effect
on another entity, can move a row between DynamoDB partitions, and marks a report
stale; it needs a surface that can show `cost_basis_skipped_reason` on the way
back.

- `MoneyInput` for amount and fee. Never `type="number"`, never `parseFloat`.
- `lib/dates.ts` for the date. Never `new Date()` on a date-only string.
  Any test rendering a date pins a negative-offset TZ via
  `frontend/lib/__tests__/_timezone.ts` and uses
  `vi.useFakeTimers({ toFake: ['Date'] })`.
- `useShows()` select for the show, gated on `api.isAuthenticated`.
- `vault-field` on every control.
- The dialog surfaces `cost_basis_skipped_reason` when the server returns one.
- Render `edit_history` on the leg, the way the void reason already renders.

**Do not regress the popup's identity keying.** `SaleDetailModal` stores the
group's `key` and re-derives the current object from `groups` on every render,
because a void from inside the open popup triggers `refetchDay()` and rebuilds
every group as a new object. An edit does the same thing.

---

## T5 — Richer transaction detail

**Files:** `backend/src/merlins_collection/routers/admin/inventory.py`
(`/items-brief`), `SaleDetailModal.tsx`, `frontend/app/(admin)/admin/history/`.

`/items-brief` gains `cost_basis`, `market_value_at_purchase`,
`acquisition_ratio` (computed server-side by `services/acquisition.py`) and
`current_market_value`.

> **Update that endpoint's docstring in the same commit.** It currently says it
> deliberately returns no price, because "echoing a second copy here … would just
> be a figure that can drift from the one that matters." That reasoning is right
> about `amount` and does not cover these fields — they are different facts about
> a different moment, and cannot drift from `amount` because they are not claims
> about it. Say that in the docstring, or the next reader will "fix" it back.

Cap-at-100 and null-not-omitted shape unchanged.

**Leg profit** is `amount - cost_basis` for a sale, **display-only, computed at
render, never stored.** History already computes `step_profit` per lineage hop
with a guard against a $0 cost basis overstating profit on consigned items —
**reuse that guard, do not write a second one.**

---

## T6 — Docs + full-suite verification

- `CLAUDE.md`: the transaction correction path beside the existing void section
  (including that trades and purchases-by-re-pointing still have none); the
  acquisition ratio and its single authority; what customer view hides.
- Every suite in the round guide.
