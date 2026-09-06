# RFC 0024 — Acquisition Economics & Transaction Editing: PROGRESS

**Read this first.** State of the world for anyone picking up a task.

**This file is the tracked progress file — not `claude-progress.md`.**

**Last updated:** 2026-09-03 — T2 done (unattended Round 9 run)
**Branch:** `feat/round9-rfcs-0021-0025`
**RFC:** [`../../rfcs/0024-acquisition-economics-and-transaction-editing.md`](../../rfcs/0024-acquisition-economics-and-transaction-editing.md)
**Task index:** [`README.md`](README.md)
**Round guide:** [`../round9/README.md`](../round9/README.md)

## Status

| Task | State |
|---|---|
| T1 `acquisition_ratio` both sides | **DONE** |
| T2 Deal-row market / paid / ratio | **DONE** |
| T3 `PATCH /admin/transactions/{txn_id}` | **DONE** |
| T4 Transaction edit dialog | **DONE** |
| T5 Richer transaction detail | **DONE** |
| T6 Docs + verification | **DONE** |

## RFC 0024 — COMPLETE, 2026-09-03. Committed on `feat/round9-rfcs-0021-0025`.

## T6 — done, 2026-09-03

**Docs:** Added two new CLAUDE.md sections beside the existing void section —
"A TYPO IN THE LEDGER GETS A DIFFERENT TOOL THAN 'THIS DID NOT HAPPEN' — EDIT,
NOT VOID" (the PATCH endpoint, its refusals, the cost_basis sync and its skip
reason, the dialog) and "THE ACQUISITION RATIO — market at purchase over what
we paid, one authority per side" (the ratio, its tone bands, what customer
view hides). Both inserted immediately after the existing void content and
before the (unrelated) Cosigners paragraph that happened to live under the
same header.

**Full-suite verification, run at the RFC boundary per the round guide:**

| Suite | Result |
|---|---|
| `backend/.venv/bin/python -m pytest backend/tests -q` | **2359 passed** |
| `npm test --workspace=frontend` | **1282 passed**, 114 files |
| `npm test --workspace=mcp-server` | **101 passed**, 8 files |
| `npm test --workspace=infra` | **44 passed**, 7 files |
| `npx tsc --noEmit` (frontend) | clean |
| `npm run lint` (frontend) | clean (2 pre-existing unrelated warnings) |
| `ruff check backend/src` | clean |

**One real regression caught by the full-suite run, fixed before closing this
task:** `test_transactions_sort.py::TestRegistryIsTotal` — RFC 0013's
"every `Transaction` field is sortable or explicitly excluded" totality test
failed on the three new T3 fields (`edited_at`, `edited_by`, `edit_history`),
exactly as CLAUDE.md's "SORTING IS UNIVERSAL" section says it should: *"A new
model field fails a test rather than silently arriving without a sort or a
filter."* Fixed by adding all three to `NOT_SORTABLE` with a reason (the same
class as the existing `voided_at`/`voided_by`/`void_reason` exclusion:
metadata rendered inline on a leg/detail popup, not an archive column to sort
a whole table by) — not by adding a sort field, since nothing in this RFC
asked for "sort the archive by most-recently-edited" and inventing that
sort would be scope creep the task never asked for. This is exactly why the
round guide asks for a full-suite run at each RFC boundary rather than only
the narrow per-task selection: T3's own narrow test run (`test_analytics.py`
et al.) could never have caught a totality test living in a different file
entirely.

RFC 0024 is fully done. **Committing this RFC on `feat/round9-rfcs-0021-0025`
now**, then continuing to RFC 0025 (T1 + T5 only, per this session's
instructions).

## T5 — done, 2026-09-03

**Files:** `backend/src/merlins_collection/routers/admin/inventory.py`
(`/items-brief` gains 4 fields + docstring rewrite),
`backend/tests/routers/admin/test_inventory.py` (updated 2 existing
exact-equality assertions to match the new shape, added 2 new tests), new
`frontend/lib/leg-profit.ts` + test, new
`frontend/components/admin/shared/ProfitBadge.tsx`,
`SaleDetailModal.tsx` (renders `ProfitBadge` for a sale leg),
`app/(admin)/admin/history/page.tsx` (`renderStepProfit` now calls the same
shared `ProfitBadge` instead of owning a second copy of the guard).

