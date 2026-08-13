# RFC 0011 — Inventory Column Controls & the Unmatched Queue: PROGRESS

**Read this first.** It is the state of the world for anyone picking up a task.

**This file is the tracked progress file — not `claude-progress.txt`.** That one is
gitignored (`.gitignore:60`), so it is local-only and your edits to it will never appear
in `git status` or reach anyone else. Record all RFC 0011 status **in this file**.

**Last updated:** 2026-08-13 (**T1–T6 DONE**. Next up: T7)
**Branch:** `Polishing-For-Deployment`
**RFC:** [`docs/rfcs/0011-inventory-column-controls-and-unmatched-queue.md`](../../rfcs/0011-inventory-column-controls-and-unmatched-queue.md)
**Task index:** [`README.md`](README.md)
**Source of the requests:** the owner's message of 2026-08-13, plus three design answers
and two scope additions given the same day (recorded in the RFC under "Owner decisions").

## Next: T7

**The table track (T1–T4) is COMPLETE**, and the unmatched queue can now be **filled**
(T5, T6) — but it cannot yet be **read**: there is no `/admin/unmatched` page (T8), so
today a parked card is only reachable via
`GET /admin/inventory/search?no_catalog_match=true`. That is the gap to close next, and
T8 wants T7's suggestions first.

There is no merge blocker in this RFC and nothing is waiting on an owner action.

### What T5/T6 left behind that T7 and T8 need to know

- **The write contract is settled and lives in `frontend/lib/triage.ts`** — `parkBody()`
  and `unlinkBody()`. T8's queue page should call the same two, not restate the fields.
- **`reasonsFor` mirrors the server's suppression** now. Any page predicting triage
  reasons after a park must pass `no_catalog_match: true` into it, or its optimistic row
  keeps a `missing_card_id` chip it no longer has.
- **Assigning a `card_id` unparks server-side**, so T8's "pair it" action needs to send
  only `card_id` — sending `no_catalog_match: false` alongside is redundant, and sending
  it *without* a `card_id` would return the row to Triage.
- **`no_catalog_match_at` is the queue's sort key** ("parked 3 weeks ago"). It is a
  `datetime`, so render it through `lib/dates.ts` — `formatTimestamp`, never `new Date()`
  on a date-only string.

### What T4 left behind that later tasks need to know

- **`admin-api.ts` now sends an ARRAY param as a repeatable one** (`?filter=a&filter=b`),
  via `URLSearchParams.append`. Any endpoint wanting a repeatable parameter gets it for
  free; passing an array used to stringify to `"a,b"` under `set`.
- **`buildFilterParams` is the only place that knows the two spellings.** New filter →
  add a registry entry; do not add a branch to `fetchItems`.
- **A filter's `kind` must match `FILTERABLE_FIELDS` in
  `services/inventory_filters.py`.** The kind picks the operator and the backend 422s an
  operator its own kind disallows. `only ever emits ops the backend registry accepts`
  catches a drift, but only against a hand-copied table in the test.
- **`useShows()`** (`frontend/lib/use-shows.ts`) is new — show ids as `{value, label}`,
  archived included, empty list on failure. T8/T10 can reuse it.

### What T1–T3 left behind that T5 needs to know

- **`FieldKind` / `FilterOp` string values are the wire contract T4 mirrors in
  TypeScript** — `text`, `select`, `range`, `dateRange`, `presence`; `contains`, `eq`,
  `gte`, `lte`, `isnull`, `notnull`. Character for character.
- **The generic parameter is `?filter=field:op:value`, repeatable**, split on the first
  two colons only (a `card_id` contains one).
- **`no_catalog_match` and `no_catalog_match_at` are ALREADY in both backend
  registries**, sorting and filtering as all-missing until T5 adds the model fields.
  T5 does not need to come back and register them.
- **`_validate_sort` and `_validate_filters` run before the table read**, next to
  `_validate_triage_reason` in `routers/admin/inventory.py`.

**T5 is the load-bearing task of the whole RFC.** One line in
`services/triage.is_missing_card_id` is what lets a card leave a queue that is otherwise
permanently floored. Everything on the queue track is downstream of it.

## Status

