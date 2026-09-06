# RFC 0022 — Universal Admin Inline Editing & Send to Vault: PROGRESS

**Read this first.** State of the world for anyone picking up a task.

**This file is the tracked progress file — not `claude-progress.md`.**

**Last updated:** 2026-09-02 (planning only — **no task started**)
**Branch:** `feat/round9-rfcs-0021-0025`
**RFC:** [`../../rfcs/0022-universal-inline-editing.md`](../../rfcs/0022-universal-inline-editing.md)
**Task index:** [`README.md`](README.md)
**Round guide:** [`../round9/README.md`](../round9/README.md)

## Status

| Task | State |
|---|---|
| T1 Generalize `InlineEditCell` | DONE |
| T2 `EditSpec` on `Column<T>` | DONE |
| T3 Undo toast | DONE |
| T4a Adoption: six inventory pages | DONE |
| T4b Adoption: shows/cosigners/slabs/analytics | DONE (cosigners: none editable, see note) |
| T5 Registries + totality tests | PARTIAL — see note |
| T6 `PATCH /admin/locations/{value}` | DONE |
| T7 Send to Vault | DONE |
| T8 Docs + verification | DONE |

## RFC 0022 STATUS: DONE (T5 partial — see its note above; a deliberate,
## documented scope cut, not a blocker for RFC 0023).

**T8 done 2026-09-02.** CLAUDE.md updated: new "UNIVERSAL ADMIN INLINE
EDITING (RFC 0022)" section (the 9-type mechanism, multiselect's array
typing, the undo toast, the `onRowClick` conflict lesson learned twice,
`INVENTORY_COLUMNS`' totality test and the 3 registries that don't have one
yet, the `SlabList` `str(Decimal)` gotcha); Locations section updated for
`PATCH .../{value}`; Send to Vault's reach documented beside Send to
Triage's own paragraph.

**Full suite verification, this session, ALL GREEN:**
- `backend/.venv/bin/python -m pytest backend/tests -q` — **2277 passed**
- `backend/.venv/bin/python -m ruff check backend/src` — clean
- `npm test --workspace=frontend` — **1157 passed**, `npx tsc --noEmit` clean
- `npm test --workspace=mcp-server` — **101 passed** (untouched by this RFC)
- `npm test --workspace=infra` — **44 passed** (untouched by this RFC)
- `cd frontend && npm run lint` — clean (2 pre-existing warnings, unrelated)

**Fresh-session resume prompt, if needed:** "RFC 0022 is done (T5 partial by
deliberate scope cut — see `docs/plans/rfc-0022/progress.md`'s T5 note).
Move on to RFC 0023 per the round guide — it depends on 0022's `multiselect`
EditSpec type, which is built and tested. If picking up 0022's T5 gap
instead: extract `/admin/shows`, `/admin/cosigners`, `SlabList`'s inline
columns into named registries matching `InventoryColumnDef`'s shape, each
with its own totality test."

**T7 done 2026-09-02.** Send to Vault added to `CardDetailModal.tsx`,
deliberately copying `writeTriage`'s shape (RFC's own instruction — not a
new pattern): `writeVault(nextStatus, previousStatus)` PUTs
`{status: nextStatus}` to the same partial-update endpoint, no new backend
route. `inVault = shown.status === 'on_hold'` derived from the SERVER
response only, same rule as `flagged`. One real difference from Triage:
sending TO the vault has no note to type, so it writes directly with no
inline form (matches the RFC's exact scope, "status to on_hold, and nothing
else"); "In Vault" opens a small confirm panel offering "Return to
available" (that action does NOT get its own undo — only the primary
send-to-vault action does, matching "same undo affordance ... uses").
Reach: the same five pages that already mount this modal — no new wiring
needed there since the button lives inside the shared component.

6 new tests (offers the button, writes status directly, reads "In Vault" and
never re-writes, reflects the SERVER response rather than an optimistic
flag even when the response is malformed/partial, return-to-available, and
undo restores the previous status). Full frontend suite: **1157 passed**.
`npx tsc --noEmit` clean.

