# RFC 0022: Universal Admin Inline Editing & Send to Vault

**Status:** Draft — written 2026-09-02, adversarially reviewed the same day
(see "Adversarial review findings"). No code written yet.
**Author:** Claude (planning session), owner-directed
**Round:** 9 — see [`docs/plans/round9/README.md`](../plans/round9/README.md)
**Owner tasks covered:** "Admin should have the ability to edit values on all
tables just by clicking on the value on the table (for quick edits of values).
This should be supported for all values and they should have appropriate input
fields, like text boxes, dropdowns, etc."; "Need a button on card details popup
to send it to vault (similar to triage)."

## Summary

Make **every value in every admin table** click-to-edit, with the input type the
value actually deserves — a money field, a date picker, a location dropdown, a
condition dropdown, a checkbox — and add a **Send to Vault** action to
`CardDetailModal` beside the existing Send to Triage.

Almost all of the backend already exists. `PUT /admin/inventory/{item_id}` is a
partial update that validates, diffs the *validated* before/after (not the raw
body), and writes an audit timeline event; `PUT /admin/shows/{id}` and
`PATCH /admin/cosigners/{id}` are the same shape. The work is overwhelmingly on
the frontend: a registry-driven editing capability on `Column<T>`, a generalized
`InlineEditCell`, and adoption across the 12 DataTable surfaces.

## Motivation

Editing an inventory value today means opening `CardDetailModal`, finding the
field, editing it, closing the modal, and losing your place in the list. At a
show, correcting fifteen conditions is fifteen round trips through a modal.

Two pages already prove the pattern works — Prep Queue and Show Prep both use
`InlineEditCell` for sticker price and TCG link — but that component only supports
`'number' | 'url' | 'money'`, and each page wires it by hand. There is nothing
general, so every new editable cell is bespoke work and most cells never get one.

The owner's answer to "should anything be off limits" was **"everything except
`card_id` and consignment terms"**. Those two keep their existing confirmed flows:
re-pointing a card is a Triage action with a before/after diff and trade-lineage
warnings, and consignment terms are a nested object edited through the cosigners
link form. Everything else — including `cost_basis` and `status` — is directly
editable.

**Send to Vault** exists because `/admin/vault` lists items whose status is
`on_hold`, and the only way to put an item there today is a manual status edit
buried in the modal's Identity section. The owner wants it to be one button,
"similar to triage" — which already has exactly that treatment.

## Owner decisions (recorded 2026-09-02)

1. **Editable scope:** everything except `card_id` and consignment terms.
   Rejected: "everything with a confirm on the dangerous ones" and "everything, no
   guard rails".
2. **Send to Vault:** sets `status` to `on_hold`, and nothing else. Rejected:
   also moving the location (needs a `vault` location that does not exist), and
   location-only (which would leave the card customer-visible and for sale).

## Detailed Design

### 1. `InlineEditCell` grows five input types

**File:** `frontend/components/admin/shared/InlineEditCell.tsx`

Today: `type: 'number' | 'url' | 'money'`. After: add `'text'`, `'textarea'`,
`'date'`, `'select'`, `'checkbox'`.

**The existing behaviours are load-bearing and must survive unchanged:**

- Escape cancels and restores the original value, **and the blur that follows an
  Escape-driven focus loss must not also trigger a save.** That is the classic
  double-fire bug in this pattern and the component already solves it.
- An unchanged edit is skipped entirely — no call, no round trip.
- `onSave` may return a promise; while pending the input stays open and disabled;
  on reject it stays open so the value can be corrected.
- **`'money'` is a TEXT input, never `type="number"`**, and commits through
  `parseMoney`. A native number input cannot receive the comma the owner types.

**New type semantics:**

