# RFC 0010 — Task Plan Index

Execution plan for
[RFC 0010](../../rfcs/0010-admin-round8-ledger-corrections-and-slab-manual-only.md).
Each task below is a **self-contained document** — hand exactly one to a fresh
conversation and it has everything it needs without re-reading the RFC.

**Branch:** all tasks land on `Polishing-For-Deployment` (one branch, many commits).

**Progress:** update [`progress.md`](progress.md) at the end of every task. That file is
the first thing a new conversation should read.

**Test discipline (owner decision, carried over from RFC 0008 and 0009):** do NOT run the
full suite per task. Each task doc names the *narrow* test selection to run while
working. The full suite runs once, at the end, via T-FINAL.

**TDD gate (CLAUDE.md, binding):** each doc has an explicit RED section. Write those
tests, show the owner the failing output, **wait for confirmation**, then go GREEN. Never
combine phases.

**Out-of-scope findings:** append to [`follow-ups.md`](follow-ups.md). Do not fix them as
a side errand.

## ⚠️ T0 IS A MERGE BLOCKER — start there

RFC 0009's T-FINAL is **re-opened and blocked** on a partial-write money bug in the slab
commit path (`docs/plans/rfc-0009/progress.md`, Blocked table). The owner's Round 8 review
independently reported the operator-facing half of it — *"typing 1,300 for cost will break
the commit, but typing 1300 is accepted. Both should work."*

**T0 closes it and unblocks the RFC 0009 merge.** Nothing else here matters if a five-slab
batch can still write two rows of real inventory and then report "Nothing was created".

The pre-existing frontend `ChatPanel.test.tsx` flakiness recorded in RFC 0009's progress
file is **not yours to fix** — it passes 12/12 in isolation and is untouched by either
branch. Note it in T-FINAL, do not chase it.

## One task per conversation — and how each one ends

**Every task doc carries the same "Done means" contract, and it is binding.** A task
conversation is finished when, and only when:

1. the narrow test selection named in the doc **passes**, with the output shown;
2. `progress.md` is updated — status `DONE`, the commit sha, a Notes line if a later task needs
   to know something, and any surprising decision added to the Decisions table;
3. out-of-scope findings are appended to [`follow-ups.md`](follow-ups.md);
4. **the work is committed** — one focused commit (or a small series), conventional-commit style
   matching this branch's history (`feat(slabs):`, `fix(triage):`, `docs(rfc-0010):`);
5. **the conversation's last output is a copy-pasteable prompt** for a fresh conversation to pick
   up the next task in the chain, in the exact form below.

Point 5 is what makes this plan executable across 19 sessions without the owner having to
remember where they were. **A task that ends without emitting the next prompt is not done.**

### The execution chain

Run them in this order. It respects every dependency in the table below, and each doc names its
own successor so a session never has to re-derive it:

```
T0 → T1 → T15 → T17 → T2 → T3 → T4 → T5 → T6 → T7 → T16
   → T8 → T9 → T10 → T11 → T12 → T13 → T14 → T-FINAL
```

T0 is first because it unblocks the RFC 0009 merge. T15 and T17 come early because they are the
owner's newest report and they are independent of everything else.

### The prompt to start any task

```
Read docs/plans/rfc-0010/progress.md and docs/plans/rfc-0010/<task-file>.md.

Execute that task only, following the RED gate in the doc: write the failing
tests first, show me the failing output, and wait for my confirmation before
implementing. Do not start any other task.

When it is done: update progress.md and follow-ups.md, commit the work, and end
your reply with a ready-to-paste prompt for the next task in the chain.
```

## Vertical slicing

The cut lines, in order of what they buy:

- **After T0** — the branch is mergeable. This is the only mandatory line.
- **After T7** — every day-to-day friction the owner reported is gone: consignors edit
  cleanly, Triage is drainable and searchable, the detail modal is usable and updates
  live, Prep Queue filters by location.
- **After T11** — the ledger is *correct*: signed, grouped, and a mis-rung sale can be
  undone. This is the largest and riskiest block; T10 and T11 go together or neither goes.