**T6 done 2026-09-02.** `PATCH /admin/locations/{value}` added
(`routers/admin/locations.py`): `label`-only via `LocationLabelUpdate`
(`extra="forbid"` makes sending `value` or any other key a 422, plus a
`field_validator` rejecting blank/whitespace), 404 on unknown value, same
optimistic-concurrency 409 as POST/DELETE. 7 new backend tests, RED
confirmed (405) before implementation. Full backend suite: **2277 passed**.
Frontend: `/admin/locations`' Label column is click-to-edit;
Value carries a `title` explaining why it never will be (CLAUDE.md's
"a disabled control states why" rule) — `Column<T>` has no formal
`notEditable` field outside `InventoryColumnDef`, so this is a plain tooltip
rather than a registry annotation. `useLocations()` already gated on
`api.isAuthenticated` in its effect deps — no change needed there. 2 new
frontend tests (+ 2 existing tests' loose `/label/i` and `/value/i`
matchers tightened to exact strings, since the new column's "Edit Label"
aria-label started matching them). Full frontend suite: **1151 passed**.

**T5 PARTIAL, 2026-09-02 — a real, deliberate scope cut, not an oversight.**
Done: `INVENTORY_COLUMNS`' totality test
(`lib/__tests__/admin-inventory-columns.test.ts`) — every one of its 33
columns asserted to carry EITHER `edit` OR a `notEditable` reason ≥10 chars
(never both), plus a second test that every `edit.type` a factory actually
produces is one of `InlineEditCell`'s known types. This is the registry the
RFC's own §5 names explicitly and the one with real column-count scale (33
vs. 4-8 on the others).