Outside-in TDD: RED confirmed on the backend (existing `items-brief` tests'
exact-equality assertions failed the moment the four new keys were added —
real, because they failed on the OLD code's shape mismatch expectation
inverted: I updated the assertions and ran them against the not-yet-touched
endpoint first to confirm they failed for the right reason, then implemented),
then GREEN (10/10 `TestAdminItemsBrief`, 187/187 across the touched backend
files). RED confirmed on the frontend for `computeLegProfit` (module not
found), then GREEN (5/5). `TransactionGroups`/History integration tests
written and run before wiring `ProfitBadge` into either page, RED confirmed
via new assertions failing against the old render output, then GREEN (42/42
across both files). `npx tsc --noEmit` and `npm run lint` clean;
`ruff check backend/src` clean (`ruff check` on the test file surfaced 6
pre-existing errors unrelated to this task, confirmed via `git stash` — same
errors present before this session's changes, left untouched as out of
scope).

### Decisions made autonomously during T5 (with rejected alternatives)

- **The four new money fields are stringified explicitly
  (`str(cost_basis) if cost_basis is not None else None`), not returned as
  raw `Decimal`.** The endpoint returns a plain `dict`, not a Pydantic model,
  so FastAPI's default encoder would otherwise round-trip a `Decimal` through
  `float` — the exact precision loss CLAUDE.md's money rules exist to
  prevent. Mirrors `slabs_sort.py`'s `_slab_row()`, which CLAUDE.md already
  documents doing the same thing for the same reason.
- **The endpoint's docstring is REWRITTEN, not just appended to** — the old
  text's "echoing a second copy here… would just be a figure that can drift"
  reads broadly enough to forbid the new fields too. Per the RFC's explicit
  instruction ("say that in the docstring, or the next reader will 'fix' it
  back"), the new docstring names the distinction directly: `amount` is a
  claim about what a leg was WORTH, the four new fields are different facts
  about a different moment, and cannot drift from `amount` because they were
  never claims about it.
- **`ProfitBadge` is a NEW shared component, and History's `renderStepProfit`
  was refactored to call it** rather than leaving History's copy alone and
  writing a second, similar-looking guard inside `SaleDetailModal`. The RFC
  said "reuse that guard, do not write a second one" — literally reusing
  `renderStepProfit` wasn't possible (it's a closure over `LineageNode`,
  History's own type, not `ItemBrief`), so the guard itself (the
  "$0-cost-basis-may-overstate-profit" rendering: color, sign, warning icon)
  was extracted into the one component both callers now render, while each
  caller keeps computing ITS OWN inputs from its own data shape
  (`node.step_profit`/`node.acquired_cost` for History,
  `computeLegProfit(leg.amount, brief.cost_basis)` for `SaleDetailModal`).
  Rejected: leaving History untouched and duplicating the render logic in
  `SaleDetailModal` — that is exactly the "two implementations that can
  drift" shape the RFC's instruction was written to prevent.
- **Leg profit renders ONLY for `leg.type === 'sale'`** in
  `SaleDetailModal` — a purchase leg's `amount` IS the cost, so "profit" on
  it is a meaningless figure, not merely an uninteresting one. Matches the
  RFC's own "Leg profit is `amount - cost_basis` for a sale" wording exactly
  rather than rendering (and then hiding) a badge for every leg kind.
- **The two updated `TestAdminItemsBrief` assertions that don't care about
  the new fields were loosened to check only `name`/`card_id`** (via
  `body["x"]["name"] == ...` instead of a full dict equality), while the ones
  that exist specifically to pin the exact response SHAPE (the sealed-item
  test, the display-name-override test) were updated to assert the complete
  new dict. Rejected: updating every test to a full literal dict — a test
  whose entire point is "does name resolution fall back correctly" gains
  nothing from also re-asserting four fields it isn't about, and it makes
  that test brittle to a future field addition that has nothing to do with
  names.

