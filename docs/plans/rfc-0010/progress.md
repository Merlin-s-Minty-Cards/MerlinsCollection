# RFC 0010 — Admin Round 8: PROGRESS

**Read this first.** It is the state of the world for anyone picking up a task.

**This file is the tracked progress file — not `claude-progress.txt`.** That one is
gitignored (`.gitignore:60`), so it is local-only and your edits to it will never appear in
`git status` or reach anyone else. Record all RFC 0010 status **in this file**.

**Last updated:** 2026-08-11 (T16 DONE — a card with no catalog match can be valued by hand)
**Branch:** `Polishing-For-Deployment`
**RFC:** [`docs/rfcs/0010-admin-round8-ledger-corrections-and-slab-manual-only.md`](../../rfcs/0010-admin-round8-ledger-corrections-and-slab-manual-only.md)
**Task index:** [`README.md`](README.md)
**Source of the requests:** the owner's `The plan.pdf` (12 items) plus two review comments
on 2026-08-10 — the money-input report and the PSA/scanner reversal.

## ✅ T0, T1, T2, T3, T4, T5, T6, T7, T15, T16 AND T17 ARE DONE — start at T8

T15 gave all five catalog pickers one shared row carrying name, image AND price;
T17 built the job that fills those prices in; T2 stopped an admin edit forking a
consignor into two rows; T3 made the server the authority on why a row is in
Triage; T4 made that queue searchable; T5 made an edit in the detail modal show
up at once and stopped the list jumping; T6 made that same modal survive zoom;
T7 let the Prep Queue narrow to one location; T16 gave a card the catalog does
not carry a way to be valued, and stopped two surfaces misreporting it.
**Start at T8**, which is what T16's task doc names as the next link in the
chain, and which is now also the next row in the table below.

## 📉 T3 RE-MEASURED THE QUEUE AND THE TASK DOC'S PREMISE IS GONE

**Read this before T4, T5 or T16 — it changes what the remaining Triage work is
for.** Measured read-only against live `merlins-cards` on 2026-08-11, with the
same predicates the endpoint uses (the app was not running, so the doc's
`curl /admin/triage/counts` was computed directly instead):

| | task doc, 2026-08-10 | measured 2026-08-11 |
|---|---|---|
| inventory rows | — | 284 |
| triage rows | **266** | **27** |
| `flagged` / `missing_card_id` / `missing_english_name` | — | 27 / 17 / **0** |
| `blank_condition` rows | "hundreds"; the money bug | **0** |
| bulk-clear candidates | "the load-bearing part" | **0** |
| statuses | — | available 25 · on_hold 1 · sold 1 |
| reason combinations | — | `flagged+missing_card_id` 17 · `flagged` 10 |
| `review_reason` of the 27 | — | **None 21** · `no_catalog_link` 3 · `manual_entry` 1 · 2 human notes |

Four consequences, all of which outlive T3:

1. **The re-point tool is the load-bearing one**, by the task doc's own decision
   rule — 17 of 27 rows are unlinked.
2. **The `blank_condition` money queue is EMPTY.** The condition control T3 added
   is correct and still worth having, but it has no backlog to work through
   today. The "Blocked / needs the owner" row asking the owner to work that queue
   is closed below.
3. **`missing_english_name` is at zero**, so the Assign-English-name tool and the
   JP half of Triage currently have no rows either.
4. **21 of the 27 rows carry NO reason at all** — bare flags written before
   `review_reason` existed. They render the generic chip and are deliberately
   *not* bulk-clearable (absence of a reason is not a machine reason), so the
   dominant cohort must be cleared one at a time. **The bulk clear cannot help
   with them.** Filed in follow-ups.

The bulk clear is **not** dead code: `_review_reason_for_buy` writes
`manual_entry` / `no_catalog_link` on every manual buy entry, so candidates
accrue from normal use even though the importer never runs again.

**T2 shipped code plus a script the owner still has to run.** The fork can no
longer happen, but the two Harrys already in the live table are still there until
someone runs `scripts/reconcile_consignors.py`. It is the second row of "Blocked /
needs the owner" below. **Nothing is blocked on it** — the page is correct and
usable either way; it just shows the duplicate until the script runs.

**T17 shipped code, not data.** The nightly cycle reaches full catalog coverage on
its own in ~6 nights, but it has not run yet — so most of the 31,603 rows still
honestly read *"no price yet"* in every picker. The owner can skip that wait with
one overnight `scripts/reprice_catalog.py` run; it is the first row of "Blocked /
needs the owner" below. **Nothing is blocked on it.**

## ✅ T0 IS DONE — the RFC 0009 merge blocker is cleared

The partial-write money bug in the slab commit path is fixed. Measured on the code as it
stood: a five-row batch with a bad amount on row 3 wrote **2 inventory items and 2 PURCHASE
transactions** before dying, left the session `draft` with all five rows staged, and the UI
said *"Nothing was created; the batch is intact"*. It now writes **zero** and returns a 422
naming the row. **Start at T1.**

## Status

| # | Task | Status | Commit | Notes |
|---|---|---|---|---|
| T0 | Money input + partial write | **DONE** | `0702346` | Merge blocker cleared. `frontend/lib/money.ts` exports `parseMoney`, `formatMoneyInput` **and `formatMoney`** (grouped display — the doc listed only the first two). `StagedSlab.buy_price` is now a **number**. `confirm_buy_session` is split into a build pass and a write pass; reuse `_build_purchase`, do not re-inline it |
| T1 | `MoneyInput` rollout | **DONE** | `571b3bc` | Shipped on **eight** surfaces — the doc's seven plus **Trade**, which its own "Why" names. `MoneyInput` gained `placeholder` / `onBlur` / `onKeyDown`; `InlineEditCell` gained `type="money"` (option a). Wire format is **unchanged** — where a string went, `String(parsed)` still goes. `MONEY_PARSE_MESSAGE` now lives in `lib/money.ts` so the three surfaces that show it cannot drift. **Percent fields deliberately untouched.** Out of scope and filed: Inventory / Shows / History-filter money inputs, and `sales.py`/`trades.py`'s single-pass write |
| T2 | Consignor row fork | **DONE** | `0620fba` | `put_consignor` sweeps like `put_show`. `Consignor.active` is **gone** — replaced by `archived`, with a before-validator migrating a stored `active: False`. New repo method **`list_consignor_rows()`** (raw rows with SKs) backs both the sweep and the script; `list_consignors` now delegates to it. Router gained `_save_cosigner`/`_require_cosigner` (mirroring `_save_show`), a 409 name guard, `?include_archived=`, and `POST /admin/cosigners/{id}/unarchive`; **`DELETE` is the archive** and now returns the updated consignor, not `{"status": "deactivated"}`. `StatusBadge` gained **`active`/`archived`** styles — use those for any person or event. `scripts/reconcile_consignors.py` keeps the **unsuffixed** row, not the highest generation (see Decisions) |
| T3 | Triage reasons + filter | **DONE** | `cbb7b6c` | The query was never broken and the 266 rows are gone — **27 remain**, see the re-measurement above; read it before T4. `services/triage.py` gained `reasons_for` (and `needs_triage` is now `bool(reasons_for(i))`, so they cannot drift), `TERMINAL_STATUSES` + **`in_triage_scope`** (called by BOTH the list and `/triage/counts`, which is what keeps the badge honest), and `is_bulk_clearable`. Search emits **`triage_reasons` AND `bulk_clearable`** on `triage=true` rows only. **ONE filter param, `triage_reason`**, 422 on an unknown key; the old three stay for compatibility and `/admin/inventory` still uses `needs_review`. New `POST /admin/inventory/bulk-clear-review`. Param is **`include_terminal`**, not the doc's `include_sold` (see Decisions). **No sticker reason** (owner decision) |
| T4 | Triage search | **DONE** | `e6a3bfc` | Frontend only, no backend change — `name` already worked on the endpoint. Shared `SearchInput` (its 300ms debounce **is** the debounce; no timer was written). The term is trimmed **at the `useCallback` dependency**, not in state — see Decisions. Two additions beyond the doc's list: a failed search no longer renders the **success** panel, and **`bulk-clear-review` now sends `name`** — the button counts on-screen rows, so without it the POST cleared flags the admin never saw. `BulkClearReviewRequest.name` already existed and nothing was sending it |
| T5 | Detail modal live updates | **DONE** | `febc2eb` | `onUpdated?: (updated?: UpdatedItem) => void` — optional, so a parent that ignores it still refetches. New `frontend/lib/item-update.ts` holds `UpdatedItem` + **`patchRow`** (spread, never replace — the response carries no `triage_reasons`, `bulk_clearable` or joined `card`); seven call sites across the six pages. The modal owns `current` and renders **`shown`**, a synchronous `current.item_id === item.item_id` guard — the effect alone flashes the previous card. **`flagged` is now derived**, so `writeTriage` lost its `nextFlagged` parameter. A response with no string `item_id` is **discarded** (`asItem`) and `onUpdated()` fires with no argument → the parent's refetch fallback. **The task doc's Triage rule cannot work as written** — see Decisions |
| T6 | Detail modal layout | **DONE** | `4c82d79` | **Still needs the owner's zoom check** — jsdom asserts classes, not typeability. Four class decisions, two of them departures from the task doc: the grid template carries an inner **`min(17rem,100%)`** (a bare `minmax(17rem,1fr)` overflows below 17rem) and the textarea span is **`col-span-full`**, not `sm:col-span-2` (which invents an implicit column on a collapsed grid). Cells are `flex-wrap` with a `min-w-[min(8rem,100%)]` floor on the editor — that pair **is** the stacking mechanism, since Tailwind container queries are not installed (3.4, `plugins: []`). Image column is `shrink-0 md:shrink`, not a bare removal. **The Consignment grid was converted too.** Verified the arbitrary classes are actually EMITTED by grepping the built CSS — vitest asserts strings and would pass on a class Tailwind never generated |
| T7 | Prep Queue location | **DONE** | `95ca449` | Frontend only, exactly as the doc said — no backend change. The column keys **are** the backend's sort fields (`location`, `cost_basis`, `current_market_value`), because `_sort_admin_results` splits on the LAST underscore; do not rename a `Column.key` on this page without re-checking that split. First header click sorts **ascending**, unlike `/admin/inventory`'s desc-first `handleSort` (see Decisions). `handleStickerSave` **no longer refetches** — it patches and drops, so the toast is now conditional: clearing a price leaves the row and says "Sticker price cleared". Both summary cards are location-scoped (`In queue (Glass)`). The bulk apply still refetches, deliberately — filed |
| T8 | Local date formatting | **NOT STARTED** | — | Test **must** pin a negative-offset `TZ` or it is theatre |
| T9 | Signed ledger amounts | **NOT STARTED** | — | Presentation only. Do not invert signs in storage |
| T10 | `Transaction.batch_id` | **NOT STARTED** | — | No heuristic backfill. Legacy rows render as single-row groups |
| T11 | Transaction void | **NOT STARTED** | — | **Largest risk in the RFC.** One countability predicate, every reader named in the task doc |
| T12 | Slabs: PSA out, price at intake | **NOT STARTED** | — | Keep `CertInput`'s Enter handling. Pricing runs AFTER commit, never inside it |
| T13 | Grouped navigation | **NOT STARTED** | — | Every route path unchanged |
| T15 | Card picker: image + price | **DONE** | `b322e03` | One shared `CardPickerRow` with **five** callers (Buy, Trade, Triage ×2, Slabs, Market). Backend: `market_price_and_finish()` in `models/inventory.py` is now the walk and `_market_price` delegates to it — **do not add a second lookup to get a finish**. `display_price` is a **string** (`"12.34"`), `null` when absent. The component is **generic in the card type**, so callers keep their own `CatalogCard`; each one now `extends PickerCard`. Thumb is `TABLE_THUMB_SIZE` (`xs`), **not** the `sm` the task doc named — see Decisions. Fixed on the way: Market's row was a `<button>` nested inside a `<button>` |
| T17 | Weekly catalog price cycle | **DONE** | `e233fc4` | Shipped as specified, plus one shape change: `refresh_catalog_prices` takes an optional **`card_ids`** so the reprice script selects ONCE per run and feeds it chunks — without it a permanently-404 card leads every chunk (see Decisions). The extraction is **two** helpers, not one: `_refresh_one_card` (the per-card spec the doc named) inside a shared `_refresh_cards` loop, which took `_refresh_held_prices` from 60 lines to a 6-line delegate. New config knob `CATALOG_REFRESH_CARDS_PER_NIGHT` (5500). Summary keys are all `catalog_`-prefixed and **always present**, including `catalog_skipped: None`. Coverage adds `catalog_cards_brief` / `catalog_cards_stale` / `catalog_stale_threshold_days` (8), rendered in the Market banner. **Read the first follow-up row before trusting the exit codes** — production runs `scheduled_sync.py`, not `daily_sync.py` |
| T16 | Unmatched-card valuation | **DONE** | `93466b6` | The premise held: three of the twelve RED tests **passed before any change** and are kept as named guards — the nightly job really does skip an unlinked item. New: `frontend/lib/valuation.ts` (`isHandValued`, `conditionMultiplierOf`, `localToday`) and `HandValuedBadge`, mounted on Prep Queue rows and in `CardDetailModal`'s **Pricing** section. Triage gains a fourth repair tool, `ValueDialog`, gated on the SERVER's `missing_card_id` reason. **The multiplier is served, not mirrored** — `_serialize_item` now emits `condition_multiplier` (see Decisions); do not add a `frontend/lib` copy of the table. `GET /admin/slabs` reports `price_source: "hand_set"` when there is no price row, and coverage gains `items_market_priced` / `items_hand_valued` / `items_unpriced`, a **partition** of `total_items` |
| T14 | Docs + ops | **NOT STARTED** | — | RFC 0009 T2/T5 → WON'T DO. Note the two CLAUDE.md rules added during planning (card images, archiving) are already in place — do not re-add them |
| T-FINAL | Verification + PR | **NOT STARTED** | — | `next build` is not optional |

