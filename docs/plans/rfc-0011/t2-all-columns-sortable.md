# T2 — Every inventory column is sortable

**RFC:** 0011 §A · **Layer:** frontend · **Depends on:** T1 · **Blocks:** —

## Everything needed already exists

| capability | where |
|---|---|
| controlled sorting | `DataTable`'s `sortKey` / `sortDir` / `onSort` — `components/admin/shared/DataTable.tsx:18-20, 61-74` |
| the page already holds sort state and passes it | `admin/inventory/page.tsx:53-54, 163-170, 527-537` |
| the header renders a sort indicator when `sortable` | `DataTable.tsx:69-71` |
| `sortable` is already carried through the registry | `toDataTableColumns`, `lib/admin-inventory-columns.tsx:364-377` |

**There is no page wiring in this task and no backend change.** T1 made the server accept
every field; this task marks the columns. It is small on purpose — it is a separate task
because it is separately rejectable: if T1's field names and the registry's `key`s
disagree, this is where it shows.

## Files

- **Modify:** `frontend/lib/admin-inventory-columns.tsx` — add `sortable: true` to every
  entry except `_image` and `_actions`
- **Test:** `frontend/lib/__tests__/admin-inventory-columns.test.ts`

## Design

`Column.key` **is** the backend's sort field, because the page sends
`params.sort = \`${sortKey}_${sortDir}\`` (`inventory/page.tsx:147`) and the backend
splits on the **last** underscore. So marking a column sortable is a claim that its `key`
is in T1's `SORT_FIELDS`. Both of these are already true for the 33 keys — verify, don't
assume, and if one disagrees fix the **registry**, never the key (keys are persisted in
`localStorage`; CLAUDE.md, rule 1 of that file's header).

Two columns stay unsortable, and the test pins both:

- **`_image`** — it renders art resolved from `card_id` through a hook. There is no
  server-side value to order by, and "sort by picture" is not a question.
- **`_actions`** — a pinned button cell, not data.

**First-click direction stays `desc`.** `handleSort` (`inventory/page.tsx:163-170`) is
untouched. CLAUDE.md records the inventory-vs-Prep-Queue disagreement as deliberate, and
this RFC does not reopen it.

## RED — write these first, show the failing output, then STOP

Append to `frontend/lib/__tests__/admin-inventory-columns.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { INVENTORY_COLUMNS } from '@/lib/admin-inventory-columns'

describe('every column is sortable except the two that cannot be', () => {
  const UNSORTABLE = new Set(['_image', '_actions'])

  it('marks every data column sortable', () => {
    const unmarked = INVENTORY_COLUMNS
      .filter((c) => !UNSORTABLE.has(c.key) && !c.sortable)
      .map((c) => c.key)

    expect(unmarked).toEqual([])
  })

  it('leaves the image and action cells unsortable', () => {
    // Art is resolved client-side from card_id and the action cell is buttons —
    // neither has a server-side value to order by.
    for (const key of UNSORTABLE) {
      expect(INVENTORY_COLUMNS.find((c) => c.key === key)?.sortable).toBeFalsy()
    }
  })

  it('uses keys the backend can parse as {field}_{direction}', () => {
    // The page sends `${key}_${dir}` and the backend rsplits on the LAST underscore,
    // so a key ending in _asc or _desc would parse as a direction and lose its field.
    for (const col of INVENTORY_COLUMNS) {
      expect(col.key.endsWith('_asc')).toBe(false)
      expect(col.key.endsWith('_desc')).toBe(false)
    }
  })
})
```

Run, show the failing list (it should name ~25 keys), and **WAIT**.

```bash
cd frontend && npx vitest run lib/__tests__/admin-inventory-columns.test.ts
```

## GREEN

Add `sortable: true` to every `INVENTORY_COLUMNS` entry except `_image` and `_actions`.
The entries currently missing it are, in registry order:

`kind`, `sticker_price`, `consignment`, `needs_review`, `review_reason`, `reviewed_at`,
`card_id`, `language`, `finish`, `factory_sealed`, `company`, `grade`, `cert_number`,
`product_type`, `description`, `market_value_at_purchase`, `listed_price`,
`sticker_notes`, `acquired_at`, `acquired_show_id`, `notes`, `value_note`,
`display_name_override`, `tcg_url`, `lineage_id`, `predecessor_item_id`, `item_id`.

## Verify by hand before you finish

Load `/admin/inventory`, turn on a column that was not sortable before (Notes is a good
one — it has blanks), and click its header twice. You should see: a sort indicator, the
order reversing, and **blank rows staying at the bottom in both directions** — that last
one is T1's missing-last rule, and this is the only place it is visible.

## Done means

1. `npx vitest run lib/__tests__/admin-inventory-columns.test.ts` passes, output shown;
2. the inventory page test file still passes:
   `npx vitest run "app/(admin)/admin/inventory/__tests__/page.test.tsx"`;
3. `npm run lint --workspace=frontend` is clean;
4. the by-hand check above was actually done;
5. `progress.md` updated.

Do not run the full suite. Do not merge. Do not push.