## T4 — done, 2026-09-03

**Files:** new `frontend/components/admin/shared/TransactionEditDialog.tsx` +
its test file, `SaleDetailModal.tsx` (Edit button per live leg, `EditedNote`),
`TransactionGroups.tsx` (`onEdit` prop, `editingLeg`/`editBusy`/`editError`/
`costBasisSkippedReason` state, wiring), `app/(admin)/admin/analytics/page.tsx`
(`handleEditTransaction`).

Outside-in TDD: wrote the dialog + its test file together (7 tests, green on
first run — a small, self-contained new component with no ambiguity to
explore via RED first); then wrote the `TransactionGroups`/`SaleDetailModal`
integration tests FIRST against the pre-wiring code, confirmed a real RED (30
of 30 `TransactionGroups` tests failed — the whole suite crashed with
`onEdit is not defined`, because the wiring pass added `onEdit` to the
destructured prop TYPE annotation but not to the actual destructured
parameter list, a real bug the RED run caught before any assertion ran), then
GREEN (37/37). Verified: `npx tsc --noEmit` clean,
`npx vitest run "app/(admin)/admin/analytics" components/admin/shared` — 247
passed across 16 files including the pre-existing
`app/(admin)/admin/analytics/__tests__/page.test.tsx` (19 tests, no
regression), `npm run lint` clean (two pre-existing unrelated warnings only).

### Decisions made autonomously during T4 (with rejected alternatives)

- **The dialog sends only fields that changed from the leg's OWN current
  value**, computed by re-deriving each field's canonical form
  (`moneyField`) and comparing — never the whole form. Matches the backend's
  own no-op handling (T3: a value matching what's stored produces no audit
  entry) and avoids resending, say, an unedited `payment_method` on every
  amount-only correction.
- **On a successful save, the dialog auto-closes UNLESS the response carries
  a `cost_basis_skipped_reason`**, in which case it stays open with the
  reason rendered via `role="status"` (not `role="alert"` — CLAUDE.md's own
  rule elsewhere in this file: "the item's cost basis was changed by hand
  since; it was left alone" is plain information, not an error, and RFC 0022
  made this the COMMON outcome once `cost_basis` is inline-editable
  everywhere). Rejected: always auto-closing and relying on a toast — a
  toast that vanishes in 5 seconds is a worse surface for information the
  operator specifically needs to read and act on (the ledger IS corrected;
  only the item's basis wasn't) than a dialog staying open until dismissed.
- **`editingLeg` is a captured object, unlike `modalGroupKey`'s
  key-and-re-derive pattern**, and this is deliberately NOT the same
  fix — the RFC's own "do not regress the popup's identity keying" warning
  is about `SaleDetailModal`'s `modalGroupKey`, which stays untouched. A
  successful edit closes `TransactionEditDialog` immediately (or shows the
  skip reason using the value already in hand), so there is no window where
  a captured stale object could mislead an operator the way a still-open
  `SaleDetailModal` could after a void from within it.
- **`payment_method` is a plain text input, not a `<select>`.** The four
  options `DealSummary.tsx` hardcodes (`cash`/`venmo`/`zelle`/`card`) are
  local to that file, not exported, and `Transaction.payment_method` has no
  backend-side enum constraint. Rejected: duplicating `DealSummary`'s local
  constant into a second file for a dialog whose whole purpose is fixing a
  typo — a free-text field can fix any typo including one in a value outside
  that fixed list (a business's real payment methods are not obviously
  closed to those four).
- **The date field binds the ISO string directly to a native
  `<input type="date">`, with no `Date` object anywhere in the component.**
  This satisfies CLAUDE.md's "never pass a date-only string to `new Date()`"
  rule by construction rather than by discipline — there is no call site for
  the bug to hide in. The test file still pins a negative-offset TZ via
  `_timezone.ts` per the task brief's instruction, even though nothing in
  this component currently depends on it, as a guard against a future edit
  reintroducing a `Date` conversion without updating the test.

## T3 — done, 2026-09-03

