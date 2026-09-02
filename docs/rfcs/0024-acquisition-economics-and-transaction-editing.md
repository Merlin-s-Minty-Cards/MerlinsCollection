# RFC 0024: Acquisition Economics & Transaction Editing

**Status:** Draft — written 2026-09-02, adversarially reviewed the same day
(see "Adversarial review findings"). No code written yet.
**Author:** Claude (planning session), owner-directed
**Round:** 9 — see [`docs/plans/round9/README.md`](../plans/round9/README.md)
**Owner tasks covered:** "Transactions need to be able to be changed manually in
case of typos + more transaction details"; "Add market and percent (market @
purchase / amount paid) to all cards displayed in the buy/sell/trade page and hide
percent on customer view — this should include cards showing up on searches, as
well as the cards that have been selected for a transaction"; "When an inventory
item is selected for a transaction, it should also display the price paid."

## Summary

One theme: **the numbers that say whether a deal was good are stored but not
shown, and the ledger that records them cannot be corrected.**

1. **An acquisition ratio** — `market_value_at_purchase / cost_basis`, the
   owner's "market @ purchase / amount paid" — becomes a first-class derived
   figure with a single authority on each side of the boundary, rendered on every
   deal row and suppressed under the existing customer-view toggle.
2. **Price paid** appears on every already-selected inventory row in Buy / Sell /
   Trade, alongside market.
3. **`PATCH /admin/transactions/{txn_id}`** lets an admin correct a typo — amount,
   date, payment method, fee, show, notes — with a server-stamped audit trail, an
   automatic `cost_basis` correction on the item, and the same analytics-staleness
   marking a void already does.
4. **Transaction detail grows** to carry cost basis, market at purchase, the
   acquisition ratio, and per-leg profit.

**`market_value_at_purchase` already exists** on `InventoryItem`, is populated by
`purchases.py` and `trades.py` on confirm, is in both the sort and filter
registries, and is rendered in one column of the inventory table. Nothing new
needs to be captured. The gap is entirely in derivation and display.

## Motivation

### The ratio nobody can see

A buy at a show is a bet: pay $32 for a card the market says is worth $100 and
you are at 312%. That number decides whether to take the deal, and it is the
number the owner asks for by name. Today the operator can see market (on catalog
search rows) and, separately, what they typed as the price — and must do the
division in their head, at a table, under time pressure, per card, on a five-card
deal.

`market_value_at_purchase` has been stored on every item bought through the deal
page since it was added; `IncomingCardForm` sends
`market_value: card ? parseMoney(String(card.display_price ?? '')) : null` and
`purchases.py` reads it into the field. The data is there. Nothing divides.

### Price paid on a selected row

`DealSearchPanel` renders an inventory row's price as
`item.sticker_price ?? item.current_market_value`. That is what we would *sell*
it for. When the operator is putting a card into an outgoing leg, the question
they need answered is what it **cost** — that is what decides whether the trade
is worth doing — and `cost_basis` is not rendered anywhere on that surface.

### A typo in the ledger is permanent

RFC 0010 T11 gave sales a correction path, and it is deliberately a **void**, not
a delete or an edit: a mistaken sale is reversed, the row stays readable, and
every aggregate stops counting it.

A void is the right tool for *"this sale did not happen"*. It is the wrong tool
for *"this sale happened, I typed $150 instead of $105"* — voiding and re-entering
loses the original date, the batch grouping, and the item's timeline continuity,
and it leaves a struck-through phantom in the archive that misrepresents what
occurred. There is currently no other tool.

### Detail

The owner's answer to "what's missing" was direct:

> All of the stats related to the cards at purchase (market price @ purchase,
> market @ purchase / price paid, cost basis, profit, and any more if you think of
> anything else since the more information the better).

## Owner decisions (recorded 2026-09-02)

