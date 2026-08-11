# RFC 0010 — Admin Round 8: PROGRESS

**Read this first.** It is the state of the world for anyone picking up a task.

**This file is the tracked progress file — not `claude-progress.txt`.** That one is
gitignored (`.gitignore:60`), so it is local-only and your edits to it will never appear in
`git status` or reach anyone else. Record all RFC 0010 status **in this file**.

**Last updated:** 2026-08-10 (T0 DONE — the RFC 0009 merge blocker is cleared)
**Branch:** `Polishing-For-Deployment`
**RFC:** [`docs/rfcs/0010-admin-round8-ledger-corrections-and-slab-manual-only.md`](../../rfcs/0010-admin-round8-ledger-corrections-and-slab-manual-only.md)
**Task index:** [`README.md`](README.md)
**Source of the requests:** the owner's `The plan.pdf` (12 items) plus two review comments
on 2026-08-10 — the money-input report and the PSA/scanner reversal.

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
| T1 | `MoneyInput` rollout | **NOT STARTED** | — | T0's helper exists: `MoneyInput` takes `label` / `value` / `onChange(raw, parsed)` and callers must gate on `parsed === null`, **never falsiness** — `0` is a real cost. Read the three T0 rows in [`follow-ups.md`](follow-ups.md) first: the two `parseFloat` sticker sites become live bugs the moment their `type="number"` goes, and `sales.py`/`trades.py` still have the single-pass write shape T0 fixed only in `purchases.py` |
| T2 | Consignor row fork | **NOT STARTED** | — | Same defect `put_show` was fixed for in RFC 0008 T7; needs a one-time reconcile for rows already forked in production |
| T3 | Triage reasons + filter | **NOT STARTED** | — | The query is NOT broken; the 266 rows are import flags. **No sticker reason** (owner decision) |
| T4 | Triage search | **NOT STARTED** | — | Frontend only; `name` already works on the endpoint |
| T5 | Detail modal live updates | **NOT STARTED** | — | Changes `onUpdated`'s signature across six mounting pages; parameter is optional so nothing breaks |
| T6 | Detail modal layout | **NOT STARTED** | — | Must be checked by a human at 100/150/200% zoom. A test can assert classes, not typeability |
| T7 | Prep Queue location | **NOT STARTED** | — | Backend already has everything; pure wiring |
| T8 | Local date formatting | **NOT STARTED** | — | Test **must** pin a negative-offset `TZ` or it is theatre |
| T9 | Signed ledger amounts | **NOT STARTED** | — | Presentation only. Do not invert signs in storage |
| T10 | `Transaction.batch_id` | **NOT STARTED** | — | No heuristic backfill. Legacy rows render as single-row groups |
| T11 | Transaction void | **NOT STARTED** | — | **Largest risk in the RFC.** One countability predicate, every reader named in the task doc |
| T12 | Slabs: PSA out, price at intake | **NOT STARTED** | — | Keep `CertInput`'s Enter handling. Pricing runs AFTER commit, never inside it |
| T13 | Grouped navigation | **NOT STARTED** | — | Every route path unchanged |
| T15 | Card picker: image + price | **NOT STARTED** | — | The rule is already in **CLAUDE.md**; this makes the code match. Art **and** prices are already in the search response — Triage/Slabs/Market discard both. `/admin/buy` is the reference row. **Ships independently of T17**: build the absent-price states properly and there is no frontend follow-up |
| T17 | Weekly catalog price cycle | **NOT STARTED** | — | ~5,500 cards/night stalest-first (~24 min), six nights + Friday slack. Needs **no schema change** — `last_synced_at` + `detail` already carry the ordering. A full nightly pass would outlive the catalog lock. **Second deliverable: `scripts/reprice_catalog.py`** — the owner's one-time overnight full re-price, chunked so it never holds the lock for more than ~9 min, resumable for free via stalest-first |
| T16 | Unmatched-card valuation | **NOT STARTED** | — | Answers "how do we price a card with no catalog match". Mostly surfacing a capability that already works: the nightly job skips unlinked items |
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
| **Run `scripts/reprice_catalog.py` overnight once, after T17 lands** | It prices all ~31,300 unheld catalog rows in one ~2 h 18 min run, so the weekly cycle starts from full coverage instead of taking ~6 nights to reach it. Dry-run it first (it prints the ETA), then `--execute --confirm-table merlins-cards`. It is chunked and resumable — Ctrl-C and re-run is safe | nothing; the nightly cycle gets there on its own, this just skips the wait |
| **Work the `blank_condition` queue — this is data remediation, not code** | Every card the import found with no condition was stored as **NM**, the most expensive tier, and customer prices scale down from it. Until someone checks each card, those are listed **above** their value (LP → 1.22×, MP → 1.72×). T3 makes them filterable and fixable in place; **only the owner can actually fix them.** Surface the count during T3 so the size of the job is known | nothing in code; real money on the live site |
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
| Frontend | 609 tests, **604 passed / 5 failed** | ~35s | **RED — same pre-existing ChatPanel flake** |
| `ruff check backend/src` | — | ~3s | clean |
| `npm run lint --workspace=frontend` | — | ~5s | clean (one pre-existing `<img>` warning in `CardDetailModal`) |
| `npm run build --workspace=frontend` | — | — | exit 0 — **run this one**, `StagedSlab.buy_price` changed type and vitest does not typecheck |

**The frontend failures are `components/inventory/__tests__/ChatPanel.test.tsx` and are
NOT yours.** That file and its component are untouched by this branch (`git log main..HEAD`
is empty for both) and it passes **12/12 in isolation** — it is flakiness that only appears
under full-suite parallel load. Do not chase it; carry the count into T-FINAL and say so.

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