**Files:** `backend/src/merlins_collection/models/business.py` (new
`TransactionFieldChange`/`TransactionEdit`, `Transaction.edited_at`/
`edited_by`/`edit_history`), `backend/src/merlins_collection/services/dynamodb.py`
(new `edit_transaction`, new `TransactionEditConflictError`),
`backend/src/merlins_collection/routers/admin/analytics.py` (new
`PATCH /admin/transactions/{txn_id}`), new
`backend/tests/routers/admin/test_transaction_edit.py` (17 tests).

Outside-in TDD: wrote the model/service/router code and the test file in the
same pass (the model+service+router are one cohesive unit with no meaningful
partial-implementation midpoint — unlike T2's per-component row-by-row
build). The first full test run was a genuine RED, and a useful one: a
`TypeError` at import time, not a test assertion failure — Python 3.14's
deferred annotation evaluation resolves a class's own field named `date`
against the class's own namespace once that field exists, so
`date: date | None` self-shadowed into `None | None`. Confirmed real (all 17
tests errored at collection, not just one), fixed by aliasing the import
(`from datetime import date as _date_type`) exactly the way
`models/business.py` already does for `Transaction.date` — then GREEN, 17/17.
Adversarial-review pass after: verified the cost_basis equality guard is
read-then-reconfirmed (not read-only), verified the ledger PUT correctly
carries no optimistic-concurrency guard of its own (see decisions below),
verified `is_countable` needed no changes. Full re-run of
`test_transaction_edit.py` + `test_transaction_void.py` +
`test_analytics.py` + `test_acquisition.py` + `test_cross_boundary.py`: 86
passed. `ruff check backend/src` clean.

### Decisions made autonomously during T3 (with rejected alternatives)

- **The main ledger `Put` in `edit_transaction` carries no
  `ConditionExpression` of its own** — only the cross-month `Delete` (guarded
  by `attribute_exists(SK)`) and the optional `cost_basis` `Update` (guarded
  by equality) are conditioned. A concurrent double-edit is last-write-wins,
  same as an ordinary `put_item`. Rejected: adding an optimistic-concurrency
  guard (e.g. re-checking the row's prior state) — the RFC's contract table
  lists exactly four refusals (voided/trade-leg/unknown-id/disallowed-field)
  and does not ask for one, void's own reversal guards exist to prevent a
  *specific* named hazard (double-voiding, resurrecting a moved item) that an
  edit-race does not share, and inventing a fifth guard the RFC never
  specified is scope creep for a low-traffic admin-only write path.
- **A no-op edit (every provided field already matches what's stored) skips
  the audit trail, timeline event and staleness marking entirely** rather
  than recording a vacuous entry. Not explicitly specified either way in the
  RFC. Rejected: always stamping `edited_at`/`edited_by` and appending an
  empty-`changes` history entry regardless — that would make "was this ever
  actually edited" unanswerable from the row itself, and would burn one of
  the 20-entry history slots on nothing.
- **`amount`/`date`/`payment_method`/`fee` reject an explicit `null` with a
  422** (`_NON_NULLABLE_EDIT_FIELDS`), while `show_id`/`notes` accept one (to
  clear them). Not explicit in the RFC's contract table. Rejected: silently
  accepting `null` on a required field and letting `Transaction`'s own
  construction fail — `model_copy(update=...)` does **not** revalidate in
  Pydantic v2, so an unguarded `null` there would have produced a `Transaction`
  instance with a type-invalid `amount=None` that no validator would ever
  catch until something downstream tried to use it as a `Decimal`.
- **`_mark_snapshots_stale` is called once with the OLD transaction state and
  once with the NEW one**, rather than writing a second, edit-specific
  staleness resolver. It already computes "the transaction's own show, plus
  every show whose date matches", so calling it twice (old date/show, new
  date/show) covers the "both, if the date moved between shows" case for
  free, deduplicated by the function's own `if not snapshot.stale` guard.
- **The trade-leg refusal is checked via `old_txn.trade_id is not None`**,
  the same field void's own batch grouping already keys on, rather than
  inventing a second way to detect a trade leg (e.g. `type == PURCHASE and
  category == ...`). One field, one meaning, reused.

## T2 — done, 2026-09-03

**Files:** `frontend/components/admin/deal/DealCardRow.tsx`,
`DealSearchPanel.tsx`, `DealStagedColumn.tsx`, `IncomingCardForm.tsx`,
`frontend/app/(admin)/admin/trade/page.tsx`, plus new/extended tests in
`components/admin/deal/__tests__/` (`DealCardRow`, `DealSearchPanel`,
`IncomingCardForm`, and a new `DealStagedColumn.test.tsx` — that component had
no direct unit tests before this task).

Outside-in TDD per file: RED confirmed for each (new assertions failing
against the pre-change component), GREEN, adversarial-review pass across the
whole set at the end (logic/chaos/bloat — no security surface here). Verified:
`npx vitest run components/admin/deal app/\(admin\)/admin/trade` — **80
passed**, 6 files, including the pre-existing "removes cost basis and profit
from the DOM in customer view" trade-page test (no regression).

### Decisions made autonomously during T2 (with rejected alternatives)

- **`DealRowCard.marketValue`/`pricePaid` use `undefined` vs `null` as two
  distinct signals**, not one. `undefined` on both means this row kind
  doesn't carry the acquisition concept at all (manual entry with no market
  figure and no staged pair) — the whole third line is omitted. `null` means
  the figure is genuinely absent for a row kind that DOES carry the concept —
  renders `—`. Rejected: a single `hasAcquisitionData` boolean prop, which
  would have made every caller compute presence itself instead of the
  natural "did I pass this key" signal already used elsewhere in this file
  (`card_id?: string | null`).
