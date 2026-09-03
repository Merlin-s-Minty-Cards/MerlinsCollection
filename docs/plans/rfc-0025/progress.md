# RFC 0025 — Customer Sticker Pricing: PROGRESS

**Read this first.** State of the world for anyone picking up a task.

**This file is the tracked progress file — not `claude-progress.md`.**

**Last updated:** 2026-09-03 — RFC 0025 COMPLETE, all six tasks done
**Branch:** `feat/round9-rfcs-0021-0025`
**RFC:** [`../../rfcs/0025-customer-sticker-pricing.md`](../../rfcs/0025-customer-sticker-pricing.md)
**Task index:** [`README.md`](README.md)
**Round guide:** [`../round9/README.md`](../round9/README.md)

## Status

| Task | State |
|---|---|
| T1 Measure the stickered fraction | **DONE — measured, reported to owner, see below** |
| T2 Sticker rule in the predicate + `_display_price` | **DONE** — owner said "Go ahead" on the T1 number |
| T3 MCP TypeScript mirror | **DONE** |
| T4 Remove condition adjustment from the customer path | **DONE** |
| T5 Remove Est. value + `est_value` | **DONE** |
| T6 Docs + verification | **DONE** |

## RFC 0025 — COMPLETE. This closes out Round 9 (RFCs 0021-0025).

The T1→T2 gate: measured 2026-09-03, reported to the owner (93.9% of
customer-visible stock already stickered — see T1 below), owner responded
"Go ahead" the same session. T2-T4, T6 then proceeded in one continuous pass.

## T1 — done, 2026-09-03 (measured against the LIVE `merlins-cards` table, read-only)

```
table=merlins-cards region=us-east-1
total inventory rows: 373

customer-visible today:            247
   of which have a sticker price:  232   (93.9%)
   of which do not:                15
```

**This is a LARGE fraction, not a small one.** 93.9% of what customers can see
today already carries a sticker price — this RFC's storefront-narrowing effect
is real but small: 15 of 247 currently-visible items (6.1%) would newly become
invisible once `is_customer_visible` requires a sticker. This is NOT the "hides
most of the storefront" scenario the round guide's gate was written to catch;
reported plainly per the instruction regardless, since the gate is procedural
(the owner sees the number before T2, always) not conditional on the number
being alarming.

Method: `InventoryRepository.list_inventory()` (a full table walk, the same
one `measure_admin_chat_latency.py` already uses against this table) filtered
through the existing `services.customer_visibility.is_customer_visible`
predicate, then split on `sticker_price is not None`. No code was written or
committed for this — a one-off read-only script run inline, per the task's
"No code changes" instruction.

## T5 — done, 2026-09-03

**Files:** `frontend/components/inventory/InventoryStats.tsx` +
its test, `frontend/app/(auth)/inventory/__tests__/page.test.tsx`,
`frontend/lib/inventory.ts`, `backend/src/merlins_collection/routers/inventory.py`
(`InventorySummary` + `inventory_summary`), `backend/tests/routers/test_inventory.py`
(deleted 4 tests whose whole purpose was `est_value` behavior, added 1
tripwire test asserting its absence), `backend/README.md` (one-line endpoint
doc, not in the task's file list but directly stale the moment the field
was removed).

Outside-in TDD: RED confirmed on the backend (updated the empty-inventory
exact-equality assertion and the new absence-tripwire test, ran them against
the not-yet-touched endpoint, both failed for the right reason — the field
was still present), then GREEN after removing `est_value` from the model,
the per-item pricing loop, and the now-unused `_market_price` import (8/8
summary tests, 83/83 in the full file). RED confirmed on the frontend
(updated `InventoryStats.test.tsx`'s tile-count/label assertions against the
not-yet-touched component, failed on the stale 3-tile expectation), then
GREEN (4/4, plus the two other touched test files). Full-suite verification:
backend **2356 passed** (2359 minus the 3 net removed), frontend **1282
passed** across 114 files, `npx tsc --noEmit` clean, `npm run lint` clean,
`ruff check` clean on the touched source file.

### Decisions made autonomously during T5 (with rejected alternatives)

- **`mcp-server/` was left untouched**, despite `est_value` appearing in
  `get-inventory-summary.ts` and `calculate-inventory-value.ts`. Verified
  first: both are independent implementations that read
  `repo.listCards()` directly in their own process — neither calls the
  backend's `GET /inventory/summary` REST endpoint at all. The shared name
  and the doc-comment cross-reference ("mirroring the backend's `est_value`")
  are coincidental/explanatory, not a real coupling, so removing the
  backend field breaks nothing there. Matches the RFC T3/T5 task file lists,
  which correctly did not name these files.