- **After T13** — the reshapes land (slabs without PSA, grouped navigation).
- **After T16** — the two rules the owner raised in review are enforced in code: every card
  picker shows the card, and a card with no catalog match can still be priced and stickered.

If appetite runs out, stopping after T7 leaves a coherent product. Stopping between T10
and T11 does not — a `batch_id` nothing groups by is dead weight.

**T14 (docs) runs after T15 and T16 despite its number.** It has to describe what shipped, and
those two land features. The numbering reflects when each task was planned, not the order.

**T15 is a good early task if you want a quick win** — it has no dependencies, no backend
change, and it fixes the thing the owner called *"very hard"* to work around daily.

## Tasks

| # | Doc | Scope | Layer | Depends on |
|---|---|---|---|---|
| T0 | [t0-money-input-and-partial-write.md](t0-money-input-and-partial-write.md) | **MERGE BLOCKER.** `parseMoney` + `MoneyInput`, applied to the slab Cost field; `buy_price` 422 at add; `confirm_buy_session` validates the whole batch before writing any of it | full-stack | — |
| T1 | [t1-money-input-rollout.md](t1-money-input-rollout.md) | `MoneyInput` replaces the `type="number"` money fields on Buy, Sell, Trade, Prep Queue, Show Prep, Market, Cosigners; the `parseFloat` sites go | frontend | T0 |
| T2 | [t2-consignor-row-fork.md](t2-consignor-row-fork.md) | `put_consignor` sweep, duplicate-name 409, **delete → archive** (hidden by default + "View archived"), `Consignor.archived`, Active/Archived badge, one-time reconcile script | backend + frontend | — |
| T3 | [t3-triage-reasons-and-filter.md](t3-triage-reasons-and-filter.md) | Server-emitted `triage_reasons`, one `triage_reason` filter param, human labels, status scope, an inline **condition** repair tool, bulk clear **excluding `blank_condition`**. **No sticker reason** — owner decision | full-stack | — |
| T4 | [t4-triage-search.md](t4-triage-search.md) | Debounced name search on the Triage page. Backend already supports `name` | frontend | T3 |
| T5 | [t5-detail-modal-live-updates.md](t5-detail-modal-live-updates.md) | Modal owns its item and takes the PUT response; `onUpdated(item)` so parents patch one row instead of refetching (kills the scroll reset) | frontend | — |
| T6 | [t6-detail-modal-layout.md](t6-detail-modal-layout.md) | Wider shell, capped image column, container-query field grid, stacked labels in narrow cells. Verified on triage + show-prep + inventory at 100/150/200% | frontend | T5 |
| T7 | [t7-prep-queue-location.md](t7-prep-queue-location.md) | Sortable location column + location filter. Backend `location` and `location_asc` already exist | frontend | — |
| T8 | [t8-local-date-formatting.md](t8-local-date-formatting.md) | `lib/dates.ts`: every `new Date("YYYY-MM-DD")` call site **plus** `todayLocal()` — `toISOString()` makes every post-5pm-Pacific transaction default to tomorrow. Local first, Pacific fallback. **Tests must pin a negative-offset TZ and fake the clock** | frontend | — |
| T9 | [t9-signed-ledger-amounts.md](t9-signed-ledger-amounts.md) | Signed money renderer keyed on transaction type, on Show Analytics and History. Presentation only — storage unchanged | frontend | T8 |
| T10 | [t10-transaction-batch-id.md](t10-transaction-batch-id.md) | `Transaction.batch_id`, written by all three confirm paths; client-side grouping with expandable legs. **No heuristic backfill** | backend + frontend | T9 |
| T11 | [t11-transaction-void.md](t11-transaction-void.md) | Void/restore with audit trail; atomic item-status reversal; ONE shared countability predicate every aggregate uses; stale show snapshots | backend + frontend | T10 |
| T12 | [t12-slabs-psa-out-price-at-intake.md](t12-slabs-psa-out-price-at-intake.md) | Delete the two PSA buttons and the Scan-cert affordance; scoped `refresh-prices?item_ids=`; price after commit, never inside it | full-stack | T0 |
| T13 | [t13-grouped-navigation.md](t13-grouped-navigation.md) | At the show / Back office / Data. Every route path unchanged; badge survives collapse; explicit mobile array | frontend | — |
| T15 | [t15-card-picker-images.md](t15-card-picker-images.md) | **A card is never identified by name alone: name + image + price.** Shared `CardPickerRow`, adopted by all five catalog pickers (Triage, Slabs and Market have neither today). Both fields are already in the response; the backend picks the price figure | frontend (+ 2 fields) | — |
| T17 | [t17-weekly-catalog-price-cycle.md](t17-weekly-catalog-price-cycle.md) | **Every catalog card re-priced weekly, by Friday** — ~5,500/night stalest-first (~24 min) inside the existing nightly job; a full nightly pass would outlive the catalog lock. **Plus `scripts/reprice_catalog.py`**, a chunked, resumable one-time overnight run that prices the whole catalog | backend | — |
| T16 | [t16-unmatched-card-valuation.md](t16-unmatched-card-valuation.md) | A card with no catalog match still gets a price and a sticker: a Triage "set a value by hand" tool, condition-multiplier help, honest coverage reporting | backend + frontend | T3, T15 |
| T14 | [t14-docs-and-ops.md](t14-docs-and-ops.md) | CLAUDE.md, RFC 0009 T2/T5 → WON'T DO, `PSA_API_KEY` out of `.env.example` and docs | docs/ops | T12, T15, T16 |
| T-FINAL | [t-final-verification.md](t-final-verification.md) | Full suite, lint, **`next build`**, smoke checklist, PR | verification | all |