| # | Task | Status | Commit | Notes |
|---|---|---|---|---|
| T1 | Generic sort backend | **DONE** | (see below) | Registry covers all 38 model fields; 2 excluded with reasons. **No existing test asserted the silent-unsorted behavior**, so Risk 1 did not materialize — all 530 admin router tests passed unchanged. Verified every caller that sends `sort`: only Prep Queue and Inventory, and all their column keys resolve. |
| T2 | All columns sortable | **DONE** | (see below) | 31 of 33 columns now sortable; `_image` and `_actions` deliberately not. Inventory page tests (27) pass unchanged — `handleSort` and the desc-first default were not touched. |
| T3 | Generic filter backend | **DONE** | (see below) | 36 filterable fields. **Design change vs the task doc:** bound parsing moved from evaluation into `validate_filters`, because `apply_filters` is a comprehension and never evaluated a bad bound on an empty result set — a 422 that fired only when rows happened to exist. Caught by `test_an_unparseable_bound_is_a_422`. Named params left hand-written as planned: `name`, `condition`, `min_price`/`max_price`, `set_id`/`card_number`/`artist`. |
| T4 | Per-column filters frontend | **DONE** | `2942598` | 44 filters covering all 31 filterable columns (`_image`/`_actions` excluded). **Three changes vs the task doc, all forced:** (1) `product_type` is a **select**, not the text box the doc's table listed — it is `FieldKind.SELECT` on the backend and `OPS_BY_KIND[SELECT]` is `{eq}`, so a `contains` would have been a guaranteed 422; (2) `admin-api.ts` had to learn **repeatable params** — it used `searchParams.set`, which keeps only the LAST `filter=` and silently widens the result set; (3) the doc's page test was rewritten **scoped to the filter panel**, because the column picker's checkbox for a column carries the same accessible name as that column's filter, so the unscoped `getByLabelText('Notes')` matches both once the picker is open. **Fixed in passing:** the Ownership filter sent `consigned` where the backend accepts only `owned`/`cosigned` — picking "Cosigned" 400'd. |
| T5 | `no_catalog_match` model | **DONE** | `e94b6da` | **T6, T7 and T8 are unblocked.** Two fields on `_ItemBase`, one suppression inside `is_missing_card_id`, one query param, one PUT transition helper. The queue is `GET /admin/inventory/search?no_catalog_match=true` — **no new list endpoint**, and **nothing backfilled** (pinned by `test_the_unmatched_queue_ships_empty`). The sealed/bulk guard has to live in the ROUTER, not the model validator: a sealed item has no `card_id` to be non-None, so the invariant cannot see it. `_apply_no_catalog_match_transition` **pops a client-sent `no_catalog_match_at`** before doing anything — the doc only said "server-stamped", which a client could otherwise satisfy by sending its own. Blast radius checked beyond the named selection: `backend/tests/{routers,services,models}` = **1483 passed**. |
| T6 | Triage unlink + park | **DONE** | (see below) | Both entry points, plus the `reasonsFor` mirror of T5's suppression. **The unlink is ONE `PUT`, not three** — three could half-succeed and leave a card unlinked but still carrying the wrong promo's price, which is worse than the state being repaired. `onRepointed` widens to `string \| null`; the `null` branch must fold `no_catalog_match: true` into its optimistic prediction or the row re-renders with a `missing_card_id` chip for a frame before dropping. The confirm copy **names the price** (`formatMoney`) and has a separate branch for a row with no stored value, so it never reads "its market value of $0.00 will be cleared". The "No match in TCGdex" action is hidden when `item.card_id` is already null — that row's action is the row-level button instead. Consumers of `reasonsFor` re-checked (outgoing, `CardDetailModal`, `TriageRowAction`): **127 passed**. |
| T7 | Pairing suggestions endpoint | TODO | — | |
| T8 | Unmatched queue page | TODO | — | |
| T9 | `first_seen_at` + sync | TODO | — | |
| T10 | Dashboard widget | TODO | — | |
| T11 | Shared card search panel | TODO | — | **RE-SCOPED by Part 2** — no longer adopted in Buy (deleted) or Trade (rebuilt). Adopt in Slabs, Triage, Market, +Unmatched. T14 composes it. |
| **T13** | Slabs come in through a trade | TODO | — | RFC Part 2. Trading a slab OUT already works; only incoming is broken (`trades.py:792` hardcodes `kind: "raw"`). |
| **T14** | Deal search + add-card form | TODO | — | RFC Part 2. Depends on T11 + T13. |
| **T15** | Unified deal page, three modes | TODO | — | RFC Part 2. Depends on T13 + T14. |
| **T16** | Retire `/admin/buy` and `/admin/sell` | TODO | — | RFC Part 2. Depends on T15. The only task that deletes reachable pages. |
| T12 | Docs + verification | TODO | — | **Runs LAST, after T16.** |