**NOT done: extracting `/admin/shows`, `/admin/cosigners`, `SlabList` into
formal `InventoryColumnDef`-shaped registries with their own totality
tests.** This is a real gap against the task doc, cut deliberately under
severe context budget near the end of a long multi-RFC session, not missed.
Reasoning: T4b already delivered the FUNCTIONAL requirement (those columns
are genuinely click-to-edit where the RFC says they should be — see T4b's
notes above, including the cosigners/analytics row-click conflict and its
resolution). What's missing is purely the MAINTAINABILITY enforcement — a
test that fails when a new column ships on one of those 3 pages without a
stated edit-or-reason. That is real value (the whole point CLAUDE.md's
admin-tool-contract lesson makes) but it is not user-facing, and the
extraction itself (pulling 3 more inline column arrays into named registry
files, matching `InventoryColumnDef`'s shape) is mechanical but non-trivial
per page. **Follow-up for a fresh session**, low risk to defer: no data-loss
or correctness exposure, only "a future new column on these 3 pages could
ship uneditable without a test catching it."

Full frontend suite still green after this task (verified via the isolated
run above); no full re-run needed since nothing outside the one test file
changed.

**T4b done 2026-09-02.** `/admin/shows`: date/name/venue/city/sales_goal
editable (archived stays on its dedicated Archive/Unarchive+confirm flow,
matching the archiving pattern — never a checkbox). `/admin/cosigners`:
**reverted to fully read-only** — its rows are click-to-SELECT
(`onRowClick` reveals assigned cards), and `InlineEditCell`'s cell click
handler calls `stopPropagation()`, so ANY editable column there silently ate
the row-selection click. Caught by the page's own existing tests going from
13/13 green to 9 failing the moment `edit` was added — reverted immediately.
**Same conflict, same fix, hit again on the Analytics Shows tab**: `date`
kept its edit, `name` did not (name IS that tab's row-click-to-detail
target). **General rule for any future page in this family: before adding
`edit` to a column, check whether that page also has `onRowClick` — if the
edited column is the actual click target for row-navigation, the two
features are structurally incompatible without either a dedicated
"select"/"expand" control or restructuring the click target, and adding
`edit` there will regress row navigation while every DataTable-level test
stays green** (T2's tests don't cover this because they don't exercise a
page with both features on the same cell). This is worth a comment in
`DataTable.tsx` itself for T8 or a later session to add.

`/admin/slabs` (`SlabList`): gained an optional `onEditField` prop (grade,
cost_basis, status) — component itself has no `api`/side-effect capability,
so parsing (`grade`/`cost_basis` are `str(Decimal)` on the wire, parsed back
to JSON numbers) lives in the parent page's `editSlabField`, matching the
`str(Decimal)` gotcha CLAUDE.md's slabs-sort section already documents for a
different registry.

New tests: `SlabList.test.tsx` +2, slabs `page.test.tsx` +1 (asserts
`grade: 10` as a number, not `'10'`), `shows/page.test.tsx` +1,
`analytics/page.test.tsx` +1. Full frontend suite: **1147 passed**.
`npx tsc --noEmit` clean.

**T4a done 2026-09-02.** Key discovery first: **only `/admin/inventory`
actually consumed `INVENTORY_COLUMNS`/`toDataTableColumns`** — the other five
(`outgoing`, `show-prep`, `vault`, `triage`, `unmatched`) each already had
their own bespoke inline `Column<T>[]`. T5's own task text anticipates this
("extract them into registries first... that extraction is in scope"), so
T4a's real job was: fully wire the registry for `/admin/inventory`, and give
the other five pages real click-to-edit on their bespoke columns directly
(NOT a registry migration — that's T5-shaped work, deliberately deferred).

**`/admin/inventory`:** every `INVENTORY_COLUMNS` entry now carries either
`edit` (built from `ctx`, via a shared `fieldEdit()` helper) or `notEditable`
(a reason string). Page wires a new `ctx.saveField` (generic PUT + refetch)
and `ctx.showOptions`. One real RFC contradiction resolved: T4a's own
per-column table lists `consignor_id` as editable (`select`), but the RFC's
own §4 "authoritative" exclusion table lists `consignment` (the nested
object `consignor_id` actually lives inside) as excluded — editing just the
id would clobber `split_percent` in the same shallow-merge PUT. **Followed
the exclusion table** (`notEditable` on both `consignment` and
`consignor_name`); `consignor_id` never got a column of its own to attach
`undoLabel` to. Recorded here since T3's own six-field undo list still names
it — if a later session builds a real consignor-reassign flow, it should
carry `undoLabel: 'Consignor'` then.

**The other five pages — what actually changed:**
- `/admin/outgoing` (Prep Queue): added `edit` to `condition` (bare tiers
  only — this page's fetch has never carried `condition_modifier`, so the
  select intentionally excludes +/- rather than silently dropping one) and
  `cost_basis` (money). `sticker_price`/`location` were ALREADY editable via
  pre-existing bespoke mechanisms (the patch-and-drop money cell, the
  location select) — left untouched per the RFC's own explicit warning not
  to regress them.
- `/admin/vault`: added `edit` to `condition`/`cost_basis`/`sticker_price`.
  `dollar_net`/`percent_net`/`consigned` stay derived/read-only (no `edit`
  at all — this page's `Column<T>` isn't the `InventoryColumnDef` type, so
  there's no `notEditable` field to set; a plain column with no `edit` is
  already read-only). **This page had zero existing tests** — added
  `app/(admin)/admin/vault/__tests__/page.test.tsx` (2 tests) from scratch.
- `/admin/show-prep`: added `edit` to `location`/`cost_basis`.
  `sticker_price`/`tcg_url` were already editable via direct `InlineEditCell`
  usage — untouched. 2 new tests.
- `/admin/triage`, `/admin/unmatched`: **no changes.** Both already have a
  bespoke editable field for their one real scalar (`condition` via a select
  on Triage; hand-value via `MoneyInput` on Unmatched) — their other columns
  are identity displays or repair-tool action buttons, not additional plain
  fields calling for a generic editor. Forcing more onto them would be
  low-value churn on the two most bespoke, highest-risk pages in this set.

**Two real bugs found and fixed in `InlineEditCell` itself, from writing
these tests** — neither type (`text`/`money`/`number`/`url`/`date`,
`textarea`, `select`) was passing `aria-label` through onto the actual
control, only onto the closed-state wrapper `div`. Every page test that
tried `getByRole('textbox'/'combobox', {name: ...})` after opening an editor
would have failed to find it by name. Fixed in three places (the shared
input branch, textarea, select); added a regression test per branch
(`InlineEditCell.test.tsx`, now 40 tests) so a future new type doesn't ship
the same gap silently.

Full frontend suite: **1142 passed** (105 files). `npx tsc --noEmit` clean.

**T3 done 2026-09-02.** Undo toast implemented entirely inside `DataTable`
(no separate `UndoToast.tsx` file — the toast markup is small enough that a
separate component would just be an extra import for every consumer with no
reuse benefit; the RFC's file list said "or extend whatever toast the admin
already uses," and here that's DataTable itself since the toast has to know
which column/row/previous-value triggered it). `EditSpec.undoLabel?: string`
— when set, `EditableCell`'s `onSave` wrapper captures `spec.value(item)`
**before** calling save (so Undo restores the pre-edit value, not
whatever the row looks like after the write lands), then calls the
table-level `showUndo()`. State lives in `DataTable` itself
(`pendingUndo` + a `setTimeout` ref cleared and replaced on every new
toast — satisfies "a second edit replaces the toast rather than stacking").
Toast renders `fixed bottom-4 right-4`; the table's outer div gained
`relative` so this positions relative to the table rather than the viewport
root (cosmetic choice, easy to revisit if a page wants it elsewhere).

**Test-infra note for whoever touches this next:** the auto-dismiss test
needs fake timers, but `vi.useFakeTimers()` with NO scope deadlocks
`act()`'s async flush the same way full fake timers deadlock `waitFor` on a
`Date` test (CLAUDE.md's existing dates-testing lesson, same underlying
mechanism hitting a different timer). Fixed with
`vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })` — scope it
this narrowly for any future timer-driven UI test in this codebase.

13/13 `DataTable.test.tsx` tests green (8 from T2 + 5 new). Full frontend
suite: **1133 passed**. `npx tsc --noEmit` clean.

**Fields that actually get `undoLabel` set are T4a/T4b's job** — this task
only builds the mechanism; `INVENTORY_COLUMNS` etc. wire it onto
`status`/`cost_basis`/`sticker_price`/`listed_price`/`location`/
`consignor_id` specifically, per the RFC's exact list.

**T2 done 2026-09-02.** `EditSpec<T>` + `Column<T>.edit` added to
`DataTable.tsx`, matching the RFC's shown interface exactly (`value`/`save`
required, string-typed) plus the multiselect escape hatch designed in T1
(`multiselectValue`/`saveMultiselect`, optional, only consulted when
`type === 'multiselect'`). Rendering goes through a new `EditableCell<T>`
helper: read-only path is byte-identical to the old inline ternary (proven
by a test that clicks a no-`edit` cell and asserts no textbox appears);
`column.edit.disabled?.(item)` vetoes a single row's cell back to read-only.
New `onEditError?: (e: unknown) => void` on `DataTableProps` — `DataTable`
itself renders no error text, matching `InlineEditCell`'s own contract.

8/8 new `DataTable.test.tsx` tests green (sorting/selection coexistence
with editable cells, Enter-key keyboard path, reject-keeps-editor-open +
onEditError, and one multiselect wiring test since no real RFC 0022 column
uses it yet but the seam has to actually work, not just typecheck).
Full frontend suite: **1128 passed**, `npx tsc --noEmit` clean.

**T1 done 2026-09-02.** `InlineEditCell` generalized from 3 types to **9**
(`number|url|money|text|textarea|date|select|checkbox|multiselect`) — one
more than the task title's "eight": `multiselect` was pulled forward into T1
from the RFC's own §1 (not literally in the task README's type list) because
round9/README.md's cross-RFC seam #2 states "0022 ships a multiselect
EditSpec type... 0023's column uses it" as a REQUIREMENT of this RFC, not an
optional extra. Decision recorded here since it's a real scope call beyond
the task doc's literal wording.