1. **Editable transaction fields:** amount, date, payment method, fee, show,
   notes. **Not** `item_id` and **not** `type` — rejected explicitly ("full
   re-pointing … a re-pointed leg silently rewrites two items' histories").
   Rejected also: money-and-date-only, as too narrow for real typos.
2. **`cost_basis` follows a corrected purchase amount automatically.** Rejected:
   ledger-only edits (which leave a wrong basis on the item forever), and a
   per-edit checkbox.
3. **Percent is hidden under customer view.** Market is not.

## Detailed Design

### 1. The acquisition ratio — one authority per side

**Backend:** `backend/src/merlins_collection/services/acquisition.py`

```python
def acquisition_ratio(item) -> Decimal | None:
    """``market_value_at_purchase / cost_basis``, as a PERCENT.

    The owner's "market @ purchase / amount paid" — 312 means we paid $32 for a
    card the market said was worth $100 at the time.

    ``None`` when either figure is absent, or when ``cost_basis`` is zero. A
    free card (a throw-in, a bulk lot) is a real and routine thing at a buy
    table, and its ratio is not "infinite" or "0" — it is undefined, and
    rendering either number would be a claim nobody made. Every caller must
    handle ``None`` and render an em dash.
    """
```

**Frontend:** `frontend/lib/acquisition.ts` — `acquisitionRatio()`, the same rule,
plus `formatRatio()` and `ratioTone()`.

Two implementations, deliberately, in the same shape as `itemTitle` /
`adminItemName` / `admin_item_name` / MCP's `toCard` — one rule, several
implementations, kept in sync on purpose. **`mcp-server/src/condition-pricing.ts`
is the cautionary precedent here**: CLAUDE.md records it claiming cross-language
pinning that no test ever actually checked. So this pair gets a real cross-boundary
test, in `backend/tests/test_cross_boundary.py`'s existing style — a shared table
of `(market, cost, expected)` cases asserted on both sides, including the zero-cost
and both-absent rows.

**Tone bands**, defined once in `ratioTone()` and nowhere else:

| Ratio | Tone |
|---|---|
| ≥ 200% | good |
| 100–200% | neutral |
| < 100% | bad — we paid over market |
| `null` | no chip at all, not a grey zero |

### 2. Deal-surface display

**`DealRowCard`** (`frontend/components/admin/deal/DealCardRow.tsx`) gains:

```ts
marketValue?: string | number | null   // market @ purchase for an owned item;
                                       // catalog market for a search result
pricePaid?: string | number | null     // cost_basis — owned items only
showRatio?: boolean                    // false under customer view
```

`DealCardRow` renders a third line under the existing name/meta pair:

```
Charizard
Base Set · #4 · Rare Holo
Market $100.00 · Paid $32.00 · 312%
```

**Rules that already exist and must not be broken:**

- **An absent figure is `—`, never `$0.00`, never blank, never a guess.**
  `priceText` already returns `null` for absent; the new fields use it.
- **A catalog price is a Near Mint market figure and is not condition-adjusted.**
  It is labelled `market` and never presented as a sale price. The existing
  `priceLabel` mechanism carries this.
- **Identity is needed continuously, not once.** These fields appear on search
  results *and* on staged rows *and* in the confirm dialog — the same rule that
  put the image on staged rows.
- **No hover carries information.** The third line is always rendered.

**Where each figure comes from:**

| Row kind | market | price paid | ratio |
|---|---|---|---|
| Catalog search result (Buy/Trade in) | `display_price` — the backend's finish-aware `_market_price(card, "normal")`. **Never re-implement the finish walk in the frontend.** | absent | absent |
| Owned inventory row (Sell/Trade out) | `market_value_at_purchase` | `cost_basis` | computed |
| Staged incoming leg | the `market_value` already carried on `IncomingLeg` | the agreed value being typed | computed live as the value changes |
| Staged outgoing leg | `market_value_at_purchase` | `cost_basis` | computed |
| Manual entry | absent | the typed value | absent |

**`DealSearchPanel` must fetch the two new fields for inventory rows.** It
currently renders `item.sticker_price ?? item.current_market_value`. Add
`cost_basis` and `market_value_at_purchase` — both are already returned by
`/admin/inventory/search`; the panel just does not read them.

> **An owned-inventory deal row now carries three money figures, and one of them
> is the primary.** The existing headline price (`sticker_price ??
> current_market_value`) is **what we would sell it for** and stays the row's
> primary, rendered as it is today. `Market` and `Paid` on the new third line are
> **context for the deal**, rendered smaller and labelled. Three unlabelled
> numbers on one row is worse than the one number the operator has now — the
> labels are what make this an improvement rather than a puzzle.

**Customer view.** `customerView` already exists as page state on
`/admin/trade` and is already threaded into `DealSummary`, which suppresses
profit. Thread the **same prop, by the same name** into `DealSearchPanel`,
`DealStagedColumn` and `DealCardRow`.

> **Under customer view: the ratio is hidden and `Paid` is hidden. `Market` stays
> visible.** Price paid is our cost basis — showing a customer that we paid $32
> for the card we are trading them at $100 is strictly worse than showing them the
> margin percentage, and the owner's instruction to hide "percent" plainly means
> "hide what tells them our margin". Recorded as a decision rather than escalated:
> it is the conservative reading and it is trivially reversible.

### 3. `PATCH /admin/transactions/{txn_id}`

Lives beside the four void/restore routes in `routers/admin/analytics.py`, under
**the same admin dependency they already carry** — a new write route on the admin
router inherits nothing by being nearby, and this one edits the ledger.

```
PATCH /admin/transactions/{txn_id}
  body: any subset of { amount, date, payment_method, fee, show_id, notes }
  200 -> the updated transaction + { "cost_basis_updated": bool,
                                     "cost_basis_skipped_reason": str | null }
  400 -> the transaction is a TRADE leg
  404 -> unknown txn_id
  409 -> the transaction is VOIDED
  422 -> a field outside the allowed set, or an unreadable value
```

#### 3.1 What is refused, and why each refusal is deliberate

- **`item_id`, `type`, `category`: 422.** Owner-scoped out. Re-pointing a leg
  rewrites two items' histories from one edit, and the correct expression of "this
  was the wrong card" is a void plus a fresh entry.
- **A voided transaction: 409.** Editing a row that counts toward nothing is
  meaningless and the resulting audit trail would be incoherent. Restore first.
- **A trade leg: 400.** This mirrors — and is the same reasoning as — the existing
  rule that a trade cannot be voided at all. A trade's legs share a `batch_id` and
  its incoming basis was allocated pro-rata by `_compute_basis_pool` at confirm
  time from *all* the legs together. Changing one leg's amount would leave the
  stored allocation silently inconsistent with the inputs that produced it, and
  re-running the allocation would rewrite cost bases on items that may since have
  been sold, re-priced or consigned. **A mistaken trade still has no correction
  path.** That is a real, recorded limitation, exactly as the void feature records
  that a mistaken buy has none.

#### 3.2 A date change is a delete-and-rewrite, in one transaction

Keys are `PK = TXN#<YYYY-MM>`, `SK = <ISO date>#<txn_id>`
(`InventoryRepository._txn_keys`), plus `GSI2PK/GSI2SK` when a `show_id` is set.
**The date is in both the partition key and the sort key.** So:

- **Same date:** `put_transaction` alone. It whole-item `put_item`s, so a removed
  `show_id` correctly drops the GSI2 attributes with no special handling.
- **Different date:** delete the old key and put the new one in **one**
  `transact_write_items`. Never two calls. A half-applied date change either
  duplicates the transaction across two months or deletes it outright, on the
  ledger, which is the partial-write class `reverse_sales` was built to eliminate.

The delete is guarded by `attribute_exists(SK)` so a concurrent void or a stale
client cannot make the edit land on a row that moved underneath it.

#### 3.3 The audit trail is server-stamped

Three new fields on `Transaction`, all optional with `None` defaults so every
existing row still validates and **nothing is backfilled**:

```python
edited_at: datetime | None = None
edited_by: str | None = None          # `email or username or sub`, SERVER-side
edit_history: list[TransactionEdit] = Field(default_factory=list, max_length=20)
```

`TransactionEdit` is `{at, by, changes: [{field, old, new}]}` — **one entry per
EDIT, not per changed field.** A six-field correction is one thing that happened,
and capping at 20 *fields* would mean three corrections exhaust the history.
Oldest entries drop past 20 edits. The bound is not decoration — this rides in a
DynamoDB item with a 400 KB ceiling, the same reason `review_reason` and
`void_reason` are bounded.

**`edited_by` is never client-supplied**, exactly like `voided_by`. A client's
claim about who edited a ledger row is not evidence, and this is the one field
whose whole purpose is accountability.

#### 3.4 `cost_basis` follows a corrected purchase amount

Owner decision. When a **purchase** leg's `amount` changes:

- Load the referenced item. If it no longer exists → skip, report
  `cost_basis_skipped_reason: "item not found"`.
- **Guard on equality: only update when the item's current `cost_basis` equals the
  transaction's OLD amount.** If someone has already hand-corrected the item, the
  ledger edit must not silently overwrite their correction — report
  `cost_basis_skipped_reason: "cost basis was changed manually since"` and let the
  UI say so.
- The item write joins the **same `transact_write_items`** as the ledger write, so
  the ledger and the item can never disagree.
- **Sales do not touch `cost_basis`.** A sale's `amount` is revenue; the basis was
  set at acquisition and a sale correction has nothing to say about it.
- A consigned item's basis is typically zero and the equality guard handles it
  naturally — if the old amount was zero and the basis is zero, it follows; if not,
  it is skipped and reported.

> **RFC 0022 makes the skip path COMMON, not rare.** Once `cost_basis` is
> click-to-edit on six admin tables, an admin correcting the item directly is an
> ordinary thing to do — and every such correction breaks the equality the guard
> checks, so the next ledger edit skips. That is the guard working correctly, and
> it means `cost_basis_skipped_reason` is a normal outcome the dialog must render
> plainly ("the item's cost basis was changed by hand since; it was left alone"),
> not an error state tucked behind a warning icon.

#### 3.5 Downstream consequences the edit must handle

- **One timeline event per transaction, keyed `<txn_id>#edit`, re-put rather than
  appended.** The original sale event is keyed `TIMELINE#<date>#<txn_id>`, so a
  same-day edit — the common case, a typo caught minutes later — would otherwise
  **overwrite the sale itself**. This is the exact rule the void feature already
  follows and it is not optional.
- **`ShowAnalyticsSnapshot.stale = True`** for any affected show, reusing the path
  void already uses. If the date moved between shows, both are marked.
- **`services/ledger.is_countable` is untouched.** An edited transaction is still
  countable; nothing about the void semantics changes. **Do not add an
  `edited_at is None` check to any aggregate** — countability has exactly one
  definition and the failure mode of a second one is two sets of books disagreeing.

#### 3.6 UI

A per-leg **Edit** action in `SaleDetailModal` (which already carries per-leg
void/restore) opening a small dialog — **not** an inline cell.

The reason it is a dialog and not an RFC 0022 inline edit: an amount change here
has a side effect on another entity (`cost_basis`), can move a row between
DynamoDB partitions, and marks a report stale. That deserves a surface that can
show the operator the `cost_basis_skipped_reason` when it comes back, and a
one-line cell cannot.

Dialog rules: `MoneyInput` for amount and fee (never `type="number"`, never
`parseFloat`); `lib/dates.ts` for the date (never `new Date()` on a date-only
string); a `useShows()` select for the show; `vault-field` on everything.

**The popup must key on group identity, not a captured object.** `SaleDetailModal`
already learned this — it stores the group's `key` and re-derives from `groups`
each render, because a void from inside the open popup triggers a refetch that
rebuilds every group as a new object. An edit does the same thing. Do not
regress it.

### 4. Richer transaction detail

`POST /admin/inventory/items-brief` gains four fields per item:

```
cost_basis, market_value_at_purchase, acquisition_ratio, current_market_value
```

**This deliberately contradicts that endpoint's current docstring**, which says it
does not return a price because "the transaction leg's own `amount` is the
authoritative sold/bought figure the caller already has, and echoing a second copy
here (current_market_value? cost_basis?) would just be a figure that can drift
from the one that matters."

That reasoning is right about the fact it names and does not cover these fields.
`amount` remains the sole authority for **what this leg was worth** and nothing
here echoes it. `cost_basis` and `market_value_at_purchase` are **different facts
about a different moment** — what the card cost us, and what the market said when
we bought it. They cannot drift from `amount` because they are not claims about
`amount`. **Update the docstring to say exactly this**, so the next reader does not
see a contradiction and "fix" it back.

`acquisition_ratio` is computed server-side by `services/acquisition.py` and
returned, rather than divided in the client — same reasoning as `display_price`:
one authority, and the client already has to handle a `null`.

**Leg profit** is `amount - cost_basis` for a sale, rendered in
`SaleDetailModal` and on History's per-leg rows. It is **display-only and
computed at render**, never stored: History already computes `step_profit` per
lineage hop with a guard against a $0 cost basis overstating profit on consigned
items, and that guard applies here identically. Reuse it; do not write a second
one.

The cap-at-100 and null-not-omitted response shape is unchanged.

## API Contracts

```
PATCH /admin/transactions/{txn_id}
  body: subset of { amount, date, payment_method, fee, show_id, notes }
  200 -> { ...transaction, cost_basis_updated: bool,
           cost_basis_skipped_reason: string | null }
  400  the transaction is a trade leg
  404  unknown txn_id
  409  the transaction is voided
  422  a disallowed field, or an unreadable value

POST /admin/inventory/items-brief          (extended, not new)
  -> per item: { name, card_id,
                 cost_basis, market_value_at_purchase,
                 acquisition_ratio, current_market_value }
```

`Transaction` gains `edited_at`, `edited_by`, `edit_history`.
No inventory model field is added — `market_value_at_purchase` already exists.

## Alternatives Considered

**Void-and-re-enter as the correction path.** It is what exists, and it is wrong
for a typo: it loses the original date, breaks the `batch_id` grouping, breaks the
item's timeline continuity, and leaves a struck-through phantom in the archive
that says a sale did not happen when it did.

**Allow editing `item_id`.** Declined by the owner and it is the right call — one
edit would rewrite two items' histories with no diff surface.

**Allow editing trade legs.** Rejected: `_compute_basis_pool` allocated the
incoming basis pro-rata across all legs at confirm time, so a single-leg amount
change leaves the stored allocation inconsistent with its own inputs, and
re-running it would rewrite cost bases on items that may have moved on.

**Compute the ratio in the frontend only.** Cheaper, and it would put a second
implementation of a money rule on the client with nothing pinning it — the exact
shape CLAUDE.md records for `condition-pricing.ts`'s unchecked parity claim.

**Store `acquisition_ratio` on the item.** A derived value that would go stale the
moment either input is corrected — including by this RFC's own `cost_basis` sync.

**An `edited` filter on the archive.** The archive's whole point is to show what
was written. `edit_history` is on the row for anyone who wants it.

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| **A date edit half-applies and duplicates or loses a ledger row.** | One `transact_write_items` for the delete + put, guarded by `attribute_exists`. Never two calls. |
| **A `cost_basis` sync overwrites a human's correction.** | The equality guard: only follow when the item's basis still equals the transaction's OLD amount. Otherwise skip and report the reason to the UI. |
| **The edit event overwrites the original sale's timeline entry.** | Keyed `<txn_id>#edit` and re-put, never appended — the identical rule the void feature already follows for the identical reason. |
| **An aggregate starts excluding edited rows.** | `is_countable` is untouched and nothing may inline a second countability check. Its module docstring enumerates its readers exhaustively; add nothing to that list. |
| **The two ratio implementations drift.** | A real cross-boundary test over a shared case table, in `test_cross_boundary.py`'s existing style — not a docstring claiming parity. |
| **A `$0` cost basis produces `Infinity%` or a fake `0%`.** | `acquisition_ratio` returns `None` for a zero or absent basis, and every caller renders an em dash. Pinned on both sides. |
| **Customer view leaks the margin.** | Both the ratio *and* the price paid are suppressed; only market stays. |
| **Money reaches DynamoDB as a bare `float`.** | `_serialize` coerces, and the edit path's tests send JSON **numbers**, not strings — the repo's habit of sending money as strings is exactly why a production 500 went unnoticed for months. |

## Adversarial review findings (2026-09-02)

1. **Correctness — the first draft updated a moved transaction with two calls.**
   The date is in both the PK and the SK, so a delete+put across two calls can
   duplicate or destroy a ledger row. Collapsed into one `transact_write_items`.
2. **Logic — the `cost_basis` sync had no guard.** As drafted it would silently
   overwrite a hand-correction an admin had already made on the item. Added the
   equality guard plus a reported skip reason, because a silent skip is as bad as
   a silent overwrite.
3. **Correctness — the timeline event would have overwritten the original sale.**
   The sale event is keyed `TIMELINE#<date>#<txn_id>` and a same-day edit is the
   common case. Keyed `<txn_id>#edit` and re-put, matching void.
4. **Logic — trade legs were editable in the first draft.** `_compute_basis_pool`
   allocates incoming basis across all legs at confirm; a single-leg edit leaves
   that allocation inconsistent with its inputs. Refused with a 400, and the
   limitation recorded rather than hidden.
5. **Consistency — `items-brief`'s docstring explicitly forbids what §4 does.**
   Rather than quietly contradicting it, the RFC distinguishes "a second copy of
   `amount`" (still forbidden) from "different facts about a different moment"
   (added), and requires the docstring be updated to say so.
6. **Bloat — the first draft stored `acquisition_ratio` on the item and added a
   backfill script.** Cut. It is derived, it would go stale the instant either
   input changed — including from this RFC's own `cost_basis` sync — and the
   inputs are already stored.
7. **Security/UX — the first draft hid only the percent under customer view.**
   Showing "Paid $32" to a customer buying at $100 is worse than showing them the
   percentage. Both are suppressed.
8. **Chaos — an edit from inside `SaleDetailModal` triggers a refetch that
   rebuilds every group object.** The modal already keys on the group's id and
   re-derives; the new edit action must not reintroduce a captured object.
9. **Cross-RFC — RFC 0022 turns the `cost_basis` skip into the common case.** Once
   `cost_basis` is inline-editable everywhere, the equality guard fires routinely.
   `cost_basis_skipped_reason` is therefore an ordinary, expected outcome and must
   be rendered as plain information, not as an error.
10. **Bloat/logic — `edit_history` was capped per FIELD, not per EDIT.** A
    six-field correction would have consumed nearly a third of the history.
    Restructured to one entry per edit carrying a `changes` list.

## Open Questions

None blocking.