Statuses: `NOT STARTED` → `RED (awaiting owner confirmation)` → `IN PROGRESS` → `DONE`,
plus `BLOCKED` for a task that was started and cannot finish without the owner, and
`DEFERRED` for one deliberately taken out of the critical path.

## How to update this file

At the **end** of your task conversation, and only then:

1. Set your row's status to `DONE` and paste the commit sha.
2. Add one line to the Notes column if a later task needs to know something.
3. Add anything surprising to the **Decisions made during execution** table below.
4. Append out-of-scope findings to [`follow-ups.md`](follow-ups.md) — not here.

Do **not** mark a task `DONE` without the narrow test selection passing. Evidence before
assertions. And **never re-use a verification result across a later feature commit** —
that is the mistake that made RFC 0009's T-FINAL sign-off stale.

## Blocked / needs the owner

| Item | Needed from owner | Blocks |
|---|---|---|
| **Run `scripts/reprice_catalog.py` overnight once — T17 has LANDED, this is ready now** | It prices all ~31,300 unheld catalog rows in one ~2 h 18 min run, so the weekly cycle starts from full coverage instead of taking ~6 nights to reach it. **Prove it on a slice first:** `--limit 200` dry run, then `--limit 200 --execute --confirm-table merlins-cards`, then the uncapped `--execute --confirm-table merlins-cards`. The dry run prints the candidate count, chunk plan and ETA before anything is written. It is chunked (lock taken/released per chunk) and resumable — Ctrl-C and re-run is safe, and there is no checkpoint file to clean up. **It needs `dynamodb:Scan`** | nothing; the nightly cycle gets there on its own, this just skips the wait |
| **Run `scripts/reconcile_consignors.py` once — T2 has LANDED, this is ready now** | The sweep stops NEW forks; it does not merge the duplicate Harry already in the live table, because nothing rewrites a consignor until someone edits it. **Prove it with the dry run first:** `../.venv/Scripts/python.exe scripts/reconcile_consignors.py` prints every row it would keep and every row it would remove, and writes nothing. Then `--execute --confirm-table merlins-cards`. It keeps the row carrying the admin's edits (the 85% Harry). **Do not run it during an import** — coexisting generations are load-then-swap's whole point during the load phase. Report the count back into this file | nothing; the page is correct either way, it just still lists the duplicate |
| ~~Work the `blank_condition` queue~~ | **CLOSED 2026-08-11 by measurement — the queue is EMPTY.** T3's diagnostic found **zero** rows carrying `blank_condition` (and zero `missing_english_name`) in the live table; the 266-row import cohort the concern was raised against is gone. The condition control T3 built is still on the row and still correct — it just has no backlog. The exclusion from bulk clear stays regardless: it is the rule that stops the defect being re-created, not a reaction to current data | — |
| **Clear the 21 reasonless flags by hand — T3 cannot do it for you** | 21 of the 27 triage rows carry `needs_review = true` with **no `review_reason` at all** (written before the column existed, and not backfillable — the data no longer distinguishes the cases). They render the generic "Flagged for review" chip and are deliberately excluded from bulk clear, because absence of a reason is not evidence automation set it. Each needs an admin to look at the card and press **Clear review** | nothing; the page does this fine, it is just one row at a time |
| ~~Should the import stop setting `needs_review` for `blank_condition`?~~ | **CLOSED 2026-08-10.** The importer will never run again, so its flagging is historical — do not edit it. And the reason turns out to be a money defect, so it is emphatically worth reviewing | — |
| **Does voiding a PURCHASE need to work in the first cut?** | Voiding a sale returns an item to stock. Voiding a purchase should arguably *remove* an item that may since have been sold or traded. Sales-only, with purchases returning a clear 400, is the honest small version | T11 scope |
| **Rotate both API keys — STILL OUTSTANDING from RFC 0009 T8** | Both were pasted into a chat transcript on 2026-08-07. Owner action in the vendor portal; procedure in `docs/aws-setup.md` Phase 8. Only the pricing key matters now — **the PSA key is read by no code and, per RFC 0010 §H, never will be** | nothing in code; flagged, not done |
| ~~Get PSA to approve the account~~ | **WITHDRAWN 2026-08-10 — the cert API is now a paid feature and the owner has declined it.** RFC 0009 T2 and T5 become WON'T DO. Stop retrying; stop emailing `collectors-apis@collectors.com` | — |

## Decisions made during execution