| Type | Commits on | Notes |
|---|---|---|
| `text` / `textarea` | Enter (textarea: Ctrl/Cmd+Enter) or blur | Same commit rules as the existing types. |
| `date` | change or blur | `<input type="date">`. Value in and out is an ISO `YYYY-MM-DD` string. **Never construct a `Date` from it** — `lib/dates.ts`'s `parseISODateLocal` / `toLocalISODate` are the only conversions allowed. |
| `select` | **change** (immediately) | No Enter, no blur commit. Waiting for a blur after a dropdown pick is the single most confusing variant of this pattern. Escape before choosing cancels. |
| `checkbox` | **toggle** (immediately) | Renders as a checkbox in place; no edit-mode swap at all. |
| `multiselect` | each toggle, immediately | A chip list; the stored value is an **array**, so `value`/`save` marshal it (`join('\u0000')` is not acceptable — pass the array through a typed variant rather than smuggling it in a string). With `allowCustom`, a text input appends a value not in `options`. |

> **`multiselect` exists specifically for RFC 0023's `finish_attributes`.** It is
> the one field in Round 9 whose stored value is a list, and the totality test in
> §5 would otherwise force that column to ship `notEditable` — contradicting the
> whole point of the finish rework. Build it here, in the shared component, rather
> than letting RFC 0023 bolt a second editing mechanism onto one column.

`select` takes an `options: {value, label}[]` prop. Every rendered control carries
`vault-field` — an unstyled `<select>` inherits the admin theme's light-green text
over the browser's white default and renders unreadable.

**A `select` whose options are still loading renders as a disabled control with
the current value, not as an empty dropdown.** The options for location,
consignor, show and set all come from fetch-once hooks, and CLAUDE.md records
those hooks shipping permanently empty when they lose the session race. Any new
option hook this RFC touches must gate on `api.isAuthenticated` and put it in the
effect's dependency array.

### 2. `Column<T>` grows an `edit` capability

**File:** `frontend/components/admin/shared/DataTable.tsx`

```ts
export interface EditSpec<T> {
  type: 'text' | 'textarea' | 'money' | 'number' | 'date'
      | 'select' | 'multiselect' | 'checkbox' | 'url'
  /** Options for `select` / `multiselect`. */
  options?: SelectOption[]
  /** `multiselect` only: accept values outside `options` as free text. */
  allowCustom?: boolean
  /** The current stored value, as a string ('' for absent). */
  value: (item: T) => string
  /** Commit. Rejects to keep the editor open; the table surfaces the message. */
  save: (item: T, next: string) => Promise<void>
  /** Optional per-row veto — e.g. a sold item's cost basis. */
  disabled?: (item: T) => boolean
}

export interface Column<T> {
  key: string
  label: string
  sortable?: boolean
  className?: string
  render?: (item: T) => React.ReactNode
  /** Present ⇒ this cell is click-to-edit. */
  edit?: EditSpec<T>
}
```

`DataTable` renders `<InlineEditCell>` in place of `render(item)` when
`column.edit` is set, passing `render(item)` as the `displayValue` so the
read-only presentation is unchanged — the formatted money, the badge, the
truncated link all stay exactly as they are until clicked.

**The read-only presentation must not change.** A cell that suddenly grows a
border or an always-visible pencil turns twelve dense tables into noise. The
affordance is the same one Prep Queue already uses: a hover background change and
a pencil that appears on hover/focus, and nothing else. Hover may change a
background colour; per CLAUDE.md it may never be the only way to reach a control,
so the cell is also keyboard-focusable and Enter opens the editor.

**Errors surface once, at the table.** `DataTable` gains an optional
`onEditError?: (e: unknown) => void`; each page routes it to whatever error banner
it already has. The cell itself renders no error text (its existing contract).

### 3. Undo, not confirmation

The owner declined per-edit confirmations, and they are right to: a confirm on
every cost-basis edit defeats the entire point of click-to-edit at a show table.

But a mis-click on a `status` dropdown can move a card out of customer-visible
stock, and a fat-fingered `cost_basis` silently changes what every profit figure
downstream reports. So instead of a modal in the way, the table shows a **5-second
undo toast** after a commit on a designated set of fields:

```
Status → on_hold · Undo
```

Undo re-issues the save with the previous value. It is one extra API call on a
path nobody takes, and it costs zero keystrokes when not used.

**Undo is last-write-wins and is not a transaction.** If a second admin edited the
same field inside the 5-second window, undo overwrites them. Accepted: this is a
single-operator admin tool, the window is five seconds, and the durable record is
the `type: "edit"` timeline event, which shows both writes. Building optimistic
concurrency for a five-second undo would cost more than the failure it prevents.

**Fields that get an undo toast:** `status`, `cost_basis`, `sticker_price`,
`listed_price`, `location`, `consignor_id`. Everything else commits silently —
a typo'd note is not worth a toast.

> **`sticker_price` and `status` become customer-visible switches once RFC 0025
> lands, and the UI must say so.** After RFC 0025 a card with no `sticker_price`
> is **hidden from the storefront entirely**, and `on_hold` already fails
> `is_customer_visible`'s `AVAILABLE` check. So *clearing* a sticker inline, or
> flipping a status, silently pulls a card off the customer site — a consequence
> the operator has no way to see from the admin table. Whichever of the two RFCs
> lands second owns this: the undo toast for a **cleared** sticker, and for a
> status leaving `available`, reads
> **"Removed from the customer site · Undo"**, not the generic field name. This is
> the one place in Round 9 where two RFCs combine into a behaviour neither
> describes on its own.

This is not a substitute for the audit trail, which already exists:
`PUT /admin/inventory/{item_id}` writes a `type: "edit"` timeline event with the
changed fields, computed by diffing the **validated** dumps rather than the raw
request body.

### 4. Per-surface adoption

Twelve surfaces render a `DataTable`. Each gets `edit` specs on the columns whose
entity has a partial-update endpoint.

| Surface | Entity | Endpoint | Editable |
|---|---|---|---|
| `/admin/inventory` | inventory item | `PUT /admin/inventory/{id}` | every column in `INVENTORY_COLUMNS` except the exclusions below |
| `/admin/outgoing` (Prep Queue) | inventory item | same | same; keeps its existing sticker/TCG cells, now via the registry |
| `/admin/show-prep` | inventory item | same | same |
| `/admin/vault` | inventory item | same | **note:** `/vault`'s response is a computed `VaultItem`, not an `InventoryItem` — `dollar_net` / `percent_net` / `consigned` are derived and are **read-only by construction** |
| `/admin/triage` | inventory item | same | same |
| `/admin/unmatched` | inventory item | same | same |
| `/admin/slabs` (`SlabList`) | graded inventory item | same | `_slab_row()` is a dict with two **stringified** fields (`grade`, `cost_basis`); the save must send a number, not the string it displays |
| `/admin/shows` | show | `PUT /admin/shows/{id}` | name, date, location, notes, archived |
| `/admin/cosigners` | consignor | `PATCH /admin/cosigners/{id}` | name, contact, default split, archived |
| `/admin/locations` | location | **none exists** | see below |
| `/admin/market` (watchlist) | watchlist entry | `POST/DELETE /admin/watchlist` only | read-only; the row is a catalog card, not an owned entity |
| `/admin/analytics` (Shows tab) | show | `PUT /admin/shows/{id}` | name, date only — the Sold/Bought/Net columns come from a snapshot join and are **derived** |
| `/admin/history`, Daily tab groups | transaction | **RFC 0024** | out of scope here — a transaction edit has a `cost_basis` side effect and needs a dialog, not a cell |

**Locations needs one new endpoint.** `/admin/locations` today has only GET, POST
and DELETE (behind a 409 in-use guard). A location is `{value, label}` where
`value` is the join key stored on every item. So:

- `PATCH /admin/locations/{value}` accepting **`label` only**. Renaming a label is
  safe and is what an admin actually wants.