## Owner decisions locked in during planning (2026-08-10)

| Question | Decision |
|---|---|
| Triage's requested "sticker needs to be updated" reason | **Not built.** *"Triage is not for stickers that need updating, it is for cards with correctness issues that need manual fixing from an admin."* The need is served by Prep Queue, which T7 makes filterable by location |
| Editing a consignor | **Must replace the old row, not add one.** The sweep in T2 |
| Deleting a consignor | **Archive**, hidden by default, badge reads **Archived** (never "Sold"), with a "View archived" toggle. No hard delete |
| Timezone | **Local if available, `America/Los_Angeles` as the fallback** — never a fixed −8, which is wrong 8 months a year |
| The spreadsheet importer | **Will never run again.** Nothing refills Triage, so a clear is permanent — and **do not edit the importer** |
| Card search | **Name alone is never sufficient — a card picker MUST show the image AND the price**, and the layout must stay readable while doing it. Now a standing rule in CLAUDE.md, not just a task |
| Catalog price freshness | **Every catalog card re-priced at least once a week, by Friday.** How the work is split was left to me: ~5,500/night, stalest-first, six nights with Friday as slack |
| A card with no catalog match | **Hand-value it.** The nightly job already skips unlinked items, so a typed value survives. T16 makes that discoverable rather than accidental |
| How a recorded transaction is reversed | **Void with an audit trail**, not a hard delete. Matches the Shows "archive, never delete" precedent |
| Sidebar grouping | **At the show / Back office / Data**, Dashboard top-level. Grouped by when you use them |
| Pricing an unmatched slab | **Keep the verified join; unmatched stays unpriced.** The vendor's name search was measured wrong ~1/3 of the time |
| `1,300` in a money field | **Must be accepted, not rejected.** Rules out `type="number"` — the input has to parse, not restrict |
| PSA | **Dropped.** The cert API is now paid; T2/T5 of RFC 0009 become WON'T DO |

## The facts that shape everything

1. **`parseFloat("1,300")` is `1`, and it is not `NaN`.** Measured 2026-08-10. Every
   `isNaN` guard in the codebase passes it. The obvious fix to T0 is a worse bug than T0.
2. **Slabs is the only free-text money field in the admin.** Buy, Sell, Prep Queue, Show
   Prep, Market and `InlineEditCell` are all `type="number"`, which is why the comma has
   never bitten there — the browser refuses the keystroke.
3. **`put_show` already solved T2's bug**, in the same file, for the same reason
   (`services/dynamodb.py:1232-1263`). `put_consignor` never got the sweep.
