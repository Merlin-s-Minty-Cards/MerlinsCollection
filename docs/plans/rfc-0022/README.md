# RFC 0022 — Task Index

**RFC:** [`docs/rfcs/0022-universal-inline-editing.md`](../../rfcs/0022-universal-inline-editing.md)
**Round guide:** [`docs/plans/round9/README.md`](../round9/README.md) — read it first.
**Progress:** [`progress.md`](progress.md) · **Follow-ups:** [`follow-ups.md`](follow-ups.md)

Overwhelmingly frontend. One new backend endpoint (T6).

**Context warning:** T4 touches seven pages. It is the single largest task in
Round 9 and is explicitly split into two halves so a session can stop between
them at a green boundary.

| Task | Title | Depends on | Suite |
|---|---|---|---|
| T1 | Generalize `InlineEditCell` to eight input types | — | frontend |
| T2 | `EditSpec` on `Column<T>` + `DataTable` wiring | T1 | frontend |
| T3 | Undo toast for the six sensitive fields | T2 | frontend |
| T4a | Adoption: the six inventory-backed pages | T2, T3 | frontend |
| T4b | Adoption: shows, cosigners, slabs, analytics-shows | T2, T3 | frontend |
| T5 | Column registries + totality tests | T4a, T4b | frontend |
| T6 | `PATCH /admin/locations/{value}` + locations adoption | — | backend, frontend |
| T7 | Send to Vault on `CardDetailModal` | — | frontend |
| T8 | Docs + full-suite verification | all | all |

**T6 and T7 are independent of everything else** and are the right tasks to pick
up in a short session.

---

## T1 — Generalize `InlineEditCell`

**Files:** `frontend/components/admin/shared/InlineEditCell.tsx` and its test file.

Add `'text' | 'textarea' | 'date' | 'select' | 'checkbox'` to the existing
`'number' | 'url' | 'money'`.

**Read the existing component's docstring before changing a line.** Three
behaviours are load-bearing and have tests you must not break:

1. **Escape cancels, and the blur that follows Escape-driven focus loss must NOT
   also save.** This is the classic double-fire bug in this pattern.
2. An unchanged edit is skipped entirely — no `onSave` call at all.
3. `'money'` is a **text** input put through `parseMoney`, never `type="number"`.

Commit semantics for the new types:

| Type | Commits on |
|---|---|
| `text` | Enter or blur |
| `textarea` | Ctrl/Cmd+Enter or blur |
| `date` | change or blur — `<input type="date">`, ISO `YYYY-MM-DD` in and out |
| `select` | **change**, immediately. Not blur, not Enter. |
| `checkbox` | **toggle**, immediately. No edit-mode swap at all. |

**Dates:** the value is a date-only ISO string end to end. Never pass it to
`new Date()`. Use `lib/dates.ts`. Any test rendering a date must pin a
negative-offset TZ via `frontend/lib/__tests__/_timezone.ts` and use
`vi.useFakeTimers({ toFake: ['Date'] })` — the default full fake timers deadlock
`waitFor`.

**Every control gets `vault-field`.** An unstyled `<select>` renders light-green
on white in the admin theme.

`select` takes `options: {value,label}[]`. When `options` is empty, render a
**disabled** control showing the current value — never an empty dropdown.

**RED first.** Repeat the Escape/blur assertion for **each** new type; do not
assume the shared code path covers them.

---

## T2 — `EditSpec` on `Column<T>` + `DataTable` wiring

**Files:** `frontend/components/admin/shared/DataTable.tsx` and its test file.

Add the `EditSpec<T>` interface and the optional `edit?: EditSpec<T>` on
`Column<T>` exactly as the RFC's §2 specifies, plus an optional
`onEditError?: (e: unknown) => void` on `DataTableProps`.

`DataTable` renders `<InlineEditCell>` when `column.edit` is present, passing
`render(item)` through as `displayValue` so **the read-only presentation is
byte-identical to today**. The affordance is hover background + a pencil on
hover/focus, and the cell is keyboard-focusable with Enter opening the editor
(hover must never be the only route to a control).