## Decisions

Owner decisions taken during design on 2026-08-13. **These reverse or constrain what the
code does today and are not open for re-litigation during implementation.**

| # | Decision | Why it matters |
|---|---|---|
| 1 | Sorting and filtering stay **server-side** | One code path; the header's `(total)` stays honest; the endpoint keeps the `sort` param other pages share. |
| 2 | Unlinking a card **automatically parks it** in the new queue | The owner's workflow is one action, not two. |
| 3 | Cards that already have no match get a **separate explicit button** to park them | There is nothing to unlink on those rows. |
| 4 | **The queue ships EMPTY** — nothing backfilled or auto-migrated | Owner, verbatim: *"all cards that go there should only be moved under admin supervision."* Pinned by a test in T5. |
| 5 | Unlinking **clears `current_market_value`** and offers the hand-value tool | The inherited figure is the wrong promo's price — the whole complaint. |
| 6 | Ranked suggestions **never replace** full-catalog search | Owner: *"you must also have the option for the user to search the whole catalog if none of those candidates match."* |
| 7 | **One shared card-search component** across all five pickers | Three of five pickers had already lost their card images by drifting apart. |
| 8 | Condition gains a **real ordinal rank** (NM > LP+ > LP > LP- > MP > HP > DMG) | Alphabetical sorting made `LP+` and `LP-` indistinguishable — the exact distinction RFC 0008 T2 stored separately. |
| 9 | An unknown `sort` field becomes a **422**, not a silent unsorted list | Same class as `_validate_triage_reason`. May require updating existing tests that assert the silent form — do that deliberately. |

### Part 2 decisions (2026-08-13, second round) — the unified deal surface

| # | Decision | Why it matters |
|---|---|---|
| 10 | **One route: `/admin/trade`.** `/admin/buy` and `/admin/sell` are **removed**, not redirected | Departs from the `/admin/outgoing` precedent — but that was about *renaming* a page that still existed. These two genuinely stop existing. Sidebar, `mobileItems` and the dashboard quick actions are rewritten in T16. |
| 11 | Sidebar label **"Buy / Sell / Trade"**; mobile bar says **"Deal"** | The long label does not fit four-across on a phone. A deliberate divergence — do not "fix" it into consistency. |
| 12 | **Full-width search on top; Coming In / Going Out side by side; summary rail** | The width IS the fix for the owner's "squished" objection. |
| 13 | Search source **auto-locked by mode**, switchable only in Trade | A control settable one way is noise on two modes of three. |
| 14 | **Incoming is ALWAYS a catalog pick first**, then Raw or Graded | Owner: *"regardless you should be picking a card from the catalog."* Consequence: a manual entry can only ever be raw, because graded pricing joins on `card_id`. |
| 15 | **Condition and grade are never on screen together** | They are alternatives. Showing both invites entering both, and T13 422s a raw leg carrying graded fields. |
| 16 | **Keep three session APIs**; merge only the UI | Highest-risk money paths in the repo. RFC 0010 T0 exists because a partial write in one created real inventory then reported "Nothing was created". |
| 17 | **No hover carries information anywhere on the new surface** | Owner: *"I don't like the show image on hover."* Image + name + price render in search results AND in staged rows. The Sell preview panel is deleted, not restyled. |

## Measurements worth keeping

Taken while writing the RFC on 2026-08-13, from the code rather than from a live table.

| | value | source |
|---|---|---|
| columns in `INVENTORY_COLUMNS` | 33 | `frontend/lib/admin-inventory-columns.tsx` |
| of those, sortable today | **8** → **31** after T2 | `sortable: true` count |
| filters in `INVENTORY_FILTERS` | **12** (3 column-less) → **44** after T4 | same file |
| sort fields the backend accepts | **8** | `_sort_admin_results` if/elif chain |
| catalog rows carrying `first_seen_at` | **0** — the field does not exist | `models/catalog.py` |
| catalog rows total (measured 2026-08-06) | 31,603 | CLAUDE.md, Ops |

## Blocked / needs the owner

Nothing. Every decision this RFC needed was taken on 2026-08-13.

## Follow-ups

See [`follow-ups.md`](follow-ups.md). Two are already known and were deferred
deliberately in the RFC's Open Questions: **bulk park** and **notifying on a new
candidate**.