- **Four backend tests were DELETED outright rather than adapted** —
  `test_summary_est_value_prefers_market_over_listed`,
  `test_summary_serializes_est_value_as_string`,
  `test_summary_est_value_resolves_through_fallback_finish_chain` (the
  historical Phase 12 D2 regression test) and
  `test_summary_total_uses_condition_adjusted_prices`. Each test's entire
  reason to exist was `est_value` behavior that no longer exists; adapting
  them to assert something else would have produced a test whose name and
  docstring lie about what it checks. Rejected: keeping them as
  `pytest.mark.skip`-with-reason — the RFC's own T5 section already frames
  this as a deliberate contract change with a tripwire test for the
  removal itself, which is a stronger, permanent guard than a skip that
  could bit-rot.
- **`backend/README.md`'s endpoint table was updated even though it wasn't
  in T5's stated file list.** It documented the exact field just removed;
  leaving it standing would be the identical "stale doc nobody comes back
  to fix" failure CLAUDE.md already records twice elsewhere in this repo.
  One line, directly caused by this task's own change — not scope creep.
- **The historical Phase-12 comment block above the deleted fallback-finish
  test (`D2 (Finding 6): inventory_summary's est_value sums...`) was left
  in place**, even though it now describes a bug in code that no longer
  exists. It documents what D1/D3 were and why the surrounding tests (which
  still exist and still pass) were written, and rewriting a historical
  provenance note to erase a fact that was once true would lose more context
  than it saves — CLAUDE.md's `docs/plans/rfc-0009/` PSA precedent makes the
  same call for the same reason ("the record of a decision made properly").

## T2 — done, 2026-09-03

**Files:** `backend/src/merlins_collection/services/customer_visibility.py`
(`is_customer_visible`), `backend/src/merlins_collection/routers/inventory.py`
(`_display_price`), and a much wider test-fixture blast radius than the
task's own file list named — every backend test file that constructs a
customer-visible `RawInventoryItem`/`GradedInventoryItem` needed a
`sticker_price`, since none existed before this RFC. Touched:
`backend/tests/routers/test_inventory.py` (the file's own `_raw`/`_graded`
helpers, plus deletion/replacement of an entire historical test family — see
decisions below), `backend/tests/routers/test_public.py`,
`backend/tests/routers/admin/test_triage.py`, and nine files under
`backend/tests/services/test_display_*.py` /
`test_set_display_state_machine.py` / `test_bedrock_display_tools.py` (the
chat hydration test suite, which shares no fixtures with `test_inventory.py`
— each file has its own local `_raw`/`_item`/`_graded` helper).