- **Customer-view suppression happens at RENDER time in `DealStagedColumn`,
  not baked into the staged row's stored state.** `trade/page.tsx` always
  stores the real `marketValue`/`pricePaid` on `StagedIncoming`/
  `StagedOutgoing` when a card is added; `DealStagedColumn` strips
  `pricePaid` and forces `showRatio={false}` only while `customerView` is
  true. Rejected: filtering at add-time — the operator can flip Customer
  View *after* cards are already staged (it is a page-level toggle, not a
  per-card one), and baking the suppression into `setIncoming`/`setOutgoing`
  would mean the toggle silently stops working for anything already on the
  page.
- **`IncomingCardForm`'s live preview is NOT gated on `customerView`** —
  the RFC's "thread the same prop" sentence names `DealSearchPanel`,
  `DealStagedColumn` and `DealCardRow` explicitly and does not name this
  component, even though the file is in T2's touched-files list (for adding
  the live market/paid/ratio preview itself). Read literally: the live
  in-progress form is filled out before a card is staged or shown to anyone,
  so it was left always-showing. Trivially reversible if the owner meant to
  cover it too — flagged here rather than escalated because the RFC text is
  explicit about which three components share the prop.
- **The catalog-pick preview's headline price and the new third line's
  `Market` figure are the same number, shown twice** (`card.display_price`
  as both). Accepted rather than redesigned: for a not-yet-owned catalog
  card there is no second, different "sell price" concept the headline could
  show instead (unlike an owned inventory row, where the headline is
  today's sticker/market price and the third line's `Market` is the
  *historical* purchase-time figure — those two legitimately differ). The
  duplication is redundant-looking but not incorrect, and inventing a
  different headline scheme for this one row kind was out of scope for a
  task whose brief was "add the fields," not "redesign the headline."

## T1 — done, 2026-09-02

**Files:** `backend/src/merlins_collection/services/acquisition.py` (new),
`frontend/lib/acquisition.ts` (new), `shared/test-fixtures/acquisition-ratio-cases.json`
(new), `backend/tests/services/test_acquisition.py` (new),
`backend/tests/test_cross_boundary.py` (added `test_acquisition_ratio_matches_shared_cases`).

