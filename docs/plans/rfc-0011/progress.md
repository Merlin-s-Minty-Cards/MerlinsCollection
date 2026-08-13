# RFC 0011 — Inventory Column Controls & the Unmatched Queue: PROGRESS

**Read this first.** It is the state of the world for anyone picking up a task.

**This file is the tracked progress file — not `claude-progress.txt`.** That one is
gitignored (`.gitignore:60`), so it is local-only and your edits to it will never appear
in `git status` or reach anyone else. Record all RFC 0011 status **in this file**.

**Last updated:** 2026-08-13 (**T1–T4 DONE**. Next up: T5, T6)
**Branch:** `Polishing-For-Deployment`
**RFC:** [`docs/rfcs/0011-inventory-column-controls-and-unmatched-queue.md`](../../rfcs/0011-inventory-column-controls-and-unmatched-queue.md)
**Task index:** [`README.md`](README.md)
**Source of the requests:** the owner's message of 2026-08-13, plus three design answers
and two scope additions given the same day (recorded in the RFC under "Owner decisions").

## Next: T5, T6

**The table track (T1–T4) is COMPLETE.** Every inventory column now sorts and filters,
server-side, from one registry per layer. What remains in this RFC is the unmatched-queue
track (T5–T10), the shared card search panel (T11) and verification (T12).

There is no merge blocker in this RFC and nothing is waiting on an owner action.

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
| T4 | Per-column filters frontend | **DONE** | (see below) | 44 filters covering all 31 filterable columns (`_image`/`_actions` excluded). **Three changes vs the task doc, all forced:** (1) `product_type` is a **select**, not the text box the doc's table listed — it is `FieldKind.SELECT` on the backend and `OPS_BY_KIND[SELECT]` is `{eq}`, so a `contains` would have been a guaranteed 422; (2) `admin-api.ts` had to learn **repeatable params** — it used `searchParams.set`, which keeps only the LAST `filter=` and silently widens the result set; (3) the doc's page test was rewritten **scoped to the filter panel**, because the column picker's checkbox for a column carries the same accessible name as that column's filter, so the unscoped `getByLabelText('Notes')` matches both once the picker is open. **Fixed in passing:** the Ownership filter sent `consigned` where the backend accepts only `owned`/`cosigned` — picking "Cosigned" 400'd. |
| T5 | `no_catalog_match` model | TODO | — | |
| T6 | Triage unlink + park | TODO | — | |
| T7 | Pairing suggestions endpoint | TODO | — | |
| T8 | Unmatched queue page | TODO | — | |
| T9 | `first_seen_at` + sync | TODO | — | |
| T10 | Dashboard widget | TODO | — | |
| T11 | Shared card search panel | TODO | — | |
| T12 | Docs + verification | TODO | — | |

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
