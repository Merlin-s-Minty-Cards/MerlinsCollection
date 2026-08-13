# T4 — A dedicated filter for every column

**RFC:** 0011 §B · **Layer:** frontend · **Depends on:** T3 · **Blocks:** —
**Owner report:** *"each column should have a dedicated filter that shows up and
disappears when the column is selected or unselected."*

## The show/hide behavior already ships — do not rebuild it

`isFilterVisible(filter, visible, showAllFilters)`
(`lib/admin-inventory-columns.tsx:492-499`) is **exactly** the behavior the owner
describes, and the page already renders `shownFilters` from it (`page.tsx:362, 468-471`),
already warns when an active filter's column is hidden (`page.tsx:366-368, 474-508`), and
already offers the "Show all filters" escape hatch.

**What is missing is coverage: 12 filters for 33 columns.** This task makes
`INVENTORY_FILTERS` total and replaces thirteen hand-written controls with controls
rendered from a declared `kind`.

## Files

- **Modify:** `frontend/lib/admin-inventory-columns.tsx` — extend `InventoryFilterDef`,
  make `INVENTORY_FILTERS` total, add `buildFilterParams`
- **Create:** `frontend/components/admin/shared/ColumnFilter.tsx` — one control per kind
- **Modify:** `frontend/app/(admin)/admin/inventory/page.tsx` — collapse 13 filter
  `useState`s into one record; delete the local `FilterSelect` / `FilterText` helpers
- **Test:** `frontend/lib/__tests__/admin-inventory-columns.test.ts`,
  `frontend/app/(admin)/admin/inventory/__tests__/page.test.tsx`

## Interfaces

**Consumes** from T3 — these strings must match the Python enums character for character:

```ts
export type FilterKind = 'text' | 'select' | 'range' | 'dateRange' | 'presence'
export type FilterOp = 'contains' | 'eq' | 'gte' | 'lte' | 'isnull' | 'notnull'
```

**Produces:**

```ts
interface InventoryFilterDef {
  id: string
  label: string
  columnKey: string | null
  kind: FilterKind
  /** The backend field name. Defaults to `columnKey` when omitted. */
  field?: string
  /** For `kind: 'select'` — a static list, or the name of a dynamic source. */
  options?: { value: string; label: string }[]
  optionSource?: 'locations' | 'shows' | 'sets'
  /** Legacy named param this filter sends instead of the generic `filter=`. */
  legacyParam?: string
}

type FilterValues = Record<string, string>   // filter id -> value; '' means unset
function buildFilterParams(values: FilterValues): { params: Record<string, string>; filters: string[] }
```

## Design

### The registry becomes total

One entry per column, plus the three existing column-less catalog filters. Kind
assignment, which is the owner's "analyzed for whether they should be max/min, a
dropdown, or a text input" deliverable:

| kind | filters |
|---|---|
| `range` (renders a Min and a Max box) | Price Paid, Market, Sticker, Listed Price, Market at Purchase, Grade |
| `dateRange` (From / To) | Acquired, Reviewed |
| `select` | Status, Kind, Condition, Location, Language, Finish, Ownership, Grading Co., Factory Sealed, Review, Acquired Show |
| `presence` (Any / Has / Missing) | **Card ID**, Name Override |
| `text` | Review Reason, Cert #, Product Type, Description, Sticker Notes, Notes, Value Note, TCGplayer URL, Lineage ID, Predecessor, Item ID |
| *(no filter)* | Image |

Two picks that were argued for rather than defaulted, and the reasons belong in the code
as comments:

```ts
// Card ID is a PRESENCE control, not a text box. Nobody types `en:sv3pt5-158` from
// memory; the question actually asked at this column is "which of my cards are
// unlinked", and that is one dropdown.
{ id: 'cardIdPresence', label: 'Card link', columnKey: 'card_id', kind: 'presence' },

// Acquired Show is a SELECT sourced from GET /admin/shows, on the same reasoning that
// makes Location a dropdown: the values are a managed list, and a substring match
// across show names is not a question anyone has.
{ id: 'acquiredShow', label: 'Acquired Show', columnKey: 'acquired_show_id',
  kind: 'select', optionSource: 'shows' },
```

**The six filters that already exist as named params keep `legacyParam`** — `name`,
`status`, `condition`, `kind`, `location`, `min_price`/`max_price`, `ownership`,
`needs_review`, plus the three catalog ones. T3 deliberately left four of those
hand-written on the backend because they do more than a field comparison, so they must
keep sending their named param and **must not** be rewritten as `filter=`.

### `buildFilterParams`

One function turning the page's value record into the query. It is the only place that
knows about the two spellings:

```ts
/**
 * Split the filter values into named params and generic `filter=` triples.
 *
 * Two spellings, ONE evaluator on the backend (T3). A filter carrying `legacyParam`
 * keeps sending it — four of those do something on the server a plain field comparison
 * cannot (`name` searches notes too, `condition` splits LP+ into tier and modifier,
 * `min_price` falls back to cost, and the catalog filters join the catalog).
 */
export function buildFilterParams(values: FilterValues) {
  const params: Record<string, string> = {}
  const filters: string[] = []
  for (const def of INVENTORY_FILTERS) {
    const value = values[def.id] ?? ''
    if (value === '') continue
    if (def.legacyParam) { params[def.legacyParam] = value; continue }
    const field = def.field ?? def.columnKey
    if (!field) continue
    filters.push(`${field}:${opFor(def, value)}:${valueFor(def, value)}`)
  }
  return { params, filters }
}
```

A `range` filter is **two** registry entries (`costBasisMin` with op `gte`,
`costBasisMax` with op `lte`) sharing one `columnKey` — the same shape `minPrice` /
`maxPrice` already have today. That keeps `buildFilterParams` a straight map and keeps
`isFilterVisible` working unchanged.

A `presence` value is `'has'` or `'missing'`, mapping to `notnull` / `isnull` with an
empty value.

### `ColumnFilter.tsx`

One component, switching on `kind`. Every control gets `vault-field` — CLAUDE.md:
*"Never ship an admin control without `vault-field`"*, and the Slabs page is the
cautionary tale.

```tsx
export default function ColumnFilter({ def, value, onChange, options }: Props) {
  switch (def.kind) {
    case 'select':
      return (
        <select
          aria-label={def.label}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="vault-field px-2.5 py-1.5 rounded-lg text-xs appearance-none cursor-pointer w-full"
        >
          <option value="">{def.label}</option>
          {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      )
    case 'presence':
      return (
        <select aria-label={def.label} value={value} onChange={(e) => onChange(e.target.value)}
                className="vault-field px-2.5 py-1.5 rounded-lg text-xs appearance-none cursor-pointer w-full">
          <option value="">{def.label}</option>
          <option value="has">Has {def.label.toLowerCase()}</option>
          <option value="missing">Missing {def.label.toLowerCase()}</option>
        </select>
      )
    case 'dateRange':
      return <input type="date" aria-label={def.label} value={value}
                    onChange={(e) => onChange(e.target.value)}
                    className="vault-field px-2.5 py-1.5 rounded-lg text-xs w-full" />
    case 'range':
    case 'text':
    default:
      // NOT type="number" even for money bounds — a native number input refuses a
      // comma, which makes `1,300` un-typeable. CLAUDE.md, "MONEY INPUT".
      return <input type="text" inputMode={def.kind === 'range' ? 'decimal' : undefined}
                    aria-label={def.label} placeholder={def.label} value={value}
                    onChange={(e) => onChange(e.target.value)}
                    className="vault-field px-2.5 py-1.5 rounded-lg text-xs w-full" />
  }
}
```

> **A money bound is `type="text"`, not `type="number"`.** The owner types `1,300`. A
> native number input refuses the comma. Parse the bound with `parseMoney` from
> `lib/money.ts` in `buildFilterParams` — never `parseFloat`, which returns `1` for
> `"1,300"` and is not `NaN`.

### Page state

Thirteen `useState`s (`page.tsx:41-52`) collapse into one:

```tsx
const [filterValues, setFilterValues] = useState<FilterValues>({})
const setFilter = useCallback(
  (id: string, value: string) => setFilterValues((v) => ({ ...v, [id]: value })),
  [],
)
```

`fetchItems`'s dependency array collapses to `[api, filterValues, sortKey, sortDir]`.
The existing `filters` record, `FilterSelect` and `FilterText` (`page.tsx:254-360,
584-634`) are **deleted** — `ColumnFilter` replaces all of them.

`hiddenActiveFilters` (`page.tsx:366-368`) keeps working unchanged; it reads values from
the record instead of the old per-filter map.

## RED — write these first, show the failing output, then STOP