| Date | Task | Decision | Why |
|---|---|---|---|
| 2026-08-10 | T0 | **`parseMoney('0')` is `0`, not `null`** — so every caller must test `=== null` and never falsiness. The task doc's table did not cover zero | `!parseMoney(cost)` would reject a legitimately free card, which is a real thing at a buy table (a throw-in, a bulk lot). This is the one way the new parser could reintroduce a silent wrong answer, so it is a named test |
| 2026-08-10 | T0 | **`money.ts` exports a third function, `formatMoney`** (`1300` → `$1,300.00`), grouped by hand rather than through `toLocaleString` | The doc's own StagingTable test requires comma-grouped display, which `formatMoneyInput` deliberately does not do (the input value has to round-trip back through `parseMoney`). Hand-grouping keeps the output independent of which ICU data the runtime shipped with. This is the fifth `toFixed(2)` site in the frontend — **T1 should collapse the other four into it** |
| 2026-08-10 | T0 | **`confirm_buy_session` builds every row before writing any**, rather than only pre-checking numeric fields as the doc described | The doc's stated goal is fixing partial write *as a class*. A numeric-only check does not get there: a bad `condition`, `company` or `location` still failed `InventoryItemAdapter` **inside** the write loop and reproduced the identical half-written batch through a different door. Extracting `_build_purchase` and writing in a second pass is both stronger and shorter than the loop it replaced. Verified with a test that puts a bad `condition` on row 2 |
| 2026-08-10 | T0 | **The partial write was MEASURED, not inferred** — 2 inventory items, 2 PURCHASE transactions, session still `draft`, all 5 rows still staged | Recorded because the UI's claim ("Nothing was created; the batch is intact") was confidently false, and the same sentence is still in `slabs/page.tsx` for the *other* failure modes it covers. It is accurate there **only because** the backend now writes nothing — if anyone reverts the confirm change, that message starts lying again |
| 2026-08-11 | T1 | **Trade is IN scope, though the task doc's measured table omits it.** The doc's own "Why" names it (*"the owner types money on Buy, Sell, **Trade**, Prep Queue and Show Prep"*), and `follow-ups.md`'s third T0 row already assumes T1 touches Trade's inputs | Leaving it out would have made Trade the one admin page that still swallows a comma — the exact inconsistency this task exists to remove. Five Trade fields converted: manual cost basis, incoming market value, incoming trade-in value, outgoing leg value, cash-component amount |
| 2026-08-11 | T1 | **`InlineEditCell` gained `type="money"` (option a), and it commits `String(parseMoney(draft))`** — `'1,300'` → `'1300'`, `'9.99'` → `'9.99'` unchanged. Unreadable text does not call `onSave` at all; it goes to `onError` and the editor stays open, the same shape as an `onSave` rejection | The doc recommended (a) and it held up: one change, and both inline sticker editors (Prep Queue, Show Prep) inherited it. Committing a canonical *string* rather than a number keeps every caller's existing `onSave(value: string)` contract intact |
| 2026-08-11 | T1 | **The wire format did not change. Where a string went, `String(parsed)` still goes** — `sticker_price`, `manual_basis`, `minimum_price`. Buy/Trade already sent JSON numbers and still do | The doc's "Do not change any API contract" is load-bearing here: these amounts land in `Decimal` fields, and swapping string→number on five endpoints at once would have made a parsing fix into a serialization change. Happy side effect: the pre-existing Prep Queue test asserting `{ sticker_price: '9.99' }` stayed green untouched |
| 2026-08-11 | T1 | **`MoneyInput` grew three props — `placeholder`, `onBlur`, `onKeyDown`** — and `MONEY_PARSE_MESSAGE` moved into `lib/money.ts` | The number inputs it replaced carried `placeholder="0.00"`, and Trade commits its cost basis and cash components **on blur**, so without a pass-through the rollout would have silently dropped both behaviours. `onBlur` runs *after* the field normalises itself. The message moved because three surfaces now render it (both components plus Market's `alert`), and three hard-coded copies is how they start disagreeing |
| 2026-08-11 | T1 | **One pre-existing test was rewritten, deliberately: Prep Queue's `min="0"` assertion.** It is a `type="number"` attribute that cannot survive the swap; its intent (reject negatives) moved to `parseMoney`, which rejects a negative outright, and the test now asserts the inline message instead | Recorded because "every pre-existing test still passes" was the stated GREEN gate and this one could not. The behaviour is strictly better — the browser used to ignore the keystroke silently; the operator is now told |
| 2026-08-11 | T1 | **Trade's outgoing-value editor became CONTROLLED**, backed by an `outDrafts` map keyed by item id | It was `defaultValue` + `onBlur`, which a money field cannot be: a half-typed `"1,"` has to survive the next render, and MoneyInput normalises through `onChange`. The draft is dropped on remove so re-adding the same card does not resurrect old text |
| 2026-08-11 | T1 | **Sell's per-item price edit was found to be COSMETIC — it never reaches the API at all.** `updateItemPrice` mutates local state; `handleConfirm` PATCHes session metadata and POSTs `/confirm`, and nothing in between sends the edited `agreed_price`. Same for the bulk discount | Found while writing the "typing 1,300 sends 1300" test and discovering there is no send to assert on. Out of T1's scope (it is not a parsing defect) so it is filed in follow-ups, but it is the largest thing this task turned up: an admin discounting a card at a show is editing a number that is thrown away |
| 2026-08-11 | T15 | **The picker thumbnail is `TABLE_THUMB_SIZE` (`xs`, 56×78), NOT the `size="sm"` the task doc's Design section names.** The doc contradicts itself: its readability section costs the row at *"a 56×78 thumb plus two text lines… ~5rem of row height"* and requires ~5 candidates visible at once | `sm` is 96×136, so five rows would need ~42rem of dropdown — which is exactly the "squished into a page" the owner's ask rules out. The `size="sm"` line describes Buy's existing code rather than the requirement, and CLAUDE.md already fixes 56×78 as *the* admin row thumbnail ("import the size, never re-pick it"). Dropdown caps went `max-h-56` → `max-h-[28rem]` on Buy, Trade and Triage; Triage's dialog went `max-w-lg` → `max-w-2xl` |
| 2026-08-11 | T15 | **`_market_price` was REFACTORED, not copied: `market_price_and_finish()` now holds the walk and `_market_price` is a one-line delegate.** Every existing caller is untouched | `display_finish` cannot be obtained from `_market_price`, and looking the price up a second time to discover which key produced it would have been the fifth reimplementation the docstring bans by name. The walk is byte-identical (the original's `order = []; if finish not in order: append` is unconditionally `[finish]`), and the final fallback loop iterates `.items()` instead of `.values()` for the key |
| 2026-08-11 | T15 | **`CardPickerRow` is GENERIC in the card type (`<T extends PickerCard>`), and grew two seams beyond the doc's `card`/`onSelect`/`action` — `nameBadge` and `selected`** | Generic because every page carries a wider `CatalogCard` (Buy reads `prices`, Market keeps an index signature) and `onSelect` handing back the narrow type meant a cast at all five call sites. `nameBadge` exists because Market renders a name-match-confidence chip inline with the name and silently dropping it while "improving" the row would be a regression; `selected` replaces the highlight class Market already had. `PickerCard.images` is `{ small?: string \| null }` — **not** an optional whole object — so it stays assignable to the narrower shapes already in `lib/` |
| 2026-08-11 | T15 | **The doc's backend test path is wrong: it is `backend/tests/routers/admin/test_market.py`, not `backend/tests/test_market.py`.** And its 4th backend RED test (`detail` present on every item) **passed before any change** — `detail` is a model field and `model_dump` has always emitted it | Second doc-path error in this RFC after T0's; check the path before trusting it. The 4th test was kept as a regression guard rather than dressed up as new work — the frontend now depends on that field to tell *"never fetched"* from *"no provider covers it"*. Also: `npx vitest` **did** work from `frontend/` this time, contrary to the note in this file's baseline section |
| 2026-08-11 | T17 | **`refresh_catalog_prices` gained an optional `card_ids` parameter, and the one-time script selects ONCE for its whole run rather than re-selecting per chunk.** The task doc's shape — "a driver that calls the same `refresh_catalog_prices` with a huge budget", chunked — would have re-selected before every chunk | A 404 writes nothing, so the card's `last_synced_at` never moves and it stays at the **head** of the stalest-first queue. Re-selecting per chunk therefore re-fetches every retired card in all ~16 chunks, and they lead each one. Nightly that retry is correct and free; inside a single overnight run it eats the budget and can stop the run finishing. Selecting once is also what makes the progress output and the ETA honest. Still one pricing implementation — the driver supplies candidates, nothing else |
| 2026-08-11 | T17 | **The extraction is TWO helpers, not the one the doc named.** `_refresh_one_card` is the per-card specification it asked for; `_refresh_cards` is the surrounding loop — pacing, the consecutive-failure counter, the abort, the runtime cap | The loop was as duplicated as the body and just as delicate (the 404 that must *neither* increment *nor* reset is a property of the loop, not the fetch). Extracting only the body would have left two copies of that. Net effect is a **reduction**: `_refresh_held_prices` went from ~60 lines to a 6-line delegate, and the 114 pre-existing tests in `test_catalog_sync.py` passed unchanged, which is what proves the extraction faithful |
| 2026-08-11 | T17 | **The runtime cap is an elapsed-time bound on the loop (`deadline`), not a start-time assertion** — and it is `None` for the depth pass, which therefore does not read the clock at all | The doc offered either. A start-time assert only catches a mis-set *constant*; the bound also catches a night where TCGdex is merely slow, which is the likelier way a 24-minute pass becomes a 60-minute one. `None` rather than a huge default so the ~300-card depth pass is provably unchanged — no new call, no new failure mode |
| 2026-08-11 | T17 | **`catalog_cards_brief` and `catalog_cards_stale` are rendered in the Market banner**, and the frontend fields are **optional**, with the line rendering as nothing (not zero) when they are absent | The doc's Files list was backend-only but its requirement says "add to `/admin/market`'s coverage panel" — a number no panel shows is not auditable. Optional because a response from before T17 does not carry them, and defaulting to `0` would render *"0 never priced · 0 past 8 days"*, i.e. a healthy cycle, on an API that has none. Only `catalog_cards_stale > 0` turns the line amber; a large `brief` count is the first cycle still running, which is the design working |
| 2026-08-11 | T17 | **The doc's four test paths are ALL wrong — the third such case in this RFC.** Real paths: `backend/tests/services/test_catalog_sync.py`, `backend/tests/scripts/test_daily_sync.py`, `backend/tests/routers/admin/test_market.py`, `backend/tests/scripts/test_reprice_catalog.py` | Following T0's and T15's rows: **check the path before trusting a task doc's test command.** The doc's own narrow-selection command would have collected nothing and reported success |
| 2026-08-11 | T17 | **Production never runs `daily_sync.py`.** The EventBridge schedule runs `python -m scripts.scheduled_sync --job prices`, which returns 0 unconditionally — so the exit codes T17 added (and the ones the depth pass already had) signal to nobody | Found while checking where the new step actually executes. The **feature** is fine: `scheduled_sync` calls `run_daily_sync`, so the cycle runs nightly and its counts land in the CloudWatch JSON summary. Only the exit code is lost. Filed rather than fixed — changing what a scheduled ECS task returns is an ops-visible change and the owner's call. **First row of follow-ups.md's execution section** |
| 2026-08-11 | T15 | **Buy's and Trade's rows previously rendered `CardImage` only `{card.images?.small && …}`** — so a card with no art produced a SHORTER row | Fixed as part of the shared row, and it is the reason the doc makes it a named test: rows that change height as art loads make the list jog under the cursor mid-click, which on a picker means selecting the wrong card. The placeholder is now always rendered, at the same size |
| 2026-08-11 | T2 | **The reconcile script keeps the UNSUFFIXED row, which is the OPPOSITE of what the task doc's text says** (*"keeps the highest-generation row (the most recently written)"* — those are two different rows) | An admin edit runs with no import generation, so it writes `CONSIGNOR#<id>` with no suffix. That row is therefore the most recently written of the pair **and** the one carrying the values the admin typed — the owner's 85% Harry. Keeping the highest `#<gen>` suffix would have silently discarded exactly the edit that made the fork visible, i.e. the script would have "fixed" the bug by throwing away the user's data. Highest-generation is kept only as the fallback for a consignor no admin ever edited, where every row is suffixed. Both branches are named tests |
| 2026-08-11 | T2 | **The script removes rows by re-writing the winner through `put_consignor`**, rather than issuing its own deletes | The sweep T2 just installed already encodes "which rows are superseded". A second copy of that rule inside a script that runs once, unattended, against live data is exactly the divergence this repo keeps paying for — and this way the cleanup exercises the fix rather than paralleling it |
| 2026-08-11 | T2 | **Two pre-existing tests were rewritten, deliberately** — `test_create_cosigner`'s `data["active"] is True` and `test_delete_deactivates`'s `active is False` (now `test_delete_archives`) | The GREEN gate says the pre-existing suites stay green, and these two could not: the task doc's own "do not leave `active` and `archived` both live as writable fields" removes the field they assert on. Both now assert `archived`; the behaviour they guard (create defaults to live, DELETE never destroys) is unchanged and is asserted harder in the new `TestArchiveCosigner`. Same shape as T1's `min="0"` rewrite |
| 2026-08-11 | T2 | **A new repo method, `list_consignor_rows()`** — raw rows with sort keys — and `list_consignors` now delegates to it | The SK is the only thing that tells a forked consignor's two copies apart, and the `Consignor` model drops it. Both the sweep and the script need it; the alternative was a one-time script reaching into `repo._table` and `repo._query_all`, i.e. two callers depending on privates to do the most delicate write in the round |
| 2026-08-11 | T2 | **`StatusBadge` gained `active` and `archived` styles** rather than the page growing a private badge | CLAUDE.md's rule is *"an `Archived` badge never reuses inventory-status vocabulary"*, and shows already hand-rolls its own badge span — a second hand-rolled copy here would make three vocabularies for one concept. Two lines in the shared map means the next archivable entity gets it free. `active` is mint (as `available` was) so the row does not visually change for a live consignor |
| 2026-08-11 | T2 | **One of the four frontend RED tests passed before any change** — the 409 duplicate-name message. Kept as a regression guard, not dressed up as new work | The page's `catch` already renders `err.detail`. The reason the owner saw a useless message is that the **backend never sent a 409**; nothing on the frontend was broken. Same call as T15's 4th backend test. Three backend tests are in the same position and are labelled in the file: the mid-import coexistence test, the "PATCH that does not move the name" test, and the "archiving with linked inventory succeeds" test — each pins a deliberate *absence* (no sweep across generations, no over-broad guard, no in-use guard) |
| 2026-08-11 | T2 | **The task doc's test paths were wrong for the FOURTH time in this RFC**, and its frontend command was the `npx vitest` form this file records as broken. Both corrected **in the task doc itself** this time, not just here | Following T0's, T15's and T17's rows. Correcting only the progress file has demonstrably not worked — three later docs copied the bad command. Real paths: `backend/tests/routers/admin/test_cosigners.py`, `backend/tests/services/test_dynamodb.py`, `backend/tests/scripts/test_reconcile_consignors.py` |
| 2026-08-11 | T3 | **The task doc's whole premise was re-measured and does not hold: 27 triage rows, not 266, with `blank_condition` and `missing_english_name` both at ZERO.** The full table is in the re-measurement section above | The doc decides its own priorities off that breakdown (*"if `flagged` accounts for ~all 266, the bulk clear is load-bearing; if `missing_card_id` does, the re-point tool is"*), and it ordered the work as if the import cohort were still there. It is not — the owner has been draining it. Recorded prominently because **T4, T5 and T16 all assume a large Triage queue**, and the honest size of the remaining job is 17 unlinked cards plus 10 hand/legacy flags |
| 2026-08-11 | T3 | **The scope parameter is `include_terminal`, NOT the doc's `include_sold`** — and `TERMINAL_STATUSES` is `SOLD`, `LOST` and `RETURNED_TO_CONSIGNOR`. UI label: "Include sold and closed" | A lost card and one returned to its consignor are as un-fixable as a sold one — the card is not in the building. A parameter named `include_sold` that also admits those two is a name that lies about what it does, and the next reader would add a *second* flag for the other statuses. Nothing else in the repo referenced `include_sold`, so the rename costs nothing |
| 2026-08-11 | T3 | **The server also emits a per-row `bulk_clearable` boolean**, beyond the `triage_reasons` the doc specified | The confirm dialog has to name an exact count *before* firing, and the only other way to compute it client-side is to mirror `MACHINE_REVIEW_REASONS` into TypeScript — which is precisely the drift this task exists to remove. One predicate (`is_bulk_clearable`), two consumers: the serializer and the POST route. It also makes the count exact by construction, since the search is unpaginated so the loaded rows *are* the filtered set |
| 2026-08-11 | T3 | **The bulk clear writes an `edit` timeline event per item**, exactly as the single-item PUT does | `admin_update_item`'s own comment states the invariant: a manual edit is the one mutation path with no built-in transaction record, so without the event the prior value is unrecoverably overwritten with no audit trail. A *bulk* version is the last place to drop that — it is the one that overwrites many rows at once. Costs one extra write per cleared item, on an operation that clears tens of rows at most |
| 2026-08-11 | T3 | **The task doc states the multi-reason bulk-clear rule two ways and they conflict.** Built: an item with a second reason is left **completely alone** (`cleared == 0`, flag intact, `reviewed_at` untouched) | The doc says both *"clears only items whose ONLY reason is `flagged`"* and *"an item that is also unlinked keeps its other reasons and stays in the list"* — the second implies the flag was cleared. The first is safer and is what shipped: clearing the flag on a row that stays in the queue anyway makes the queue no shorter, destroys the stored `review_reason`, and stamps `reviewed_at` on an item nobody reviewed — which then suppresses the next automated flag. My first draft of the test asserted the other reading and was the one test that failed after GREEN; the *test* was wrong |
| 2026-08-11 | T3 | **Three pre-existing frontend tests were rewritten, deliberately** — all four page fixtures gained `triage_reasons`, the reason-filter test now asserts `triage_reason=<key>` **and** the absence of the old three params, and the two-reason test asserts "Entered by hand" instead of `manual_entry` | Same shape as T1's `min="0"` and T2's `active` rewrites. The endpoint always sends `triage_reasons` for `triage=true`, so a fixture without it is a response shape that no longer exists — and a page that falls back to the local recompute when the key is missing would reintroduce exactly the drift being removed. **No fallback was added**, on purpose |
| 2026-08-11 | T3 | **The doc's frontend run command is the `npx vitest` form this file records as broken** — corrected in the task doc itself, following T2's precedent. Its backend test path (`backend/tests/test_admin_inventory.py`) does not exist either; everything went in `backend/tests/routers/admin/test_triage.py` | **Fifth** task doc in this RFC with wrong paths or a wrong command (T0, T15, T17, T2, now T3). Correcting only this file has demonstrably not worked |
| 2026-08-11 | T4 | **The bulk clear was made to send the search term — a defect T4 itself introduced, fixed inside T4 rather than filed.** With a search active the button counted the rows on screen while the POST ignored the search, so *"Clear machine flags (1)"* would have cleared **every** machine flag in the queue | Adding the search is precisely what makes the count and the operation diverge, so it is not a pre-existing issue to hand onward. It also needed **no backend change**: `BulkClearReviewRequest.name` already exists and the endpoint already filters on it — its docstring says the filter mirrors the search so *"clear what I can see"* is expressible. Nothing was sending it. Found in the post-change adversarial pass, written RED first, and it is now the 7th test in the block |
| 2026-08-11 | T4 | **The term is trimmed at the `useCallback` DEPENDENCY (`const searchTerm = search.trim()`), not in state** | Both alternatives are wrong in a way that shows up on the keyboard. Trimming into state makes `SearchInput`'s `value → local` sync echo the trimmed string back into its own box, so a space is eaten the instant it is typed — the admin cannot type `"Mega Brave"`. Depending on the raw `search` refetches the whole queue for `"   "`, a request that sends no `name` and therefore returns exactly what is already on screen. The trimmed derivation gets both: spaces are typeable, and a whitespace-only term fires **no request at all** |
| 2026-08-11 | T4 | **The empty state was split, and the split is keyed on the SEARCH only — a reason filter that matches nothing still renders the success panel.** Filed, not fixed | The doc's one named design decision is the search case, and `missing_english_name` is at zero live, so the filter case is reachable today. It is a one-line extension (`searchTerm || reasonFilter`) plus its own copy and test, and it is T3's surface — widening T4 to cover it is the kind of scope drift this RFC's task docs exist to prevent. In follow-ups with that fix spelled out |
| 2026-08-11 | T4 | **No timer was written.** `SearchInput`'s built-in 300ms debounce is the debounce the doc asks for | Recorded because the doc specifies "debounced 300ms" as if it were work, and the shared component's default already is 300. A second debounce layered on top of it would have made the queue lag ~600ms behind the keyboard for no gain. The test asserts the *behaviour* (three keystrokes → one call), so it stays honest if the component ever changes |
| 2026-08-11 | T4 | **The task doc's run command was the broken `npx vitest` form for the SIXTH time in this RFC** (T0, T15, T17, T2, T3, now T4) — corrected in the task doc itself, following T2's precedent. Its file paths were right, which is the first time | Six for six on the command. Every one of these docs was written before the `npx vitest` failure was recorded and none was revised after; correcting them one at a time as each task runs is the only thing that has actually worked |
| 2026-08-11 | T5 | **The task doc's Triage rule is unimplementable as written and was replaced.** It says *"the correct test is on the **updated item's** `triage_reasons` being empty"* — but `PUT /admin/inventory/{item_id}` returns a bare `_serialize_item` and **never carries that key**: `_attach_triage_reasons` runs only on `?triage=true` SEARCH rows. Built instead: patch the row, then `reasonsFor()` **predicts** the next state, exactly as `clearReview`, `onRepointed` and `onNamed` on that page already do | Following the doc literally would read `undefined`, treat it as empty and **drop every edited row from the queue whether it was fixed or not** — including a card whose only edit was a note. `patchRow` spreads for the same reason: replacing the row wholesale with the response would strip the reason chips and the joined `card` the list request added. Two tests pin it — one that the row drops when the flag was its only reason, one that a still-unlinked row **stays** and keeps its remaining chip |
| 2026-08-11 | T5 | **A response that is not recognisably an item is DISCARDED, not displayed** (`asItem` — a non-object, or no string `item_id`). The modal keeps showing what it had and calls `onUpdated()` with **no argument**, which is the parent's refetch fallback | Two reasons, one of them measured: `setCurrent({})` erases `item_id`, and `shown` then fails its own guard and unmounts the modal mid-edit — a 204, a proxy, or an older backend is enough. The second is the task's own premise: a modal that renders a save it cannot see is the defect being fixed, arriving through a different door. Every existing test in the file mocks `put` as `{}`, so without this the change would have taken the whole suite down |
| 2026-08-11 | T5 | **`shown` is a synchronous guard (`current.item_id === item.item_id`), not just the effect the doc describes** | `useEffect(() => setCurrent(item), [item?.item_id])` alone leaves one render where the prop is card B and `current` is still card A — effects run after that render commits. So opening a second card would flash the first card's saved values. The effect stays (it re-seeds), the guard makes the render correct in the same tick. Named test: "re-seeds from the prop when the modal is reopened on a different card" |
| 2026-08-11 | T5 | **`flagged` stopped being state and `writeTriage` lost its `nextFlagged` parameter** — three arguments became two | The doc asks for `flagged` to be derived "or the two drift", and once it is, a caller-supplied `nextFlagged` is a second source for the same fact: it would let the header read "In Triage" while the item on screen says otherwise. The honest consequence is recorded here — if a write returns something `asItem` rejects, the header does **not** flip, because nothing confirmed it did |
| 2026-08-11 | T5 | **A shared `patchRow` helper (`frontend/lib/item-update.ts`) rather than six inline maps**, and `CardDetailModalProps.onUpdated` takes its `UpdatedItem` type | Seven call sites across six pages, and the rule they all depend on — **spread, never replace** — is exactly the kind that gets copied wrong once and then silently strips a triage row's chips. Same call as `CardPickerRow` in T15. The two pages with a drop rule compose (`patchRow(...).filter(...)` / `.flatMap(...)`), so the page-specific rule still reads at the call site |
| 2026-08-11 | T5 | **Three of my own RED tests initially passed against the UNFIXED code and had to be hardened.** Counting rows to prove a row was dropped reads zero while a refetch has `loading` true; two tests now assert each page's own empty panel, which requires `!loading && items.length === 0`. A third matched "Pikachu" in both the table and the open modal's header | Recorded because a green test against unfixed code is the failure mode the RED gate exists to catch, and it was only caught by reading *why* each test failed rather than counting failures. Same lesson as the ChatPanel entry below: the first failure explains the rest |
| 2026-08-11 | T5 | **The doc's run command was the broken `npx vitest` form for the SEVENTH time** (T0, T15, T17, T2, T3, T4, now T5) — corrected in the task doc itself. Its file paths were right | Seven for seven. **T6 is the same file and will have the same command** — fix it before running it |
| 2026-08-11 | T6 | **The grid template carries an inner `min()`: `minmax(min(17rem,100%),1fr)`, not the doc's `minmax(17rem,1fr)`** | A bare `minmax` forces a 17rem track even when the container is *narrower* than 17rem, so the grid overflows horizontally — which at 200% zoom in a narrow window is strictly worse than the squeeze being fixed, because the content leaves the modal instead of merely being cramped. The tests assert `auto-fit` + `minmax` rather than the exact string, so the safer form is not locked out. Same `min()` reasoning as the image column's cap, which the doc *does* specify — the doc applied the idea in one place and not the other |
| 2026-08-11 | T6 | **The textarea span is `col-span-full`, NOT the existing `sm:col-span-2`** | Wrong twice over on the new grid. It is viewport-keyed exactly as the grid was, and — the real defect — on a grid that has collapsed to ONE column, `span 2` makes the browser create an **implicit second column**, breaking precisely the narrow case this task exists to fix. `col-span-full` (`grid-column: 1/-1`) spans whatever tracks actually exist. Confirmed emitted as `grid-column:1/-1` in the built CSS |
| 2026-08-11 | T6 | **Tailwind container queries are genuinely unavailable, so the stacking is `flex-wrap` on the cell plus `min-w-[min(8rem,100%)]` on the editor** | The doc offers `@container`/`@lg:` as the cleaner expression "if available" — it is not: tailwind 3.4 with `plugins: []` and no `@tailwindcss/container-queries`. Wrapping is the honest substitute and is genuinely container-driven: the editor drops below the label exactly when it no longer fits beside it, with no breakpoint to tune. The floor is the load-bearing half — `min-w-0` (what was there) is what let the input be crushed to near-zero width, which **is** the owner's "characters go into the factory sealed label" symptom. The input never moved; it was squeezed until it rendered beside the neighbouring label |
| 2026-08-11 | T6 | **The image column is `shrink-0 md:shrink`, not a bare removal of `flex-shrink-0`** | Below `md` the content area is `flex-col`, where shrinking squashes the art *vertically* on a short viewport — a layout that was never the bug. The doc says "replace `flex-shrink-0`" without distinguishing the two axes. The RED test was hardened to assert `md:shrink` alongside the absence of `flex-shrink-0`, so it pins the intent ("yields in the side-by-side layout") rather than the letter; it still fails against the original code. Also added **`max-w-full`** to the `img`, which the doc omits — without it a `w-auto` image sized off `h-full` overflows the very cap being added, so `max-h-full` alone does not hold |
| 2026-08-11 | T6 | **The arbitrary-value classes were verified against the BUILT CSS, not just the DOM** — `auto-fit`, `min-width:min(8rem`, `max-width:min(34%`, `aspect-ratio:5/7` and `grid-column:1/-1` all confirmed present | The whole test strategy here is class-string assertions, and a class Tailwind's JIT never emits produces an identical green suite with a silently broken layout — the grid would fall back to one implicit column. This is the one failure mode jsdom cannot see *and* the change is entirely made of unusual arbitrary values, three of them with nested `min()`. **Worth repeating for any future arbitrary-value Tailwind class**: `npm run build --workspace=frontend`, then grep `frontend/.next/static/css/*.css` |
| 2026-08-11 | T6 | **The Consignment grid was converted too, though the task doc's Files/Design sections name only the field sections** | It is the same `grid-cols-1 sm:grid-cols-2` defect, in the same modal, one section below — leaving it would mean a consigned card's terms stay two-up-and-squeezed at the exact zoom the rest of the modal was just fixed for. One class, no behaviour change, and it is inside the reported symptom ("the fields don't have room to show the data") rather than beside it |
| 2026-08-11 | T6 | **One of my seven RED tests failed for a defect in the TEST, and was fixed rather than accepted** — the regression gate matched `Notes`, which is both a section `<h3>` and a field label, so it died on "Found multiple elements" | It is the gate that proves no field vanished, and a gate must pass *before* the change or it proves nothing. Switched to the unambiguous `Sticker Notes`. Recorded because it is the mirror of T5's lesson: **read why each test failed, do not count failures** — six failed on class strings (correct) and the seventh on a selector (mine), which is invisible in a "7 failed" summary |
| 2026-08-11 | T6 | **The task doc's run command was CORRECT — the first in this RFC.** Its file paths were right too | Ends a run of seven (T0, T15, T17, T2, T3, T4, T5) where the doc carried the broken `npx vitest` form. T5's note *"T6 is the same file and will have the same command — fix it before running it"* turned out to be unnecessary: T6's doc already carries the `npm test --workspace=frontend` form and the correction-in-the-doc practice T2 started has caught up with the chain |
| 2026-08-11 | T7 | **The first header click sorts ASCENDING, deliberately unlike `/admin/inventory`, whose `handleSort` opens `desc`** | The task doc's own RED test 4 specifies it (`location_asc` first, `location_desc` on the second click) and it is right for this page: locations read alphabetically, and the point of sorting by cost here is to find the cheap cards still worth pricing by hand, i.e. low-to-high. Recorded because the two pages now genuinely disagree and the next reader will assume one of them is a bug. It is a page-level default, not a shared component change — `DataTable` has never owned the direction |
| 2026-08-11 | T7 | **The "Priced → removed from queue" toast stopped being unconditional, and that is a consequence of the task, not a side errand** | Removing the refetch is a named requirement ("Do not refetch the list when an item is priced"). But the refetch is what used to quietly put a *cleared* row back — clearing a sticker price is a real edit, and the row then still meets this queue's `missing_sticker=true` criterion. Without a refetch, announcing "removed" while the row visibly stays would be the message lying. Clearing now says "Sticker price cleared"; only a non-null price drops the row. The priced id is also pruned from `selectedIds`, or the bulk bar counts a card nobody can see |
| 2026-08-11 | T7 | **The header counts were already correct; only the LABELS were missing.** Both `In queue` and `Est. value` are derived from `items`, which is the server-filtered set, so the doc's "reflect the filtered set" requirement held before any change | Recorded because it changes what that RED test actually gates. The honest new behaviour is the scope suffix — `In queue (Glass)` / `Est. value (Glass)` — and the test's count assertions passed before the change, dying only on the missing `<select>`. Both cards are labelled, not just the count: an unqualified `$10.00` beside a scoped `1` is the same misread through a different card |
| 2026-08-11 | T7 | **One of my nine RED tests had to be re-scoped AFTER green and re-proven RED** — `getByText('$10.00')` matched both the Est. value card and the surviving row's Market cell once the filter narrowed to one item | Third time in this RFC (T5's row-count tests, T6's `Notes` collision): a test written against the *unbuilt* UI can pick a selector that only becomes ambiguous once the UI exists. Fixed by scoping each figure to its own summary panel, then re-run against a `git checkout`-reverted `page.tsx` to confirm it still fails — a test rewritten after GREEN proves nothing until it has been shown RED. **The scoped assertions are also the ones that survive** if a future row happens to be worth $35.00 |
| 2026-08-11 | T7 | **The doc's run command was the broken `npx vitest` form again** (T0, T15, T17, T2, T3, T4, T5 — T6 was the one exception) — corrected in the task doc itself. Its file paths were right | Eight of the nine executed docs. The correction-in-the-doc practice T2 started is what stops the next reader re-hitting it; correcting only this file has demonstrably never worked |
| 2026-08-11 | T16 | **The condition multiplier is SERVED, not mirrored: `_serialize_item` now emits `condition_multiplier` on every admin row** (`"0.58"`, `null` for a kind with no condition). No table was added to `frontend/lib` | The task doc says both *"add the mirror"* and, in its Do-not list, *"do not hardcode a second copy of the condition multiplier table"* — those conflict, and the second is the one worth keeping. `services/condition_pricing.py` is the authority and it already has one duplicate (`mcp-server/src/condition-pricing.ts`, whose own docstring calls it "a known seam"); a `frontend/lib` copy would be the third place a re-tuned tier has to be changed in step. The dialog needs the number live as the admin types, so a round-trip per keystroke is out — but the number is a property of the ROW, and the row is already being fetched. `lib/valuation.ts`'s `conditionMultiplierOf` just reads it |
| 2026-08-11 | T16 | **Three of the twelve RED tests PASSED before any change**, and are kept as named guards rather than dressed up as new work — the two `refresh_inventory_market_values` invariants and the `PUT` accepting a hand-set value | This is the task doc's own premise (*"it already works, and nothing tells you so"*) verified rather than assumed, and the doc asks for the first by name: *"the invariant everything else rests on. Name the test for it"*. Recorded because the RED gate exists to catch a green test against unfixed code, and the honest answer here is that 3 of 12 were exactly that **by design**. The 9 that failed are the whole of the actual work. Same call as T15's 4th backend test and T2's four |
| 2026-08-11 | T16 | **A slab's `hand_set` source keys on the absence of a PRICE ROW, not on `card_id`** | The doc frames it as an unlinked-slab problem, but a *linked* slab that no provider covers is in the identical position: `get_graded_price_row` returns nothing, so any figure the item carries was typed by a human. Gating on `card_id` would have reported that case as unpriced forever while the value sat on the row. Keying on the row also makes the rule read as what it is — "there is no provider figure, so this one is yours" — and it cannot disagree with `PUT /admin/slabs/{id}/price/pin`, which 404s for exactly the same reason |
| 2026-08-11 | T16 | **`isHandValued` is `!card_id` alone — NOT the doc's "has a value AND no `card_id`"** | The row that most needs the marker is the one that is **still blank**: on Prep Queue an empty Market cell with no explanation reads as *"the price hasn't synced yet"*, and waiting is the one wrong response available. Keyed on the link alone it matches `refresh_inventory_market_values`' skip condition exactly (`kind not in (raw, graded) or card_id is None`), which is what makes the marker true rather than merely plausible — and it correctly covers sealed and bulk, whose values have always been hand-set |
| 2026-08-11 | T16 | **The coverage split is computed as a PARTITION (`market_priced = with_value − hand_valued`, `unpriced = total − with_value`), not as three independent sums** | The doc's requirement is that the three sum to the total, and three separate `sum(...)` comprehensions satisfy that only until somebody edits one predicate. Deriving two of them makes the invariant structural — the test asserts the sum, and the code cannot fail it. `unmatched_sample` now samples `items_unpriced`, so a hand-valued card is not in it: there is nothing left for anyone to do about it |
| 2026-08-11 | T16 | **The `/admin/market` panel renders the split, though the doc's RED list is backend-only** — as `70 market-priced · 10 hand-valued · 20 unpriced`, with the three fields **optional** and the line absent (not zeroed) when the API did not send them | Straight repeat of T17's call: its Design section says *"report manually-valued items as a third category"* on that page, and a number no panel shows is not auditable. Optional for T17's reason too — a pre-T16 response carries no keys, and defaulting to 0 would render *"0 hand-valued"*, a confident claim the API never made |
| 2026-08-11 | T16 | **The dialog writes a GENERATED `value_note`, never free text** — `Hand-valued 2026-08-11 — $40.00 NM comp × MP (0.58)` | `value_note` is in `_CUSTOMER_ITEM_FIELDS`: it is customer-visible by design (Phase 19), which is what makes it the right home for provenance and the wrong home for a text box. Generating it also means the note and the number cannot disagree. The date is built from `getFullYear/getMonth/getDate`, **not** `toISOString().split('T')[0]` — that is the UTC-date bug **T8** is about to fix everywhere, and T16 was not going to add a fresh instance of it on the way past |
| 2026-08-11 | T16 | **The tool is gated on the server's `triage_reasons` including `missing_card_id`, not on a local `!item.card_id`** | T3 made `services/triage.reasons_for` the authority on why a row is in the queue and this is not the place to open a second one. It also matters that the tool is **absent** on a linked card rather than merely useless there: the nightly sync owns that figure, so a value typed on a linked card is gone by morning, and an affordance that silently discards work is worse than no affordance |
| 2026-08-11 | T16 | **The doc's narrow-selection command matched NO coverage test** — `-k "catalog_sync or slab or market_coverage"` never matches `TestAdminMarketCoverage`, and the frontend half was the broken `npx vitest` form again. Both corrected **in the task doc itself** | Ninth of the ten executed docs (T6 remains the one exception), and a new variety: previous errors were wrong *paths*, this one is a `-k` expression that collects and passes while testing none of what the task added. Worse than a wrong path, which at least fails loudly |
| 2026-08-10 | T0 | **The doc's file paths were wrong in two places**, corrected as executed: the backend tests are `backend/tests/routers/admin/test_purchases.py`, and the frontend run command must be the `npm test --workspace=frontend` form, not `npx vitest` | `npx vitest` fails with "Vitest failed to find the runner" — already noted in the baseline section of this file, but the task doc contradicted it. Later task docs copy this command; check it before trusting it |

*(rows below are PLANNING decisions, recorded before execution because a later task would
otherwise re-litigate them.)*

| Date | Task | Decision | Why |
|---|---|---|---|
| 2026-08-10 | T0 | **`type="number"` is REJECTED as the cost-field fix**, reversing the recommendation recorded in RFC 0009's progress file | The owner's review comment requires `1,300` to be *accepted*. A native number input does not accept a comma, so that fix makes the owner's input un-typeable rather than correct — it satisfies the machine and fails the person |
| 2026-08-10 | T0 | **`parseFloat` is banned for money.** Measured: `parseFloat("1,300")` → `1`, `parseFloat("1,300.50")` → `1`, and neither is `NaN` | It defeats every `isNaN` guard already in the codebase (`outgoing/page.tsx:140`, `show-prep/page.tsx:133`), converting a loud 500 into a silent $1,299 loss. A wrong number that passes validation is strictly worse than a crash |
| 2026-08-10 | T0 | **`confirm_buy_session` will pre-validate the whole batch**, not just the one field that triggered the bug | It is the only change that fixes *partial write* as a class rather than this trigger. Filing it as a follow-up was the alternative, and it is hard to justify filing "the ledger can be left half-written" while T11 is being built specifically because the ledger had no correction path |
| 2026-08-10 | T3 | **Triage's requested sticker reason is NOT built** — owner reframed the ask: *"Triage is not for stickers that need updating, it is for cards with correctness issues that need manual fixing from an admin"* | The written plan document asked for it; the owner's clarification overrides their own doc. Derived, it would have added ~224 rows to a list they want to shrink and duplicated Prep Queue; stored, it would have made Triage a second sticker worklist |
| 2026-08-10 | T2 | **Consignor delete is an ARCHIVE, hidden by default, badge reads "Archived"** — with a "View archived" toggle. The first draft's hard-delete/purge route is **withdrawn** | Owner refinement. Once the fork is swept there is no orphan row that needs destroying, and a consignment ledger that can lose its counterparty is worse than a list with a filter on it. Mirrors `Show.archived`, the rule CLAUDE.md already documents |
| 2026-08-10 | T2 | **`Consignor.archived` replaces `active`**, with a before-validator mapping a legacy `active: False` → `archived: True` | `active` meant the same thing under a worse name and is read almost nowhere. Two live fields for one concept is how the next reader introduces a bug. The migration is not hypothetical — **the owner has already soft-deleted a Harry**, so a production row carries `active: False` and must render as archived |
| 2026-08-10 | T3 | **`blank_condition` is a MONEY defect and is EXCLUDED from bulk clear.** Found while planning: the importer defaults a missing condition to `Condition.NM` (`spreadsheet_import.py:437-443`) — the most expensive tier — and every customer price scales down from it, so an LP card is listed at **1.22×** and an MP card at **1.72×** its value | It is the highest-value queue in Triage, not noise, and it is fixable by someone holding the card. Bulk-clearing it would silently ratify an NM price on every card nobody has checked — the exact failure the condition-pricing work exists to prevent. T3 adds an inline **condition** repair tool instead |
| 2026-08-10 | T3 | **Do not touch the spreadsheet importer.** Owner: *"We will most likely never run the importer again… we are actively reviewing and adding cards to match the sheet until we will eventually drop the sheet altogether"* | Closes the open question about its flagging behaviour. Nothing refills the queue, so draining Triage is one-way rather than a treadmill — and editing a program that will never run again is dead code with a live blast radius. It also promotes Triage to the **primary reconciliation workflow**, which is why T3/T4 favour filtering, searching and in-place fixes over bulk actions |
| 2026-08-10 | T8 | **A second date bug is in scope: `toISOString().split('T')[0]` is the UTC date.** Measured — 6:30pm Pacific on Aug 10 yields `2026-08-11`, so every transaction entered after 5pm Pacific defaults to **tomorrow**. Buy, Sell, Trade and the dashboard all do it | Same root cause as the display bug (a date derived through a UTC boundary) and the same helper file. Fixing the display while leaving the input wrong would be worse than fixing neither — the business sells at evening shows, so this mis-dates most transactions |
| 2026-08-10 | T8 | **Local zone first, `America/Los_Angeles` as the fallback — an IANA name, never a fixed `-08:00`** | Owner: *"use the local time if possible, but otherwise default to PST time as that is where we are all located."* Measured: Pacific is **PDT (−7)** in August and **PST (−8)** in January, so a hardcoded −8 is wrong from March to November — including every summer show. Also worth knowing: for **date-only** values no zone is involved at all once you stop routing them through `new Date()`; the fallback only matters for timestamps and for "what is today" |
| 2026-08-10 | T15 | **"A card picker MUST show the image" went into CLAUDE.md as a standing rule, not just into a task.** Owner: *"it should be a clear rule going forward in all work on this project… Do what you need to in order to make sure this mistake doesn't happen again."* | A task fixes five files; a rule fixes the sixth picker nobody has written yet. CLAUDE.md over a skill because this is project-specific product judgement, not a transferable technique — and CLAUDE.md is loaded into every session. The rule also covers the *layout* half of the ask, since art bolted on until the name is unreadable is a regression, not a feature |
| 2026-08-10 | T17 | **The weekly deadline is met by ~5,500 cards/night stalest-first over six nights, NOT by a nightly full-catalog pass.** Owner set the deadline ("by friday of each week") and left the split to me | Measured: 162 ms/card + the existing 100 ms courtesy delay = 262 ms, so all 31,603 rows serial is **2 h 18 min** — which **outlives the 3600 s catalog lock TTL**. That failure mode is not a stale price, it is *"the card silently disappears from a live catalog"* (`refresh_held_prices` docstring). 5,500/night is 24 min with 2.5× headroom, completes in 5.7 nights so Friday is slack, and one or two lost nights are absorbed. Cost was never the constraint: ~$2.40/month |
| 2026-08-10 | T17 | **Ordering is `detail == "brief"` first, THEN `last_synced_at` ascending — and it needs no schema change** | `CatalogCard` already carries both. The trap that decided the order: `last_synced_at` is bumped by **any** write including the breadth pass, so a priceless `brief` row written yesterday looks *fresher* than a priced row from last week. Ordering on the timestamp alone would push brand-new, never-priced cards to the back of the queue. Same shape as `refresh_graded_prices` — never-priced first, then stalest, capped at a budget |
| 2026-08-10 | T17 | **Stalest-first instead of a persisted cycle cursor** | A cursor is state that can be wrong, and it strands whatever an aborted night skipped. With stalest-first, a failed night's cards stay stale and tomorrow picks them up automatically — the cycle self-heals with nothing to reconcile |
| 2026-08-10 | T15 | **The price figure is chosen SERVER-side** via `_market_price(card, "normal")`, returned as `display_price` + `display_finish` | A catalog result has no item, so no finish, and `_market_price` returns `None` without one — the frontend literally cannot call it correctly. Passing a default finish inherits the whole fallback walk for free. Its docstring bans reimplementation by name: a second copy is how 174 of 213 live items went unpriced. This would have been the fifth |
| 2026-08-10 | T15 | **The absent-price states are the MAIN cases, not edges**, and `detail: "brief"` vs `"full"`-with-no-band must render differently | ~31,300 of 31,603 rows have no price until T17 finishes its first cycle. And the two absences are different facts — *"we never fetched one"* vs *"no provider covers this card"* — which the model preserves deliberately as *"an honesty requirement"*. Collapsing them to `—` discards the only signal saying whether waiting helps. An absent price is **never** `$0.00`: bands are written only when a provider published a figure |
| 2026-08-10 | T15 | **The image was always in the response.** `CatalogCard.images` is populated and `/admin/market/search` serialises it — Triage, Slabs and Market simply discard it, while `/admin/buy` and `/admin/trade` render it correctly | So this is not a data problem and needs no backend change. It also explains the failure: three pickers were built *from* Buy's pattern and dropped the image on the way, which is why the fix is one shared component with five callers rather than three more copies |
| 2026-08-10 | T2 | **`/admin/shows` is the reference implementation for archiving**, and the pattern is now a six-part contract in CLAUDE.md rather than a per-entity decision | Owner: *"if there are other things that get archived, they should be the same."* Shows already has all of it — `include_archived`, a "Show archived" checkbox, an `Archived` badge, and confirm copy explaining what is preserved. Copying it costs nothing and diverging costs a bug per entity |
| 2026-08-10 | T16 | **Hand-valuation already works; T16 surfaces it rather than building it.** `refresh_inventory_market_values` skips `card_id is None` (`catalog_sync.py:395-397`), so a typed `current_market_value` on an unlinked item is never overwritten | The honest framing changes the size of the task from "build a parallel pricing system" to "add one repair tool and stop misreporting". Two traps found in the process: the **condition multiplier is NOT applied** to a hand-typed value (so the admin must type the adjusted figure, and the UI must help), and an **unlinked graded slab has nowhere to store a graded price** at all, because those rows are keyed by `card_id` |
| 2026-08-10 | T3 | **Reasons are emitted by the SERVER**, and `reasonsFor()` stops being the display authority | The Python and TypeScript copies of the rules are faithful *today* — verified by probing the predicates, not assumed — which is exactly why the drift would be silent later. A row in the list with no chip is the owner's own report |
| 2026-08-10 | T10 | **`batch_id` is NOT backfilled**, and no `(date, payment_method, type)` heuristic is allowed | Two separate cash sales on one show day are indistinguishable from one two-card sale. The heuristic invents transactions that never happened, in the one view where being wrong costs money. Legacy rows render as single-row groups and say so |
| 2026-08-10 | T11 | **Void, never delete** (owner's choice from three options) | It matches the precedent already in this codebase — Shows "delete" is an archive so analytics can never dangle (RFC 0008 Q6). A deleted sale leaves no trace it existed and silently disagrees with every snapshot already generated |
| 2026-08-10 | T12 | **PSA is dropped, not deferred**, and the two disabled buttons are deleted | They were rendered disabled *on purpose*, so the gap read as known rather than forgotten. With the API now paid and declined, the gap is permanent — and a disabled button implies a roadmap. The reason moves into the docs so the next reader finds a decision rather than silence |
| 2026-08-10 | T12 | **Pricing runs AFTER the commit, never inside its loop**, via the existing `refresh-prices` endpoint scoped by `item_ids` | Putting a metered third-party HTTP call inside the write loop rebuilds T0's failure with a worse trigger. And `refresh_graded_prices` already orders never-priced slabs first, so a just-committed slab is already at the head of the queue — this needs a scope filter, not a second pricing path |
| 2026-08-10 | T12 | **`CertInput`'s Enter-advances behaviour and `\r\n` stripping SURVIVE** hiding the scanner UI | A wedge scanner is a fast keyboard that ends with Enter. Remove the handler and wedge scanning breaks while hand-typing keeps working — the failure is invisible until someone is standing at a table with a scanner |
| 2026-08-10 | T13 | **Routes are not renamed.** `/admin/outgoing` keeps its misleading path | Grouping is a sidebar concern. Renaming breaks every bookmark and doc reference to fix a URL nobody types, and CLAUDE.md already documents the gotcha |

## Baseline at planning time (2026-08-10)

Measured during RFC 0009's T-FINAL re-verification at commit `80deb9c`, so a later task can
tell a regression from a pre-existing failure:

| Suite | Count | Time | State |
|---|---|---|---|
| Backend | 1502 passed / 0 failed | 2m13s | green (measured 2026-08-09 at `6486773`) |
| Frontend | 580 tests, **6–7 failing** | ~30s | **RED — pre-existing, not ours** |
| MCP | 98 passed / 7 files | 1.0s | green |
| `ruff check backend/src` | — | ~3s | clean |
| `npm run lint --workspace=frontend` | — | ~5s | clean, exit 0 |
| `npm run build --workspace=frontend` | — | — | exit 0 |

**Re-measured after T0 at `0702346`** — a suite result is never reused across a later
feature commit, so this is a fresh run, not the row above carried forward:

| Suite | Count | Time | State |
|---|---|---|---|
| Backend | 1515 passed / 0 failed | 2m09s | green |
| Frontend | **609 passed / 0 failed** | ~29s | **green — the ChatPanel flake is fixed, see below** |
| `ruff check backend/src` | — | ~3s | clean |
| `npm run lint --workspace=frontend` | — | ~5s | clean (one pre-existing `<img>` warning in `CardDetailModal`) |
| `npm run build --workspace=frontend` | — | — | exit 0 — **run this one**, `StagedSlab.buy_price` changed type and vitest does not typecheck |

**Re-measured after T1 at `571b3bc`** — a fresh run, not the row above carried forward:

| Suite | Count | Time | State |
|---|---|---|---|
| Frontend | **644 passed / 0 failed** (80 files) | ~30s | green — 609 + 35 new T1 tests |
| `npm run lint --workspace=frontend` | — | ~5s | clean (the one pre-existing `<img>` warning in `CardDetailModal`) |
| `npm run build --workspace=frontend` | — | ~18s | exit 0 |

Backend and MCP were not re-run: T1 is frontend-only and touched no Python or MCP
file. Do not carry these numbers into the next task's sign-off.

**Re-measured after T15** — a fresh run, not a row above carried forward:

| Suite | Count | Time | State |
|---|---|---|---|
| Backend | **1519 passed / 0 failed** | 2m27s | green — 1515 + 4 new T15 tests |
| Frontend | **670 passed / 0 failed** (81 files) | ~32s | green — 644 + 26 new T15 tests |
| Narrow T15 selection (9 files) | 107 passed / 0 failed | ~12s | green |
| `ruff check backend/src` | — | ~3s | clean |
| `npm run lint --workspace=frontend` | — | ~5s | clean (the one pre-existing `<img>` warning in `CardDetailModal`) |
| `npm run build --workspace=frontend` | — | ~40s | exit 0 — **and it caught a real type error vitest could not**, see below |

MCP was not re-run: T15 touched no MCP file.

**`next build` earned its place in the checklist.** With all 107 focused tests green,
the build failed on `PickerCard.images` being `{…} | null` where
`lib/trade-incoming-form.ts` declares `{ small?: string | null } | undefined` — a
five-call-site signature change is exactly the shape vitest does not typecheck. Fixed
by narrowing `images` to an optional object with nullable members. **Run the build.**

**Re-measured after T17** — a fresh run, not a row above carried forward:

| Suite | Count | Time | State |
|---|---|---|---|
| Backend | **1554 passed / 0 failed** | 2m28s | green — 1519 + 35 new T17 tests |
| Frontend | **673 passed / 0 failed** (81 files) | ~32s | green — 670 + 3 new T17 tests |
| Narrow T17 selection (4 files) | 149 passed / 0 failed | ~17s | green — and **114 of those 149 are pre-existing**, which is what proves the `_refresh_one_card` extraction faithful |
| `ruff check backend/src` | — | ~3s | clean |
| `npm run lint --workspace=frontend` | — | ~5s | clean (the one pre-existing `<img>` warning in `CardDetailModal`) |
| `npm run build --workspace=frontend` | — | ~40s | exit 0 |

MCP was not re-run: T17 touched no MCP file.

**Re-measured after T2** — a fresh run, not a row above carried forward:

| Suite | Count | Time | State |
|---|---|---|---|
| Backend | **1574 passed / 0 failed** | 2m45s | green — 1554 + 20 new T2 tests |
| Frontend | **677 passed / 0 failed** (81 files) | ~30s | green — 673 + 4 new T2 tests |
| Narrow T2 selection (3 backend files) | 118 passed / 0 failed | ~13s | green |
| Narrow T2 selection (1 frontend file) | 13 passed / 0 failed | ~1.4s | green |
| `ruff check backend/src` | — | ~3s | clean |
| `npm run lint --workspace=frontend` | — | ~5s | clean (the one pre-existing `<img>` warning in `CardDetailModal`) |
| `npm run build --workspace=frontend` | — | ~40s | exit 0 |

MCP was not re-run: T2 touched no MCP file, and nothing in `mcp-server/` reads a
consignor.

**Re-measured after T3** — a fresh run, not a row above carried forward:

| Suite | Count | Time | State |
|---|---|---|---|
| Backend | **1595 passed / 0 failed** | 3m28s | green — 1574 + 21 new T3 tests |
| Frontend | **691 passed / 0 failed** (82 files) | ~8s | green — 677 + 14 new T3 tests |
| Narrow T3 selection (1 backend file) | 57 passed / 0 failed | ~11s | green — 36 of them pre-existing |
| Narrow T3 selection (2 frontend files) | 36 passed / 0 failed | ~8s | green |
| `ruff check backend/src` | — | ~3s | clean |
| `npm run lint --workspace=frontend` | — | ~5s | clean (the one pre-existing `<img>` warning in `CardDetailModal`) |
| `npm run build --workspace=frontend` | — | ~40s | exit 0 |

MCP was not re-run: T3 touched no MCP file, and nothing in `mcp-server/` reads a
triage reason.

**Re-measured after T4** — a fresh run, not a row above carried forward:

| Suite | Count | Time | State |
|---|---|---|---|
| Frontend | **698 passed / 0 failed** (82 files) | ~30s | green — 691 + 7 new T4 tests |
| Narrow T4 selection (1 file) | 38 passed / 0 failed | ~9s | green — **31 of them pre-existing**, which is what proves the search did not disturb T3's queue, either repair tool, or the T15 pickers |
| `npm run lint --workspace=frontend` | — | ~5s | clean (the one pre-existing `<img>` warning in `CardDetailModal`) |
| `npm run build --workspace=frontend` | — | ~11s | exit 0 |

Backend, MCP and `ruff` were not re-run: T4 is frontend-only and touched **no**
Python and no MCP file — `git diff --stat` on the feature commit is two files,
both under `frontend/app/(admin)/admin/triage/`. Do not carry these numbers into
the next task's sign-off.

**Re-measured after T5** — a fresh run, not a row above carried forward:

| Suite | Count | Time | State |
|---|---|---|---|
| Frontend | **708 passed / 0 failed** (82 files) | ~31s | green — 698 + 10 new T5 tests |
| Narrow T5 selection (4 files) | 109 passed / 0 failed | ~10s | green — **99 of them pre-existing**, which is what proves the six `onUpdated` rewires disturbed nothing |
| `npm run lint --workspace=frontend` | — | ~5s | clean (the one pre-existing `<img>` warning in `CardDetailModal`) |
| `npm run build --workspace=frontend` | — | ~11s | exit 0 |

Backend, MCP and `ruff` were not re-run: T5 is frontend-only and touched **no**
Python and no MCP file. Do not carry these numbers into the next task's sign-off.

**Re-measured after T6** — a fresh run, not a row above carried forward:

| Suite | Count | Time | State |
|---|---|---|---|
| Frontend | **715 passed / 0 failed** (82 files) | ~30s | green — 708 + 7 new T6 tests |
| Narrow T6 selection (1 file) | 38 passed / 0 failed | ~6s | green — **31 of them pre-existing**, which is what proves a pure layout change disturbed none of T5's live-update work, the triage write path or the field registry |
| `npm run lint --workspace=frontend` | — | ~5s | clean (the one pre-existing `<img>` warning in `CardDetailModal`, and **only** that one) |
| `npm run build --workspace=frontend` | — | ~40s | exit 0 |
| Built-CSS grep | 5 of 5 utilities emitted | — | green — see below |

Backend, MCP and `ruff` were not re-run: T6 is frontend-only, one component file
plus its test. Do not carry these numbers into the next task's sign-off.

**The build did a second job here, and it is the one that matters.** vitest
asserts class *strings*; a class Tailwind's JIT never emits gives an identical
green suite over a silently broken layout. Every one of T6's decisions is an
unusual arbitrary value, three with a nested `min()`, so the built CSS was
grepped directly:

| Grepped | Found |
|---|---|
| `grid-template-columns:repeat(auto-fit,minmax(min(17rem,100%),1fr))` | ✅ verbatim, `min()` intact |
| `min-width:min(8rem,100%)` | ✅ |
| `max-width:min(34%,20rem)` | ✅ |
| `aspect-ratio:5/7` | ✅ |
| `grid-column:1/-1` | ✅ |

Repeat this for any future arbitrary-value Tailwind class: `npm run build
--workspace=frontend`, then grep `frontend/.next/static/css/*.css`.

**Lint caught a warning this change introduced, and it was fixed rather than
accepted.** `react-hooks/exhaustive-deps` reports at the `useEffect(` line, not
at the dependency array — an `eslint-disable-next-line` placed above `}, [...])`
suppresses nothing. The baseline for this file is **one** `<img>` warning; a
second one is a regression, not noise.

**Re-measured after T16** — a fresh run, not a row above carried forward:

| Suite | Count | Time | State |
|---|---|---|---|
| Backend | **1602 passed / 0 failed** | 2m15s | green — 1595 + 7 new T16 tests |
| Frontend | **734 passed / 0 failed** (82 files) | ~29s | green — 715 + 9 new T16 tests + 10 landed with T7 |
| Narrow T16 selection (4 backend files) | 245 passed / 0 failed | ~29s | green — **238 of them pre-existing**, which is what proves a derived serializer field, a slab fallback and a coverage split disturbed none of T15's price walk, T17's cycle counts or RFC 0009's slab list |
| Narrow T16 selection (4 frontend files) | 128 passed / 0 failed | ~11s | green — 119 of them pre-existing |
| `ruff check backend/src` | — | ~3s | clean |
| `npm run lint --workspace=frontend` | — | ~5s | clean (the one pre-existing `<img>` warning in `CardDetailModal`, and only that one) |
| `npm run build --workspace=frontend` | — | ~40s | exit 0 |

MCP was not re-run: T16 touched no MCP file. Note that `mcp-server/src/condition-pricing.ts`
is *referenced* by this task's reasoning — it is the duplicate that made a third
frontend copy unacceptable — but it is unchanged and its multipliers did not move.

**Not verified here, and it needs the owner: T16's manual check.** Take a real
card that is not in the catalog. From Triage, hand-value it with an NM comp and
the condition helper, then confirm it shows that price on `/inventory` as a
customer, that it can be sold through `/admin/sell`, that its sticker can be set
from Prep Queue, and — the whole point — **that the value is still there after
`POST /admin/market/sync`**. The suite pins the invariant against moto; only a
live run pins it against the real nightly job and real data.

**Not verified here, and it needs the owner: T6's manual check IS the acceptance
criterion, not the suite.** jsdom does no layout — `getBoundingClientRect()` is
all zeros — so the six new tests pin the class *decisions* and cannot tell you
whether the Finish field is typeable at 175% zoom in Chrome. On `/admin/triage`,
`/admin/show-prep` **and** `/admin/inventory`, at 100%, 150% and 200%: open a
card, click **Finish** and type, and confirm the characters land in the Finish
input and it is wide enough to read (the owner's own case: Hydreigon ex #240).
Then check that the image never takes more than about a third, that the fields
collapse to one column instead of staying two-up, that `item_id`/`tcg_url`
truncate rather than widening the column, and that a card with **no** art lays
out the same. A **graded** item is the densest section — three extra Identity
fields — so check one of those too.

**Not verified here, and it needs the owner:** T5's manual check — on Inventory,
scroll well down the list, open a card, edit its location, and confirm the new
value appears at once **and** that closing the modal leaves you where you were
rather than at the top. Scroll position is not observable in jsdom, so the tests
pin its *cause* (the list request must not fire again) and only a human confirms
the effect.

**Not verified here, and it needs the owner:** T4's manual check — searching a
card known to be in the queue, then one that is not, and confirming the message
does not congratulate you. Tests pin the panel that renders; only a human
confirms it reads right beside a real 27-row queue.

**`ruff check backend/tests/routers/admin/test_triage.py` reports 2 violations
(one `I001`, one `E501`) and BOTH pre-date T3** — verified by running ruff
against the file's `HEAD` contents through `--stdin-filename`, which reports the
identical two. Same call as T2 and T17: **do not "fix" pre-existing lint inside a
feature commit.**

**Not verified here, and it needs the owner:** T3's manual check — opening
Triage and confirming every visible row has a chip, filtering by each reason and
watching the count change, and setting a real condition on a card in hand and
confirming the customer-facing price on `/inventory` moves. The last one has
**no data to test against** — `blank_condition` is at zero — so it is really a
check that the control writes the two fields correctly on any raw row.

**`ruff check backend/tests` is NOT clean, and it was not clean before T2 either.**
`test_cosigners.py` carries **6 pre-existing** violations (one `I001`, five `E501`)
— verified by stashing the change and running ruff against the file at `HEAD`,
which reports the same six. The two files T2 added are themselves clean. Same
call as T17 made for `backend/scripts`: **do not "fix" the pre-existing ones
inside a feature commit** — it is a whole-directory sweep or nothing.

**Not verified here, and it needs the owner:** T2's manual check — editing the
real imported Harry and confirming ONE row with the edited values, seeing the
409 text on a second "Harry", archiving/unarchiving through the toggle, and
confirming the already-soft-deleted Harry renders as **Archived** rather than
"SOLD". That needs the live table; tests can assert the contract, not the data.

**`ruff check backend/scripts` is NOT clean, and it was not clean before T17 either.**
`daily_sync.py` carries a pre-existing `I001` (import sort) and a `DTZ011`, verified by
running ruff against the file at `HEAD`. The project's documented lint command is
`ruff check backend/src`, which is why `backend/scripts` has drifted. The two new/edited
scripts are themselves clean. Do not "fix" `daily_sync.py`'s imports inside a feature
commit — it is a whole-directory sweep or nothing.

**Not verified here, and it needs the owner:** T17's manual check — running the nightly
job against live data with `CATALOG_REFRESH_CARDS_PER_NIGHT=50` and confirming 50
`brief` rows come back `full`, then proving the script at `--limit 200`. Both write to
the live table and spend real requests against a volunteer-run free API. **Prerequisite:
the ECS task role needs `dynamodb:Scan`** — the candidate selection scans the catalog,
the same permission gap CLAUDE.md records for catalog search.

**Also not verified here, and it needs the owner:** T15's manual check — searching
`Charizard`/`Pikachu` in all five pickers with real cards in hand, confirming a
Japanese card on the `missing_english_name` queue is identifiable by its art, and
checking 100%/150% zoom. That needs live catalog data and a human holding a card;
tests can assert classes, not readability.

**~~The frontend failures are `ChatPanel.test.tsx` and are NOT yours… do not chase it.~~
FIXED 2026-08-11 — and that instruction was wrong.** It was not "flakiness", it was two
real defects, and telling three successive tasks not to look at it is why it survived RFC
0009 and most of RFC 0010's planning:

1. `beforeEach` called `vi.clearAllMocks()`, which does **not** drain the
   `mockResolvedValueOnce` queue — proven with a two-test probe, where the second test
   received the first's leftover value. So a test that ended early handed its unconsumed
   replies to its neighbours, which then failed on another test's data.
2. The history-cap test typed ~120 characters through `userEvent` at the default
   per-keystroke delay: **3317 ms of the 5000 ms budget with the machine idle**, so under
   full-suite parallel load it timed out — and its 12 queued replies cascaded into four
   neighbours.

That is why the failure count wobbled between 1 and 7 and why the file passed 12/12 alone.
Fixed with `mockedApiFetch.mockReset()` and a shared `userEvent.setup({ delay: null })`
(3317 ms → 994 ms). **Verified across five consecutive full-suite runs: 609/609 every
time.** The rule went into CLAUDE.md and the `testing` skill.

**The lesson for the rest of this RFC:** a wobbling failure *count* is the tell that one
failure is causing the others — read the first one. "Pre-existing" assigns blame; it says
nothing about whether the suite is healthy.

**A pass count is not a suite result.** RFC 0009's recorded "575 passed" was read off a red
run and the fail count was never carried across, which is how a stale sign-off happened.
Record both numbers, always.

Use `./.venv/Scripts/python.exe`, never bare `python` — the bare form resolves to an
unrelated venv with no pytest. If results look impossible, this checkout is a git worktree
and a global editable install can shadow it with the sibling repo's backend; verify which
package loaded before debugging anything else (CLAUDE.md).

Both vitest suites fail spuriously if invoked as `npx vitest` ("Vitest failed to find the
runner"). Use the documented `npm test --workspace=…` form; the failure is the invocation,
not the code.