- **`value` is not editable, at any price.** Changing it would orphan every item
  pointing at the old string, and there is no rename-and-migrate path. The cell is
  read-only with a one-line reason beside it, per CLAUDE.md's rule that a
  disabled control states why.

**Field exclusions, and every one has a stated reason.** These are read-only
cells, not absent ones:

| Field | Why | Where to edit it instead |
|---|---|---|
| `card_id` | Re-pointing a card is a confirmed action with a before/after diff and trade-lineage warnings. | Triage re-point |
| `consignment` (nested) | Not a scalar; split, terms and consignor move together. | Cosigners link form / `CardDetailModal` panel |
| `item_id`, `lineage_id`, `predecessor_item_id` | Identity and history. Already `readOnly` in `CardDetailModal`. | nowhere |
| `reviewed_at`, `voided_*`, `edited_*` | Server-stamped accountability fields. A client's claim about who did something is not evidence. | nowhere |
| `current_market_value` | Denormalized nightly by `refresh_inventory_market_values`; a hand edit is overwritten on the next run. | catalog / graded price pin |
| Derived columns (`dollar_net`, `percent_net`, `consigned`, `triage_reasons`, `bulk_clearable`, show analytics totals) | Computed server-side from other fields. | the inputs |
| `location.value` | Join key for every item. | delete + recreate |

### 5. Totality — a new column cannot ship silently uneditable

The repo's own precedent is that a registry gets a totality test:
`INVENTORY_COLUMNS` and `SORT_FIELDS` both have one, so a new model field fails a
test rather than arriving without a sort or a filter.

Same shape here, in `frontend/lib/__tests__/admin-inventory-columns.test.ts`:

> **Every `INVENTORY_COLUMNS` entry has either an `edit` spec or an explicit
> `notEditable: '<reason>'` string.**

The reason string is not decoration — it is what renders in the cell's tooltip and
it is what stops the exclusion list above from rotting into folklore. A totality
test that only diffs key *sets* would pass while every reason said `""`; CLAUDE.md
records that exact failure (`admin-tool-contract.json`'s properties were all
`{}` and the parity test could not see it). So the test asserts the reason is
non-empty and at least 10 characters.

The same test shape goes on `SHOW_COLUMNS`, `CONSIGNOR_COLUMNS` and the slab list
columns where those registries exist; where a page defines columns inline, the
task extracts them into a registry first. That extraction is in scope — it is the
thing that makes the totality test possible at all.

### 6. Send to Vault

**File:** `frontend/components/admin/shared/CardDetailModal.tsx`

A button beside the existing Send to Triage, following its exact shape:

- Reads **"Send to Vault"** when the item's status is anything else; **"In Vault"**
  when it is already `on_hold`, and clicking then offers to send it back to
  `available`.
- Writes `{ status: 'on_hold' }` through the existing
  `PUT /admin/inventory/{item_id}`. No new endpoint.
- Shows the same undo affordance Triage's row action uses.
- **The server's `status` is the single answer** — the button reflects the
  refetched item, never a local optimistic flag that can disagree with it. This
  mirrors the comment already in `writeTriage`.

Reach: the five pages that mount the modal — inventory, outgoing, show-prep, vault
and triage. `/admin/trade`, Market, History, Cosigners and `/admin/card/[id]` do
not mount it and are unchanged, exactly as the Triage button's reach is documented
today.

**Nothing about vault visibility changes.** `on_hold` already excludes an item
from `is_customer_visible` (which requires `AVAILABLE`), so the customer surface
follows automatically with no second predicate.

## API Contracts

One new endpoint:

```
PATCH /admin/locations/{value}
  body: { "label": string }
  200 -> { "value": string, "label": string }
  404 -> unknown location
  422 -> empty label, or any key other than `label`
```

`value` is deliberately absent from the accepted body. Sending it is a 422, not a
silent no-op — same rule the sort and filter registries already follow.