Outside-in TDD: RED confirmed first with five new, narrow tests (stickerless
→ invisible, stickered → visible, `_display_price` returns the sticker with
no fallback via a direct unit test rather than through the HTTP wire — see
the first decision below for why, the price bound narrows to the sticker,
`hidden_no_price` is structurally zero) — all five failed against the
pre-change code for the right reason. Implemented `is_customer_visible` +
`_display_price`, then used a full-suite run as the blast-radius finder
rather than trying to enumerate every affected fixture by grep first: the
first full run surfaced 66 failures in `test_inventory.py` alone, which
resolved to 12 once the two shared `_raw`/`_graded` helpers got a default
`sticker_price`, and those 12 were each individually a test of the OLD
market/catalog-fallback mechanism this RFC retired — not something a fixture
default could fix. Full backend suite before moving to T4: 1 failure left
(`test_display_price_derivation.py`, correctly out of scope for T2 — it's
T4's file).

### Decisions made autonomously during T2 (with rejected alternatives)

- **`_display_price` is unit-tested directly (`_enrich` + `_display_price`
  called in-process), not through `GET /inventory/search`'s JSON response.**
  The RFC's own "API Contracts" section pins that endpoint's wire shape as
  "unchanged" — `_display_price`'s result is used ONLY for the filter bound
  and the sort order, and is never written back into the serialized
  `listed_price`/`card.market_price` fields the response actually sends. An
  early draft of this task's test asserted `result["listed_price"] ==
  "25.00"` (the sticker) through the search endpoint and was WRONG — caught
  before it ever ran, by re-reading the RFC's contract section against the
  actual `search_inventory` code, which returns `enriched` items unmodified
  after using `_display_price` only for filtering/sorting. See follow-up #7
  below: this is a real, RFC-scoped gap, not a test bug to paper over.
- **An entire historical test family in `test_inventory.py` was deleted, not
  adapted** — the RFC 0008 §A/T1 "single authority" block (`_live_priced`
  helper + 5 tests) and the Phase 12 "priceless item" block (6 tests), plus
  2 more individual tests (`test_price_filter_matches_on_the_live_catalog_price`,
  2 Phase-14 sort-by-price tests rewritten rather than deleted since sort-by-
  price itself is still a real, tested feature — just no longer against a
  catalog-derived figure). Every deleted test's fixture pattern (`listed_price
  = None`, `current_market_value = None`, relying on `_raw()`'s default
  `sticker_price` to keep the item visible) constructed a scenario —
  "customer-visible item with no resolvable price" — that is now a
  contradiction: `is_customer_visible` requires a sticker, so that item
  cannot exist as a search result at all. Rewriting them to assert something
  else would have produced tests whose names and docstrings lie about their
  own premise; the coverage they existed for (a $517-vs-$500 filter-bound
  divergence, `hidden_no_price` reporting a nonzero count) is superseded by
  `test_hidden_no_price_is_structurally_zero` and a new, much smaller
  `test_price_bound_and_price_sort_agree_on_the_same_figure` in sticker
  terms.
- **`_raw()`/`_graded()` in `test_inventory.py` default `sticker_price` to
  the SAME value as their existing `price` param**, rather than adding a
  second, independent default. Every pre-existing test in that file that
  never mentions "sticker" is testing something else entirely (a name
  filter, a condition filter, a language filter) and needs the item to STAY
  customer-visible with the price behavior it already had — mirroring
  `price` is what makes that automatic. `test_public.py`'s fixtures went the
  OPPOSITE way (a fixed `sticker_price` independent of `market`/`listed`)
  because that file's tests are specifically about the featured endpoint's
  market-based RANKING, which this RFC does not touch — coupling
  `sticker_price` to `market` there would have made ranking assertions
  accidentally depend on visibility fixture values.

## T3 — done, 2026-09-03

**Files:** `mcp-server/src/dynamodb-repository.ts` (`isPublicInventory`, new
`stickerPrice` method, `toCard`'s `value` field), `mcp-server/src/repository.ts`
(`Card.value`/`Card.marketPrice` docstrings), new
`shared/test-fixtures/customer-visibility-cases.json`, new
`backend/tests/test_cross_boundary.py::test_customer_visibility_matches_shared_cases`,
new `mcp-server/src/__tests__/customer-visibility-cases.test.ts`,
`mcp-server/src/__tests__/dynamodb-repository.test.ts` (fixture + 2 test
rewrites — see decisions), `mcp-server/src/tools/get-inventory-summary.ts` +
`calculate-inventory-value.ts` (stale `est_value` doc references from T5,
found while touching adjacent code).

**Landed in the same commit as T2**, per the RFC's own explicit instruction
("A sticker rule applied on three surfaces and not the fourth means the chat
offers a customer a card the search will not show and no price is quoted
for"). RED confirmed (`isPublicInventory` had no sticker check; `toCard`'s
`value` still called the old `marketPrice()`), GREEN, then the cross-boundary
parity test added last (both sides run cleanly on their own before the
shared-fixture pin was added, matching T1's `acquisition_ratio` precedent —
prove each side independently, then prove they agree). Full mcp-server suite:
113 passed across 9 files (up from 8 — the new parity test file).

### Decisions made autonomously during T3 (with rejected alternatives)

- **`Card.value` and `Card.marketPrice` SPLIT into two different
  computations — this is not in the RFC's text and was decided from reading
  the existing code.** `flag_underpriced_cards` compares `card.value`
  (what we charge) against `card.marketPrice` (an external reference) to
  find stock priced below a market threshold — a real, distinct,
  already-shipped feature (one of the five customer MCP tools CLAUDE.md's
  own table names). Collapsing both fields into `sticker_price` would make
  `value < marketPrice * threshold` always compare a number against itself,
  permanently disabling that tool. So: `value` (`toCard`'s `stickerPrice()`
  call) became sticker-only, matching `_display_price`; `marketPrice` KEPT
  its old computation (live catalog price, condition-adjusted, with the
  denormalized/graded/listed fallback chain) unchanged, because it answers
  a genuinely different question ("what does the market say this card, in
  this condition, is worth") that the RFC's text never asked to change.
  Rejected: collapsing both to the sticker (breaks underpricing detection
  silently — no test would catch it since `flagUnderpricedCards`'s own
  early-return on `value === marketPrice` never firing looks like "nothing
  to flag today," not a bug) and leaving `marketPrice`'s condition
  adjustment out of the split reasoning (it stays deliberately, since
  comparing an unadjusted NM figure against a condition-correct sticker
  would flag nearly every non-Mint card as underpriced).
- **The parity fixture uses a `SimpleNamespace`-shaped row on the Python
  side rather than constructing a real `RawInventoryItem`/`GradedInventoryItem`.**
  `is_customer_visible` only ever reads five attributes
  (`status`, `kind`, `location`, `factory_sealed`, `sticker_price`) via
  plain attribute/`getattr` access, so it has no dependency on which
  concrete model built the object. A `SimpleNamespace` lets one case table
  cover raw/graded/bulk/sealed `kind` values without needing four different
  Pydantic constructors (bulk and sealed items don't have a `condition` or
  `finish`, which a shared constructor call would otherwise have to special-
  case away).
- **`isPublicInventory` is now `export`ed**, where it was module-private
  before. The only consumer besides `listCards()`'s internal filter is the
  new parity test — exporting it was the only way to test the exact function
  production code runs rather than a reimplementation of its logic in the
  test file (which is exactly the "claims parity nothing checks" failure
  shape CLAUDE.md already records for this file).

## T4 — done, 2026-09-03

**Files:** `backend/src/merlins_collection/services/bedrock.py`
(`_hydrate_item`'s price derivation — deleted the whole
catalog+condition-adjustment block, two now-unused imports), CLAUDE.md (the
condition-pricing section, rewritten — see below), `mcp-server/src/dynamodb-repository.ts`
(`marketPrice()`'s docstring and one stale inline comment, already
touched in T3 for the field split), full rewrites of
`backend/tests/services/test_display_price_derivation.py` (4 tests) and 2
tests in `test_display_hydration.py`.

**`_hydrate_item` is used by BOTH the customer chat and the admin analyst
chat** (`visible=is_customer_visible` default vs. `visible=ADMIN_VISIBILITY`)
— its own docstring states "ONE hydrator... never a second admin copy." The
RFC's T4 section names `routers/admin/inventory.py` and MCP's admin path as
places condition adjustment STAYS, but never names this shared hydrator
among them. Decided (not escalated — this is answerable from the code, not a
fact only the owner holds): the simplified sticker-only price applies to
BOTH hydration callers, since nothing in the RFC carves out an exception for
this specific shared function and a DisplayedCard's price should mean the
same thing regardless of which chat surface is asking. Recorded here as the
decision and the rejected alternative (keeping the old catalog/condition
derivation for the admin caller only, which would have meant threading a
second code path through one function the RFC explicitly says must not
fork).

RED confirmed: rewrote `test_display_price_derivation.py` wholesale first
(its old premise — pinning the condition-adjustment mechanism T4 removes —
made every one of its 4 tests test a mechanism about to not exist), ran
against the not-yet-touched `_hydrate_item`, all 4 failed for the right
reason (returning the OLD condition-adjusted/catalog figure, not the
sticker). GREEN after the `bedrock.py` change. Two more failures then
surfaced in `test_display_hydration.py` (the finish-fallback catalog lookup
tests) on the next full run — same obsolete-premise shape, one replacement
test written. Full backend suite: 2351 passed, 0 failures.

**CLAUDE.md's condition-pricing section was rewritten, not just amended** —
per the RFC's own instruction to do this in T4, not defer it, since the old
section actively misleads the moment this lands. Used a `<details>`-collapsed
"history" subsection for the retired pre-RFC-0025 mechanism rather than
deleting it outright, mirroring how this file already treats other
superseded-but-informative sections (e.g. the admin chat panel's `fixed`
positioning history) — a reader who finds an old cross-reference to "the
customer condition multiplier" can still find out what that meant and why
it changed, without the current, load-bearing rule being buried under it.

## T6 — done, 2026-09-03

**Docs:** CLAUDE.md's condition-pricing section (done as part of T4, per the
RFC's own instruction). No further CLAUDE.md changes needed for T6 itself —
T2's changes are internal (`is_customer_visible`/`_display_price`) with no
CLAUDE.md section previously documenting the old behavior in a way that
needed correcting beyond what T4 already rewrote.

**Full-suite verification, run at the RFC boundary (closing out Round 9):**

| Suite | Result |
|---|---|
| `backend/.venv/bin/python -m pytest backend/tests -q` | **2351 passed** |
| `npm test --workspace=frontend` | **1282 passed**, 114 files (unaffected — T2-T4 are backend/mcp-only) |
| `npm test --workspace=mcp-server` | **113 passed**, 9 files |
| `npm test --workspace=infra` | **44 passed**, 7 files (unaffected) |
| `npx tsc --noEmit` (frontend) | clean |
| `npx tsc --noEmit` (mcp-server) | clean |
| `npm run lint` (frontend) | clean (2 pre-existing unrelated warnings) |
| `ruff check backend/src` | clean |

**One operational note, not a code issue:** two full-suite backend runs
during T2/T3 timed out the harness's 120s foreground window and moved to
background — both completed successfully (2350, then 2351 passed) once
awaited; not a flake, just a suite that takes ~3 minutes.

### A finding that must be flagged to the owner directly (see follow-ups.md #7)

**The RFC's own "unchanged wire shape" contract for `GET /inventory/search`
means the price a customer actually SEES on a tile is still the pre-RFC
market-derived figure, not the sticker.** `_display_price` (filter, sort,
visibility) is correctly the sticker now; `_CUSTOMER_ITEM_FIELDS` was never
given a `sticker_price` entry, and `frontend/lib/inventory.ts:399` still
computes the customer-visible tile price as `marketPrice ?? item.listed_price
?? 'Price N/A'`. This is exactly scoped-as-written (no task in T2-T6 touches
`_CUSTOMER_ITEM_FIELDS` or any frontend price-rendering file, and the RFC's
own API Contracts section pins the search response shape as unchanged), so
it is not a bug in this implementation — but it does mean the RFC's stated
motivation ("Showing them the sticker is the fix") is not yet fully realized
end-to-end. Filtering/sorting/visibility all correctly use the sticker; the
displayed number does not yet. Logged in `follow-ups.md` and called out
plainly in the final summary rather than fixed as a side errand.

## Facts established during planning (do not re-derive these)

- **`sticker_price` is on `_ItemBase`** (`models/inventory.py:211`), so both
  customer kinds (`raw`, `graded`) carry it. No `getattr` needed.
- **`is_customer_visible` has FOUR readers**, three Python and one TypeScript:
  - `routers/inventory.py::customer_visible_items` — filter search + the authed
    dashboard summary (`/inventory/summary`)
  - `routers/public.py:276` — the anonymous public featured endpoint
  - `services/bedrock.py:525` and `:654` — chat display hydration, twice, via
    `visible=is_customer_visible`
  - **`mcp-server/src/dynamodb-repository.ts:46,62`** — a separate TypeScript
    mirror (`PUBLIC_LOCATIONS`, `row.status === "available"`) that queries
    DynamoDB directly, in a separate process. **This one is the easy miss.**
- **`_display_price` is the documented single authority** for the customer price
  filter, sort and tile. Its docstring records that those three once read three
  different figures and only two agreed, producing a $517 card that passed
  `max_price=500`. "They must never diverge again: change this function, not a
  caller."
- **`apply_condition_adjustment` has many callers and most are unaffected:**
  `catalog_sync.py:424` (bakes the multiplier into stored
  `current_market_value`), `routers/admin/inventory.py:899`,
  `routers/inventory.py:373` (the `est_value` loop being deleted in T5) and `:582`,
  `services/bedrock.py:437`. **Do not delete the module.**
- **`InventoryStats`' grid is already `auto-fit`, not `grid-cols-3`** — changed
  after a live 390px measurement where `$10,517.69` overflowed its card. Removing
  a tile needs no layout work.

## Decisions made autonomously (with the rejected alternative)

- **The sticker rule goes in `is_customer_visible`, not in a router.** Rejected a
  router filter: it would need repeating in four places and the two most likely to
  be missed (public featured, chat hydration) are the two least visible.
- **Condition adjustment is removed from the customer price path but the module
  stays.** A sticker is not a Near Mint catalog figure; scaling it applies the
  adjustment twice. Rejected leaving `_condition_adjust` in place (double
  application) and deleting the module (still used by four other callers).
- **Only the Est. value tile is removed, not the whole `InventoryStats`
  component.** Rejected removing the bar: two counts are not a valuation and the
  owner asked for the estimated-value widget.
- **`hidden_no_price` stays in the response with a test asserting it is zero.**
  Rejected removing it (a contract change for no gain) and leaving it untested
  (dead code rather than a tripwire).
- **CLAUDE.md's condition-pricing section is edited in T4, not deferred to T6.**
  It becomes actively wrong the moment T4 lands, and this repo has recorded the
  stale-justification failure twice already.

## Measurements to record here during execution

- **T1:** customer-visible count, stickered count, and the percentage — with the
  date. **Report to the owner before T2 merges.**

## Owner gates on this RFC

1. **T1 → T2.** The owner sees the stickered fraction before the storefront
   narrows. Their decision stands unless they change it on seeing the number.
