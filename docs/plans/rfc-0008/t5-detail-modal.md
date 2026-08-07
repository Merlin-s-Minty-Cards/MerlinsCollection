# T5 — Item detail: full field coverage, real notes box

**RFC:** 0008 §F6 (issues #12, #13) · **Layer:** frontend · **Depends on:** nothing
**File:** `frontend/components/admin/shared/CardDetailModal.tsx`

## The gap

`EDITABLE_FIELDS` (line 22-36) lists **13** fields. `_ItemBase`
(`backend/src/merlins_collection/models/inventory.py:170-202`) plus kind-specific
fields is roughly twice that. And `notes` (line 31) renders through the generic
text branch — a single-line `<input type="text">` (line 266-278). That's the
"tiny box" in the report. Contrast the Buy page, which uses a proper
`<textarea rows={2}>` for the same kind of free text.

## Missing fields

Read `models/inventory.py:170-247` (the discriminated union) as the source of
truth — this list is the RFC's audit, verify it against the model before trusting it:

**On `_ItemBase`:** `market_value_at_purchase`, `listed_price`, `acquired_at`,
`acquired_show_id`, `value_note`, `needs_review`, `consignment` (nested).

**Read-only / derived** — display but no edit control:
`item_id`, `lineage_id`, `predecessor_item_id`.

**Kind-specific**, rendered conditionally on `item.kind`, mirroring the union:
- raw: `factory_sealed`
- graded: `company`, `grade`, `cert_number`
- sealed: `product_type`

## Fix

### 1. Widen the field type

The current shape is `{ key, label, type: 'text' | 'number' | 'select' }`. Extend it:

- Add `'textarea'` — for `notes` and `value_note`. Multi-row, sized to show a full
  note without truncating. This is the headline ask of issue #13; don't undersize it.
- Add `'checkbox'` — for `needs_review`, `factory_sealed`.
- Add `'date'` — for `acquired_at`.
- Add an optional `kinds?: ItemKind[]` so kind-specific fields render only for the
  matching kind. Absent means "all kinds".
- Add an optional `readOnly?: true` for the derived fields.

### 2. Consignment needs its own sub-form

`consignment` is a **nested object** (`consignor_id`, `split_percent`,
`minimum_price`, `paid_out`) and does not fit the flat `{key, label, type}` shape.
Give it a small dedicated sub-form section rather than bending the registry around
it. If that turns out to be more than a modest amount of work, render it read-only
for now and say so — a read-only correct display beats a broken editor.

### 3. Leave `condition` alone

It already works: a single select over `CONDITION_OPTIONS` with
`parseCondition`/`formatCondition` splitting the display string into the two stored
fields (`condition` + `condition_modifier`). That is the correct pattern and the
Round 1 bug is exactly what happens when you bypass it. **Never send a combined
`"LP+"` to the backend as a `condition` enum value.**

### 4. Locations

`location` already uses `useLocations()`. Keep it. Never hardcode a location list.

## Watch for

- **T11 adds a "Send to Triage" button to this same modal**, relying on its
  docstring claim that it *"opens when clicking a card row in any admin page"*.
  While you're in here, sanity-check that claim against the actual call sites — if
  some admin page has its own bespoke detail view instead, T11's cheapest insertion
  point doesn't exist and it needs to know that early.
- **Every added field must actually be accepted by `PATCH`.** Check
  `admin_update_item` (`routers/admin/inventory.py:267-319`) for its allowed-field
  set before adding an editor. An input that silently no-ops is worse than no input.
- Field count roughly doubles — group into sections (Identity / Pricing /
  Acquisition / Consignment / Flags) rather than one long column.

## RED — write these first, confirm they fail, then stop

1. `notes` renders a `<textarea>`, not `<input type="text">`. Fails today.
2. The textarea shows multiple rows (assert the rendered element, not a snapshot).
3. `value_note` also renders as a textarea.
4. A graded item shows `company`, `grade`, `cert_number`. Fails today.
5. A raw item does **not** show `grade`/`cert_number`. (Guards the `kinds` filter.)
6. A raw item shows `factory_sealed` as a checkbox.
7. `item_id` / `lineage_id` display but expose no edit control.
8. `acquired_at` renders a date input.
9. Editing `condition` to `LP+` sends `condition: "LP"` **and**
   `condition_modifier: "+"` as separate fields. Passes today — the single most
   important regression guard in this task.
10. Consignment fields appear for a consigned item.

## Verify (narrow)

```bash
cd frontend && npx vitest run CardDetailModal
npm run lint --workspace=frontend
```

Then open a real item on `/admin/inventory` and edit a note — confirm it saves and
the box is comfortable to type in.

## Done when

- Every `_ItemBase` field plus the active kind's fields is present.
- Notes is a properly sized textarea.
- Test 9 still green.