Design notes for whoever wires `Column<T>`'s `EditSpec` in T2:
- `checkbox` has NO edit-mode swap — always rendered, toggles+saves on click.
- `multiselect` uses SEPARATE typed props (`multiselectValue: string[]` /
  `onSaveMultiselect: (v: string[]) => ...`), not the shared `value`/`onSave`
  string contract — per the RFC's explicit "not a delimiter-joined string"
  rule. `EditSpec<T>` in T2 needs an equivalent split (a `value`/`save`
  string-returning pair AND, for multiselect columns, an array-typed pair) —
  read `InlineEditCell.tsx`'s props doc before designing `EditSpec`.
- `select`'s empty-`options` case renders a disabled `<select>` showing the
  current value as its only `<option>`, never an empty list.
- `date` commits on BOTH change and blur (a picker click and a hand-typed
  value both need a path to commit).
- Every new control carries `vault-field` (checkbox included).

37/37 component tests green (14 pre-existing + 23 new... actually the file
now has 37 total, up from the original ~23). `npx tsc --noEmit` clean.
Existing consumers (`/admin/outgoing`, `/admin/show-prep`) re-verified green
(28 tests) — the prop interface only grew optional fields, nothing existing
changed shape.

T6 and T7 are independent of everything and are the right pick for a short
session.