4. **Triage's query is correct.** Probed directly against the model on 2026-08-10: an
   ordinary EN raw item with a `card_id` is not in the queue. The 266 rows are the
   spreadsheet import's own `needs_review` flags.
4b. **`blank_condition` is a MONEY defect.** The importer defaulted a missing condition to
   `Condition.NM` — the most expensive tier — and every customer price is scaled down from
   it, so an LP card is listed at **1.22×** and an MP card at **1.72×** its value. Never
   bulk-clear that reason; make it easy to fix instead.
4c. **`toISOString().split('T')[0]` is the UTC date.** Measured: 6:30pm Pacific on Aug 10
   yields `2026-08-11`, so every transaction entered after 5pm Pacific defaults to
   tomorrow. Buy, Sell, Trade and the dashboard all do this.
5. **`Transaction` has `trade_id` but no sale/buy equivalent**, so a five-card purchase is
   five unrelated rows. T10 adds the key; there is nothing to group by until it does.
6. **`refresh_graded_prices` already walks never-priced slabs first**, so a slab committed
   a second ago is already at the head of the queue. T12 needs a scope filter, not a second
   pricing path.
7. **Catalog search already returns the card's image AND its prices.** `CatalogCard.images` and
   `.prices` are both populated and `/admin/market/search` serialises both. Triage, Slabs and
   Market throw both away. `/admin/buy`'s dropdown is the correct reference row — copy it (T15).
7b. **But `prices` is EMPTY for ~31,300 of 31,603 rows**, because the nightly depth pass only
   prices cards the business owns. That is why T15 and T17 are one story: T15 can render a price
   immediately, and has nothing to render until T17 fills them in.
7c. **A full-catalog nightly pass is ~2 h 18 min** (measured: 162 ms/card + 100 ms courtesy delay)
   and would **outlive the 3600 s catalog lock TTL** — whose failure mode is catalog rows silently
   disappearing, not a stale price. Hence ~5,500/night over six nights (T17).
8. **`refresh_inventory_market_values` skips items with `card_id is None`** — so a hand-typed
   value on an unlinked card is never overwritten. That is what makes T16 possible, and it is
   already true today.

## Do not

- Do not run `npm test` or the full pytest suite inside a task conversation.
- Do not combine RED and GREEN phases (CLAUDE.md).
- Do not use bare `python` — always `./.venv/Scripts/python.exe` (CLAUDE.md).
- **Do not use `parseFloat` on money.** See fact 1. `parseMoney` (T0) or nothing.
- **Do not "fix" a money field with `type="number"`.** The owner requires `1,300` to work.
- **Do not remove `CertInput`'s Enter-advances handler or its `\r\n` stripping** when T12
  hides the scanner UI. A wedge scanner ends its burst with Enter, and breaking that
  breaks invisibly — hand-typing keeps working.
- Do not write a bare `float` to DynamoDB — `_serialize` coerces, but only where it is
  applied, and the session routers persist raw request JSON (CLAUDE.md Ops).
- Do not backfill `batch_id` from `(date, payment_method, type)`. It fabricates
  transactions that never happened, in the one view where being wrong costs money.
- Do not let any aggregate inline its own "is this voided" check. One predicate, called by
  every reader (T11).
- Do not hard-delete a transaction. The owner chose void.
- Do not add a Triage reason for stickers. Owner decision, above.
- **Do not bulk-clear `blank_condition`.** Those cards are priced to customers as NM.
- **Do not edit the spreadsheet importer.** It will never run again — dead code, live blast
  radius.
- **Do not hard-delete a consignor**, and do not add a 409 in-use guard on archiving one.
- **Do not use a fixed `-08:00`.** IANA `America/Los_Angeles`, and only as a fallback.
- Do not put a metered third-party call inside a write loop (T12). That is T0's bug with a
  worse trigger.
- Do not rename or redirect any admin route while grouping the nav (T13).
- Do not hand-pick a card-art size. Use `TABLE_THUMB_SIZE` / `TABLE_THUMB_COLUMN`.
- Do not hardcode a location list. `useLocations()` (CLAUDE.md).
- Do not skip `next build` in T-FINAL. Vitest does not typecheck, and that is the only
  gate that caught RFC 0009's `?params=[object Object]` bug.