Everything else reuses `PUT /admin/inventory/{item_id}`,
`PUT /admin/shows/{show_id}` and `PATCH /admin/cosigners/{consignor_id}` as they
stand.

## Alternatives Considered

**A single generic `PATCH /admin/{entity}/{id}`.** Fewer endpoints, and a
catastrophic idea: it would route inventory, shows and consignors through one
validator and destroy the per-entity rules each of those endpoints carries (the
`card_id` catalog check, the review transition, the show SK sweep, the consignor
duplicate guard).

**A row-level "edit mode" toggle that turns a whole row into inputs.** Fewer
click targets to build, but it re-renders a dozen cells to change one, loses the
formatted presentation while editing, and makes a single-field correction a
multi-step action. Cell-level is what the owner asked for.

**Confirmation dialogs on dangerous fields.** Explicitly declined by the owner.
The undo toast delivers the same protection with none of the friction, and the
timeline audit event delivers the durable record.

**Making `CardDetailModal` the only edit surface and just making it faster.** It
is the status quo and it is what the owner is asking to get away from.

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| **A mis-click silently changes money or status.** | 5-second undo toast on the six sensitive fields; the existing `type: "edit"` timeline event as the durable record. |
| **Twelve tables become visually noisy.** | The read-only presentation is unchanged; the affordance is hover background + a pencil on hover/focus only, identical to the two pages that already do this. |
| **A `select` ships with an empty option list on a fresh page load.** | Every option hook gates on `api.isAuthenticated` **in the effect's dependency array**. CLAUDE.md records four hooks that shipped permanently empty from exactly this; the tests there mock a synchronously-resolving session and cannot see it, so the pattern must be copied deliberately rather than verified after. |
| **A stringified backend field round-trips as a string and breaks a Decimal.** | `SlabList`'s `grade` and `cost_basis` are `str(Decimal)` in the response. The save path parses back to a number. Never write a bare `float` to DynamoDB — and when testing this path, send a JSON **number**, which is what the frontend actually sends. |
| **`InlineEditCell`'s Escape/blur double-fire regresses under the new types.** | Its existing test covers it; add the same assertion for every new type rather than assuming the shared code path covers them. |
| **The exclusion list rots.** | The totality test requires a non-empty reason string ≥10 chars for every non-editable column. |

## Adversarial review findings (2026-09-02)

1. **Bloat — the first draft proposed a generic `PATCH /admin/{entity}/{id}`.**
   Cut. It would have collapsed four validators with genuinely different rules
   into one, on the admin write path.
2. **Logic — `/admin/vault`, `/admin/analytics` and `SlabList` do not return the
   entity they appear to.** Vault returns computed `VaultItem`s, the Shows tab
   joins an analytics snapshot, and slabs return `_slab_row()` dicts with two
   stringified money fields. Making "every value editable" literally true on those
   surfaces would mean saving a derived number back to a field that does not
   exist. Each is now explicitly enumerated as derived/read-only.
3. **Correctness — `/admin/locations` has no update endpoint at all,** so
   "editable" there was undefined. Added `PATCH .../{value}` for `label` only,
   with `value` permanently read-only because it is the join key on every item.
4. **Chaos — an option hook losing the session race renders an empty dropdown that
   never retries.** This is a documented, already-shipped failure in this repo and
   it lands squarely on the new `select` type. Mitigated by the `isAuthenticated`
   dependency rule and by rendering a disabled control rather than an empty one
   while options are unresolved.
5. **Security — nothing here weakens a boundary.** The new endpoint accepts one
   field; every other write reuses an endpoint that already validates. Worth
   noting explicitly: `status` becoming a one-click dropdown makes it *easier* to
   pull an item out of customer view, which is the safe direction.
6. **Logic — the totality test as first drafted diffed key sets only.** That is
   the exact shape of failure CLAUDE.md records for `admin-tool-contract.json`:
   green forever while every value was an empty stub. Strengthened to assert a
   substantive reason string.

## Open Questions

None blocking.