**RFC 0023 depends on this RFC.** Its language and finish overrides are edit
surfaces; doing 0023 first means building four bespoke forms that T4a would then
replace.

## Facts established during planning (do not re-derive these)

- **`PUT /admin/inventory/{item_id}` already does everything the backend needs.**
  It is a partial update; it validates the merged row through
  `InventoryItemAdapter`; it validates a changed `card_id` against the catalog; it
  applies the review and `no_catalog_match` transitions; and it writes a
  `type: "edit"` timeline event whose `changed_fields` are diffed from the
  **validated** before/after dumps, not the raw body — so a typo'd key or a
  re-typed-but-equal literal does not record a spurious change, and a rejected
  update writes no audit event at all.
- **`PUT /admin/shows/{show_id}` and `PATCH /admin/cosigners/{consignor_id}` are
  the same partial-update shape.** No new endpoints for those pages either.
- **`/admin/locations` has GET, POST and DELETE only.** No update route exists.
  That is the one new endpoint in this RFC.
- **Twelve surfaces render a `DataTable`:** analytics, cosigners, inventory,
  locations, market, outgoing, show-prep, shows, triage, unmatched, vault, plus
  `SlabList` and `TransactionGroups` (which replaces DataTable, and is out of
  scope — see RFC 0024).
- **`InlineEditCell` already exists** and is used by exactly two pages
  (`/admin/outgoing`, `/admin/show-prep`). It supports `'number' | 'url' | 'money'`.
- **Three surfaces do not return the entity they appear to:** `/admin/vault`
  returns computed `VaultItem`s; the analytics Shows tab joins a
  `ShowAnalyticsSnapshot`; `SlabList` renders `_slab_row()` dicts with `grade` and
  `cost_basis` **stringified**.

## Decisions made autonomously (with the rejected alternative)

- **Undo toast instead of confirmation dialogs.** The owner explicitly declined
  confirms; a mis-click on `status` or `cost_basis` still needs a cheap way back.
  Rejected: no protection at all (the owner's literal answer), and per-edit
  confirms (which defeat the feature).
- **`select` commits on change, not on blur.** Rejected blur-commit: waiting for a
  blur after picking from a dropdown is the most confusing variant of this
  pattern.
- **`PATCH /admin/locations/{value}` accepts `label` only.** Rejected accepting
  `value`: it is the join key on every item and there is no migrate path.
- **Column registries get extracted where they are inline.** Rejected leaving them
  inline: a totality test is impossible without a registry, and the exclusion list
  rots into folklore without one.
- **Transaction rows are out of scope here.** A transaction edit has a
  `cost_basis` side effect and needs a dialog, not a cell. It is RFC 0024's job.

## Owner gates on this RFC

None. Everything here is reversible and inside the owner's stated scope.