`edit.disabled?.(item)` vetoes a single row's cell — it renders read-only.

**RED first.** Tests: a column with no `edit` is unchanged; a column with `edit`
opens an editor on click and on Enter; `disabled` suppresses it; a rejecting
`save` keeps the editor open and calls `onEditError`; sorting and selection still
work with editable cells present.

---

## T3 — Undo toast

**Files:** a new `frontend/components/admin/shared/UndoToast.tsx` (or extend
whatever toast the admin already uses — check `/admin/outgoing`, which has one),
plus `DataTable` plumbing.

After a successful commit on one of **`status`, `cost_basis`, `sticker_price`,
`listed_price`, `location`, `consignor_id`**, show a 5-second toast naming the
change with an Undo action that re-issues the save with the previous value.

Everything else commits silently. Do not toast a note edit.

**RED first.** Tests: the toast appears for a listed field and not for an
unlisted one; Undo calls `save` with the *previous* value; the toast auto-dismisses;
a second edit replaces the toast rather than stacking indefinitely.

---

## T4a — Adoption: the six inventory-backed pages

**Pages:** `/admin/inventory`, `/admin/outgoing`, `/admin/show-prep`,
`/admin/vault`, `/admin/triage`, `/admin/unmatched`.

All six write through `PUT /admin/inventory/{item_id}`, which is already a partial
update that validates, diffs the **validated** dumps, and writes a `type: "edit"`
timeline event. **No backend change is needed for any of them.**

Add `edit` specs to `INVENTORY_COLUMNS` (`frontend/lib/admin-inventory-columns.tsx`)
so all six inherit them from the one registry rather than each wiring its own.

Per-column input types, by field kind:

| Field kind | `edit.type` | Options source |
|---|---|---|
| money (`cost_basis`, `sticker_price`, `listed_price`, `market_value_at_purchase`) | `money` | — |
| `condition` | `select` | `lib/constants.ts` display strings — remember storage is **two** fields; `_split_combined_condition` on the backend already handles `"LP+"` |
| `location` | `select` | `useLocations()` |
| `status` | `select` | `ItemStatus` values |
| `consignor_id` | `select` | `useCosigners()` |
| `acquired_show_id` | `select` | `useShows()` |
| `acquired_at` | `date` | — |
| `needs_review`, `factory_sealed`, `no_catalog_match` | `checkbox` | — |
| `notes`, `value_note`, `sticker_notes` | `textarea` | — |
| `tcg_url` | `url` | — |
| everything else scalar | `text` | — |

**`/admin/vault` is different and must be handled explicitly:** its endpoint
returns computed `VaultItem` rows (`dollar_net`, `percent_net`, `consigned`), not
`InventoryItem`s. Those three are **derived and read-only**; the editable columns
on that page are the ones that map back to real item fields.

**Exclusions, each with a `notEditable` reason string** — the RFC's §4 table is
the authoritative list. `card_id` and `consignment` are the owner-stated two;
identity/audit/derived fields are the rest.