In `frontend/lib/__tests__/admin-inventory-columns.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import {
  INVENTORY_COLUMNS, INVENTORY_FILTERS, buildFilterParams, isFilterVisible,
} from '@/lib/admin-inventory-columns'

describe('every column has a filter', () => {
  const NO_FILTER = new Set(['_image', '_actions'])

  it('covers every column', () => {
    const covered = new Set(INVENTORY_FILTERS.map((f) => f.columnKey).filter(Boolean))
    const uncovered = INVENTORY_COLUMNS
      .filter((c) => !NO_FILTER.has(c.key) && !covered.has(c.key))
      .map((c) => c.key)
    expect(uncovered).toEqual([])
  })

  it('gives every filter a kind and a unique id', () => {
    const ids = INVENTORY_FILTERS.map((f) => f.id)
    expect(new Set(ids).size).toBe(ids.length)
    for (const f of INVENTORY_FILTERS) {
      expect(f.kind).toBeTruthy()
    }
  })

  it('names a real column, or is deliberately column-less', () => {
    const keys = new Set(INVENTORY_COLUMNS.map((c) => c.key))
    for (const f of INVENTORY_FILTERS) {
      if (f.columnKey !== null) expect(keys.has(f.columnKey)).toBe(true)
    }
  })
})

describe('buildFilterParams', () => {
  it('sends a legacy named param where one exists', () => {
    const { params, filters } = buildFilterParams({ status: 'available' })
    expect(params.status).toBe('available')
    expect(filters).toEqual([])
  })

  it('sends a generic triple for a new filter', () => {
    const { params, filters } = buildFilterParams({ notes: 'foil' })
    expect(filters).toEqual(['notes:contains:foil'])
    expect(params).toEqual({})
  })

  it('maps presence to isnull and notnull', () => {
    expect(buildFilterParams({ cardIdPresence: 'missing' }).filters)
      .toEqual(['card_id:isnull:'])
    expect(buildFilterParams({ cardIdPresence: 'has' }).filters)
      .toEqual(['card_id:notnull:'])
  })

  it('accepts a money bound typed with a comma', () => {
    // parseFloat("1,300") is 1 and is not NaN — a silent $1,299 error.
    expect(buildFilterParams({ costBasisMin: '1,300' }).filters)
      .toEqual(['cost_basis:gte:1300'])
  })

  it('omits an empty value entirely', () => {
    const { params, filters } = buildFilterParams({ notes: '', status: '' })
    expect(filters).toEqual([])
    expect(params).toEqual({})
  })
})

describe('a filter follows its column', () => {
  it('is hidden when its column is hidden', () => {
    const notes = INVENTORY_FILTERS.find((f) => f.id === 'notes')!
    expect(isFilterVisible(notes, new Set(['status']), false)).toBe(false)
    expect(isFilterVisible(notes, new Set(['notes']), false)).toBe(true)
  })

  it('is revealed by the show-all escape hatch regardless', () => {
    const notes = INVENTORY_FILTERS.find((f) => f.id === 'notes')!
    expect(isFilterVisible(notes, new Set(['status']), true)).toBe(true)
  })
})
```

In the inventory page test, one behavioral test that pins the owner's actual ask:

```tsx
it('shows a column filter when the column is turned on, and hides it again', async () => {
  const user = userEvent.setup({ delay: null })   // never the default: it is per-keystroke
  render(<AdminInventoryPage />)

  expect(screen.queryByLabelText('Notes')).not.toBeInTheDocument()

  await user.click(screen.getByRole('button', { name: /columns/i }))
  await user.click(screen.getByRole('checkbox', { name: 'Notes' }))
  expect(await screen.findByLabelText('Notes')).toBeInTheDocument()

  await user.click(screen.getByRole('checkbox', { name: 'Notes' }))
  expect(screen.queryByLabelText('Notes')).not.toBeInTheDocument()
})
```

**Run, show the owner the failures, and WAIT.**

```bash
cd frontend && npx vitest run lib/__tests__/admin-inventory-columns.test.ts
```

## Watch for

- **`mockReset()` in `beforeEach`, never `clearAllMocks()`.** This page's tests queue
  `mockResolvedValueOnce` fetch replies, and `clearAllMocks` does not drain that queue —
  leftovers cascade into the next test.
- **`userEvent.setup({ delay: null })`.** The picker test types and clicks a lot.
- **Do not touch `isFilterVisible`, `hiddenActiveFilters`, or the column picker.** They
  already do the right thing; this task only feeds them more data.
- **21 new controls in a 6-column grid is a lot of panel.** The grid already collapses
  responsively (`grid-cols-2 md:grid-cols-4 lg:grid-cols-6`); the panel only ever shows
  filters for *visible* columns, so in practice it stays small. Do not add a second
  disclosure — "Show all filters" is already the escape hatch.

## Done means

1. both test files pass, output shown;
2. `npm run lint --workspace=frontend` clean;
3. by hand: turn on Notes, Grade and Acquired; confirm a text box, a Min/Max pair and a
   date pair appear, that each narrows the list, and that turning the column off both
   hides the control **and** raises the existing "Filtering on a hidden column" notice if
   a value was left in it;
4. `progress.md` updated.

Do not run the full suite. Do not merge. Do not push.