Full outside-in TDD: RED confirmed (module-not-found on both sides, pre-existing
cross-boundary tests stayed green), GREEN, adversarial-review pre- and
post-change (inline, no subagent), REFACTOR (one test renamed/corrected — see
decisions below). Verified: `pytest backend/tests/services/test_acquisition.py
backend/tests/test_cross_boundary.py` (18 passed), `vitest run
lib/__tests__/acquisition.test.ts` (23 passed), ruff clean, eslint clean.

### Decisions made autonomously during T1 (with rejected alternatives)

- **`acquisition_ratio` takes two explicit `Decimal | None` values
  (`market_value_at_purchase`, `cost_basis`), not an `item` object.** The
  RFC's code fence used `item` as illustrative shorthand, but
  `InventoryItem.cost_basis` is a *required* `Decimal` (never `None`) —
  reading `item.cost_basis` literally could never exercise the "cost absent"
  row the RFC's own test-case table demands. Rejected: an `item`-shaped
  parameter with `getattr`/duck-typing, which would hide this mismatch
  instead of surfacing it, and would couple the function to a model shape
  none of its actual callers (T2, T5) need it to have.
- **Both sides round to 2 decimal places before returning**
  (`ROUND_HALF_UP` in Python, `Math.round(x*100)/100` in TypeScript), rather
  than returning full unrounded precision. Rejected: unrounded — Python's
  arbitrary-precision `Decimal` and JS's float64 `Number` disagree past
  common precision on a repeating-decimal division (10/3), which would make
  the shared-fixture cross-boundary pin fail on cosmetic precision drift
  having nothing to do with the actual bug class it exists to catch.
- **The cross-boundary pin is a shared JSON fixture
  (`shared/test-fixtures/acquisition-ratio-cases.json`), loaded independently
  by a Python test and a TypeScript test — not a literal source-regex parse
  (the pattern the rest of `test_cross_boundary.py` uses) and not a Node
  subprocess invoked from pytest.** `acquisition_ratio` is a computed
  function, not a literal constant, so there is no literal answer in the TS
  source for a regex to extract. Rejected: two independently hand-typed
  literal test tables (the exact `condition-pricing.ts` failure shape
  CLAUDE.md already documents — "each side had only its own test with
  independently hardcoded expectations"). Rejected: shelling out to
  `node`/`npx` from the Python test — the module's own docstring commits to
  "no TS compiler needed," and a shared-fixture oracle gives the same
  transitive guarantee (if both suites pass against one file, the two
  implementations agree) without adding a cross-language runtime dependency
  to either suite.
- **The shared fixture lives at `shared/test-fixtures/...`, not `shared/`
  directly.** CLAUDE.md's `shared/` lesson ("for values crossing the
  Python/TypeScript boundary — nothing else") was written about a file with
  *no* actual reader on one side, later found unreachable at runtime in the
  deployed image. This fixture has genuine readers on both sides but is
  test-only — never imported by any runtime module, never needing to survive
  a Docker `COPY` or a package build — a materially different risk profile
  than `shared/tool-contract.json`, which both processes read live. The
  `test-fixtures/` subpath keeps it inside the designated cross-boundary
  directory while keeping it visually distinct from deployment-critical
  entries, so a future audit of `shared/` doesn't have to guess which files
  matter at runtime.
- **A genuine `ROUND_HALF_UP` tie-break case (1/800 → 0.125% → 0.13%) is
  tested Python-only, deliberately excluded from the shared fixture.** 800 =
  2⁵×5² has no finite binary representation, so JS float64 division can land
  either side of the exact tie before `Math.round` runs, while Python's
  `Decimal` division is exact. Putting this case in the shared fixture would
  risk a spurious cross-boundary failure that indicts float representability,
  not either implementation's rounding rule. An earlier draft of this test
  (`market=1.00, cost=8.00`) didn't actually exercise a tie at all (12.5 has
  nothing in the thousandths place) — caught and fixed during the
  post-change adversarial-review pass, before this task closed.
- **Negative `cost_basis` is not special-cased** (only `== 0` short-circuits
  to `None`). Nothing upstream can produce one — `parseMoney` and the
  backend's own money-field validation reject negative amounts before a
  value reaches storage — so adding a sign check here would guard against an
  input class the rest of the system already prevents.

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