**Do not regress Prep Queue's existing behaviour.** Pricing an item inline there
PATCHes the row and **drops it without a refetch**, with a *conditional* toast
(setting a price says "Priced → removed"; clearing one says "Sticker price
cleared" and the row stays), and prunes the id from `selectedIds`. That is
deliberate and tested — the registry-driven cell must preserve it, which likely
means Prep Queue keeps a page-level `edit.save` override for `sticker_price`.

Also do not regress: **first header click sorts ASCENDING on Prep Queue and
DESCENDING on `/admin/inventory`.** These genuinely disagree and both are pinned.

**Suite:** `npm test --workspace=frontend`. Stop here at green if context is
past ~45%.

---

## T4b — Adoption: shows, cosigners, slabs, analytics-shows

| Page | Endpoint | Editable |
|---|---|---|
| `/admin/shows` | `PUT /admin/shows/{id}` | name, date, location, notes, archived |
| `/admin/cosigners` | `PATCH /admin/cosigners/{id}` | name, contact, default split, archived |
| `/admin/slabs` (`SlabList`) | `PUT /admin/inventory/{id}` | slab fields |
| `/admin/analytics` Shows tab | `PUT /admin/shows/{id}` | name, date only |

**`SlabList` gotcha:** `_slab_row()` returns a **dict**, and `grade` and
`cost_basis` are `str(Decimal)` in the response so a Decimal survives JSON without
becoming a float. The save must parse back to a **number** before sending. Never
write a bare float to DynamoDB, and when writing the test for this path send a
JSON number — the suite's habit of sending money as strings is why a real
production 500 went unnoticed for months.

**`/admin/shows` gotcha:** the SK embeds the show **date**, and `put_show` sweeps
superseded rows after writing to stop a reschedule forking the show into two rows.
That already works; just be aware a date edit is not a plain update underneath.

**Analytics Shows tab:** Sold/Bought/Net/Items come from a `ShowAnalytics` join,
not from `shows_sort.py`'s fields. They are derived and stay display-only.

**Cosigners:** the name carries a 409 duplicate guard (case- and
whitespace-insensitive, and an archived consignor still collides). A rejected
inline edit must keep the editor open with the 409 message — this is the best test
of T2's reject path.

---

## T5 — Column registries + totality tests

Some pages define their columns inline. **Extract them into registries first** —
that extraction is in scope, because it is what makes a totality test possible.

Then, for `INVENTORY_COLUMNS` and each new registry:

> Every column entry has either an `edit` spec **or** a `notEditable: string`
> reason of at least 10 characters.

**The length assertion is the point.** CLAUDE.md records a parity test that
diffed key sets only and stayed green while every value was an empty `{}` stub —
"a test exists and passes" is not the same claim as "the test checks the thing
that matters."

---

## T6 — `PATCH /admin/locations/{value}` + locations adoption

**Files:** `backend/src/merlins_collection/routers/admin/locations.py`,
`backend/tests/routers/admin/test_locations.py`,
`frontend/app/(admin)/admin/locations/page.tsx`, `frontend/lib/use-locations.ts`.

```
PATCH /admin/locations/{value}   body: { "label": string }
```

- `label` only. Any other key → **422**, never a silent no-op.
- Empty/whitespace label → 422.
- Unknown `value` → 404.
- **`value` is permanently not editable.** It is the join key stored on every
  inventory item and there is no rename-and-migrate path. The frontend cell is
  read-only with a one-line reason beside it.

`useLocations()` must gate its fetch on `api.isAuthenticated` **in the effect's
dependency array** if it does not already — CLAUDE.md's fetch-once-hook lesson
names this hook specifically.

---

## T7 — Send to Vault on `CardDetailModal`

**File:** `frontend/components/admin/shared/CardDetailModal.tsx` + test.

A button beside Send to Triage. Read `writeTriage` and the Triage button's JSX
first — this is a deliberate copy of that shape, not a new pattern.

- "Send to Vault" → `PUT /admin/inventory/{id}` with `{ status: 'on_hold' }`.
- Already `on_hold` → reads **"In Vault"**, and clicking offers to return the item
  to `available`.
- The **server's `status` is the single answer**. Reflect the refetched item;
  never hold a local optimistic flag that can disagree with it.
- Same undo affordance as the Triage row action.

Reach: the five pages that mount the modal (inventory, outgoing, show-prep, vault,
triage). Nothing else changes.

`on_hold` already fails `is_customer_visible`'s `AVAILABLE` check, so the customer
surface follows with no second predicate. **Do not add one.**

---

## T8 — Docs + full-suite verification

- `CLAUDE.md`: a section on the inline-editing registry and its totality rule; the
  new locations endpoint; Send to Vault's reach (mirroring how Send to Triage's
  reach is already documented).
- Every suite in the round guide.
