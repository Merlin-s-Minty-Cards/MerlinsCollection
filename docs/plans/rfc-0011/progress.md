# RFC 0011 — Inventory Column Controls & the Unmatched Queue: PROGRESS

**Read this first.** It is the state of the world for anyone picking up a task.

**This file is the tracked progress file — not `claude-progress.txt`.** That one is
gitignored (`.gitignore:60`), so it is local-only and your edits to it will never appear
in `git status` or reach anyone else. Record all RFC 0011 status **in this file**.

**Last updated:** 2026-08-13 (**T1–T11 DONE**. Next up: T13, per README.md's task index — T12 runs last, after T16)
**Branch:** `Polishing-For-Deployment`
**RFC:** [`docs/rfcs/0011-inventory-column-controls-and-unmatched-queue.md`](../../rfcs/0011-inventory-column-controls-and-unmatched-queue.md)
**Task index:** [`README.md`](README.md)
**Source of the requests:** the owner's message of 2026-08-13, plus three design answers
and two scope additions given the same day (recorded in the RFC under "Owner decisions").

## Next: T10

**Everything T10 depends on is now DONE.** T7 gives it `items_with_candidates`, T9
gives it `GET /admin/catalog/new-cards`. T10 is a pure read — it should not need to
touch the backend at all.

There is no merge blocker in this RFC and nothing is waiting on an owner action.

### What T9 left behind that T10 needs to know

- **`GET /admin/catalog/new-cards?since_days=30&limit=6`** → `{count, since, cards[]}`.
  `count` is the WHOLE window (never capped by `limit`); `cards` is the rendered sample,
  newest-first. Each card carries `card_id, name, set_id, set_name, number, rarity,
  images, market_price, first_seen_at` — `images` is `{small, large}`, and `market_price`
  is a NEAR MINT catalog figure, never condition-adjusted.
- **`since` is a UTC date**, because the cutoff itself is computed in UTC. Render it
  as-is; do not recompute a window boundary client-side.
- **T7's `items_with_candidates`** (from `GET /admin/unmatched/suggestions`) is the
  other number this widget quotes. The two endpoints are independent reads — fetch both,
  do not derive one from the other.
- **A widget with zero new cards and zero pairable cards is the ordinary state**, not an
  error — same posture as the Unmatched queue's own empty state (T8).

### What T8 left behind that T10 needs to know

- **`GET /admin/unmatched/suggestions` returns `items_with_candidates`**, and T8 renders
  the same rows from the same call. The widget quotes that number; do not recount it.
- **The page's own header count is `ordered.length`** — the size of the parked cohort,
  which is a DIFFERENT number from `items_with_candidates` (cards you can act on). The
  widget should be explicit about which one it is showing.
- **Do not add a sidebar badge for this queue.** The Triage badge stays the only amber
  number in the Back office group; T8 has a test pinning that.

### What T7 left behind that T8 and T10 need to know

- **`GET /admin/unmatched/suggestions?limit=3`** is the only route on the new
  `/admin/unmatched` router. There is **no second list endpoint** — the list stays
  `GET /admin/inventory/search?no_catalog_match=true`.
- **A candidate maps onto `CardPickerRow`'s `PickerCard` with one rename**: send
  `display_price: market_price` and `images: { small: image_small }`; `detail` and
  `last_synced_at` pass through by name, and they are what make the component's absent-
  and stale-price wording honest. **Do not render an absent price as `$0.00`** — and note
  the shared component says *"no price yet"* / *"not priced"* rather than a bare `—`,
  which is strictly more informative and is the rendering T8 should keep.
- **Items with no candidates are still returned**, with `candidates: []`. Only
  `items_with_candidates` excludes them, and it counts ROWS you can act on, never
  suggestions in total — that is the number T10's widget quotes.
- **The response is already ordered oldest-park-first.** T8 re-sorts candidates-first on
  top of that (the task doc's `ordered` snippet), which preserves the age order within
  each group.
- **`score` is one of exactly three values** — `1.0`, `0.7`, `0.5` — and `why` is the
  matching sentence. Render `why`, not the number.

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
| T6 | Triage unlink + park | **DONE** | `c5686b8` | Both entry points, plus the `reasonsFor` mirror of T5's suppression. **The unlink is ONE `PUT`, not three** — three could half-succeed and leave a card unlinked but still carrying the wrong promo's price, which is worse than the state being repaired. `onRepointed` widens to `string \| null`; the `null` branch must fold `no_catalog_match: true` into its optimistic prediction or the row re-renders with a `missing_card_id` chip for a frame before dropping. The confirm copy **names the price** (`formatMoney`) and has a separate branch for a row with no stored value, so it never reads "its market value of $0.00 will be cleared". The "No match in TCGdex" action is hidden when `item.card_id` is already null — that row's action is the row-level button instead. Consumers of `reasonsFor` re-checked (outgoing, `CardDetailModal`, `TriageRowAction`): **127 passed**. |
| T7 | Pairing suggestions endpoint | **DONE** | (this commit) | **T8 and T10 are unblocked.** `GET /admin/unmatched/suggestions?limit=3` (`ge=1, le=10`) → `{items: [{item_id, candidates[]}], items_with_candidates}`; a candidate carries `card_id, name, set_id, set_name, number, rarity, image_small, market_price, detail, last_synced_at, score, why`. **Two fields beyond the task doc's shape, both forced by `CardPickerRow`:** `detail` (T8 must keep `brief` = never fetched vs `full` = no provider covers it — CLAUDE.md calls collapsing them a lie) and `last_synced_at` (so a stale figure shows its age). Both are free; the catalog row is already in hand. **The doc's `_identity` reads a `card_number` field that DOES NOT EXIST on an inventory item** — the number is materialized inside `display_name` as `"Dragonair #181"`, so `identity_of` splits the trailing `#N` back off; without that, `normalize_name` yields `"dragonair 181"` and every lookup misses. A fourth tier was NOT added: an item with no number falls to the 0.7 name-only tier, which is number-blind and reads honestly. Tests live at `tests/routers/admin/test_unmatched.py`, not the doc's `tests/routers/test_admin_unmatched.py` — `admin_client` is defined in that package's conftest. Blast radius: `backend/tests/{routers/admin,services}` = **1255 passed**. |
| T8 | Unmatched queue page | **DONE** | (this commit) | **T10 is unblocked.** `/admin/unmatched`, sidebar entry in **Back office directly after Triage**, icon `Unlink`, **no badge** (the Triage count stays the group's only amber number) and **not** in `mobileItems`. The page reads `GET /inventory/search?no_catalog_match=true` + `GET /unmatched/suggestions?limit=3` in **one `Promise.all`** — not `allSettled`, because suggestions failing while the list succeeds renders every row silently claiming it has no candidates, a wrong answer wearing the shape of a right one. Pair sends **`{card_id}` alone**; Back to Triage sends `{no_catalog_match: false}`; both drop the row with no refetch. **The NM label lives on the COLUMN HEADER** (`Suggestions · Market (NM)`), once, rather than as a caption repeated per row. **The absent-price rendering is `CardPickerRow`'s "no price yet" / "not priced", NOT the task doc's bare `—`** — the doc predates the shared component, and the component keeps the `brief` vs `full` distinction CLAUDE.md forbids collapsing. `formatTimestamp` for the parked stamp (it is a datetime); tests pin `America/Los_Angeles` via `_timezone.ts` with **no fake timers at all**. Card art is the **placeholder by construction** and `useCardImages` is deliberately not called: a parked item has no `card_id`, so the lookup could never succeed. 36 passed (15 page + 21 shell); Triage's 56 unchanged; `tsc --noEmit` and lint clean. |
| T9 | `first_seen_at` + sync | **DONE** | (this commit) | **T10 is unblocked.** `CatalogCard.first_seen_at: datetime \| None`, written only by the repository, never by a caller. **`repo.list_cards_by_language` does not exist** (the task doc assumed it); membership is instead built from the SAME `list_cards_by_set` queries the set-membership check already runs, unioned across every set in the language — no extra request. **The unconditional (reseed) path pre-reads `first_seen_at` via one chunked `BatchGetItem` per page** — safe there because that path is a whole-item replace that overwrites regardless of what it reads, so the read adds no decision-making window. **The conditional (priced-preserving) path could NOT do the same** — a pre-read in front of it reopens the exact Phase 2.0a race the `ConditionExpression` exists to close, caught immediately by the existing `test_the_seed_decides_at_write_time_not_by_pre_reading`. Fixed by reading the prior value off the conditional `put_item`'s own `ReturnValues="ALL_OLD"` instead, inside the same atomic operation — one extra `update_item` per card to restore it, accepted and recorded in follow-ups.md. `_sync_new_sets` now ALWAYS walks `iter_brief_cards` (never gated on `missing_set_ids`), and membership is checked per-CARD against `held_ids`, not per-set — `cards_added_to_existing_sets` is the new summary field. `GET /admin/catalog/new-cards?since_days=30&limit=6` reads `catalog_cache`, counts only non-null-stamped rows, and returns `since` as the **UTC** date (the cutoff is computed in UTC; a locally-derived `since` would name a day the filter did not use). Blast radius (`services + routers/admin + scripts + models`): **1615 passed**, ruff clean. |
| T10 | Dashboard widget | **DONE** | `dd40826` | A fourth `ActionCard`, "Ready to pair" (`action-pairable`), added to the Needs-attention grid (now 4-across). Count is **M** (`items_with_candidates` from `/unmatched/suggestions`); hint carries **N** (`count` from `/catalog/new-cards?since_days=30`) as `"{N} new catalog cards in 30 days"`, falling back to `'Unmatched cards with a match'` while N is still loading/null. Both reads joined the dashboard's existing single `Promise.all`, each `soft()`-wrapped like the other six. **`pairableCount` (M) was added to `actionCounts`; `newCardCount` (N) deliberately was not** — N is news, not work, and must never suppress the all-clear panel. Both a zero-M and a zero-N render as the calm "0", never an error copy. 17/17 dashboard tests pass (12 pre-existing + 5 new); lint clean. |
| T11 | Shared card search panel | **DONE** | (this commit) | New `CardSearchPanel` (`components/admin/shared/CardSearchPanel.tsx`): name + number + set, `CardPickerRow` results, permanent `onManualEntry` control when provided. Backend fix: `GET /admin/market/search`'s `number` filter now normalizes both sides through `normalize_number`/`number_keys` (`services/card_text.py`), so `182`, `182/167` and the Excel artifact `182.0` all find a card stored as `182/167` — was exact-match only. **Adopted in Slabs** (`SlabEntryForm`, replacing its inline search+picker; the "Enter manually instead" button focuses the name field, satisfying the owner's permanent-affordance rule) **and Triage's `RepointDialog`** (`onManualEntry` omitted — must resolve to a genuine catalog row; its "no match" answer is "No match in TCGdex"/T6's park action). **Unmatched's `CatalogSearchDialog` also swapped** (follow-ups.md row 6, closed), `onManualEntry` omitted — a parked card pairs with a row that already exists. **Market did NOT adopt it** — see follow-ups.md row 10: its error-with-retry state, name-match confidence chip and watchlist star action have no equivalent in the shared component's API, so Market kept its own search/fetch/error machinery and gained number + set fields directly instead. Two props beyond the task doc's interface, both forced by real callers: `onNameChange` (Slabs needs the typed-but-unselected name for its free-text fallback) and `nameInputRef` (preserves the cert-Enter-advances-to-name wedge-scan handoff CLAUDE.md calls load-bearing). 180 tests pass across the touched files (CardSearchPanel 9, SlabEntryForm 11, Slabs page 24, Triage 56, Market 24, Unmatched 16, plus SlabList/dashboard unaffected); backend `test_admin_market.py` 38 passed; `tsc --noEmit` and both lints clean. |
| **T13** | Slabs come in through a trade | **DONE** | `ad83409` | RFC Part 2. `POST /admin/trades/{id}/incoming` now accepts `kind: "raw" \| "graded"` (default `"raw"`), validates symmetrically (both directions 422), and `confirm` branches the item build on `kind` so a graded leg lands as `GradedInventoryItem` / `ItemCategory.GRADED` instead of raw. Notes for T14/T15: incoming-leg keys are `card_id` (required for graded), `name`, `agreed_value`, `kind`, and graded-only `company`, `grade`, `cert_number`, `grade_label`; raw-only `condition`, `finish`. |
| **T14** | Deal search + add-card form | **DONE** | `ccde40b` | RFC Part 2. `DealSearchPanel` (catalog via T11's `CardSearchPanel`, or inventory via `/inventory/search?status=available` — the inventory picker had no image at all before this), `IncomingCardForm` (catalog-pick-first, kind toggle raw/graded, condition and grade never both rendered per decision 15, cert-owned warning that never blocks Add, manual entry disclosure forced to raw with a stated reason), `DealCardRow` (the one row shape: image, name, price, zero hover-only information). `buildIncomingLeg` (`frontend/lib/trade-incoming-form.ts`) keeps the raw/graded branches strictly disjoint so a leg can never carry both a condition and a grade — T13 422s exactly that. **`IncomingLeg` also carries optional `set_name`/`card_number`, manual-entry-only** — `trades.py:451-452` already reads these keys and dropping them silently would lose what an operator typed for an unmatched card. **Fix round 1 caught in review:** language values were lowercase `en`/`ja`; `InventoryItem.language` is a case-sensitive `EN`/`JP` StrEnum — fixed, with a test now pinning the emitted casing. 30 tests pass; lint clean. **T15 imports `IncomingLeg` from `frontend/lib/trade-incoming-form.ts`** with exactly the keys above; `onPickInventory` is typed against a local `DealInventoryItem` (no canonical `InventoryItem` type exists frontend-side) — widen it if T15 needs fields it omits. |
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
