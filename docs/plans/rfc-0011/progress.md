# RFC 0011 — Inventory Column Controls & the Unmatched Queue: PROGRESS

**Read this first.** It is the state of the world for anyone picking up a task.

**This file is the tracked progress file — not `claude-progress.txt`.** That one is
gitignored (`.gitignore:60`), so it is local-only and your edits to it will never appear
in `git status` or reach anyone else. Record all RFC 0011 status **in this file**.

**Last updated:** 2026-08-13 (plan written; **no task executed yet**)
**Branch:** `Polishing-For-Deployment`
**RFC:** [`docs/rfcs/0011-inventory-column-controls-and-unmatched-queue.md`](../../rfcs/0011-inventory-column-controls-and-unmatched-queue.md)
**Task index:** [`README.md`](README.md)
**Source of the requests:** the owner's message of 2026-08-13, plus three design answers
and two scope additions given the same day (recorded in the RFC under "Owner decisions").

## Start at T1 or T5 — the two tracks are independent

There is no merge blocker in this RFC and nothing is waiting on an owner action. The
table track (T1–T4) and the unmatched-queue track (T5–T10) touch disjoint files.

**T5 is the load-bearing task of the whole RFC.** One line in
`services/triage.is_missing_card_id` is what lets a card leave a queue that is otherwise
permanently floored. Everything on the queue track is downstream of it.

## Status

| # | Task | Status | Commit | Notes |
|---|---|---|---|---|
| T1 | Generic sort backend | **DONE** | (see below) | Registry covers all 38 model fields; 2 excluded with reasons. **No existing test asserted the silent-unsorted behavior**, so Risk 1 did not materialize — all 530 admin router tests passed unchanged. Verified every caller that sends `sort`: only Prep Queue and Inventory, and all their column keys resolve. |
| T2 | All columns sortable | TODO | — | |
| T3 | Generic filter backend | TODO | — | |
| T4 | Per-column filters frontend | TODO | — | |
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
| of those, sortable today | **8** | `sortable: true` count |
| filters in `INVENTORY_FILTERS` | **12** (3 of them column-less) | same file |
| sort fields the backend accepts | **8** | `_sort_admin_results` if/elif chain |
| catalog rows carrying `first_seen_at` | **0** — the field does not exist | `models/catalog.py` |
| catalog rows total (measured 2026-08-06) | 31,603 | CLAUDE.md, Ops |

## Blocked / needs the owner

Nothing. Every decision this RFC needed was taken on 2026-08-13.

## Follow-ups

See [`follow-ups.md`](follow-ups.md). Two are already known and were deferred
deliberately in the RFC's Open Questions: **bulk park** and **notifying on a new
candidate**.
