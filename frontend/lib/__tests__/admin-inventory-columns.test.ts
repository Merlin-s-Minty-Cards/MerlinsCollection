import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import {
  INVENTORY_COLUMNS,
  INVENTORY_FILTERS,
  DEFAULT_VISIBLE_COLUMN_KEYS,
  COLUMN_STORAGE_KEY,
  buildFilterParams,
  loadVisibleColumnKeys,
  saveVisibleColumnKeys,
  isFilterVisible,
} from '@/lib/admin-inventory-columns'

// ===========================================================================
// T6 — the column registry itself (RFC 0008 §F5)
// ===========================================================================
//
// The page-level behaviours (picker, filter panel, inline editing) are pinned
// in app/(admin)/admin/inventory/__tests__/page.test.tsx. This file pins the
// module's own contract: the shape of the registry and the persistence layer's
// tolerance for whatever is actually sitting in localStorage.

describe('the registry itself', () => {
  it('has unique keys', () => {
    // A duplicate key silently breaks BOTH the React table (duplicate <th> key)
    // and the picker (two checkboxes toggling one entry), and neither failure
    // names the cause.
    const keys = INVENTORY_COLUMNS.map((c) => c.key)
    expect(new Set(keys).size).toBe(keys.length)
  })

  it('exposes the superset of the item union, not just what the page hardcoded', () => {
    // The point of the task: fields that exist on the backend union
    // (models/inventory.py) but were never displayable become available.
    const keys = new Set(INVENTORY_COLUMNS.map((c) => c.key))
    for (const key of [
      'company', 'grade', 'cert_number',     // graded
      'product_type', 'description',         // sealed / bulk
      'finish', 'factory_sealed',            // raw
      'listed_price', 'market_value_at_purchase', 'acquired_at',
      'notes', 'value_note', 'language', 'needs_review',
      'display_name_override', 'lineage_id',
    ]) {
      expect(keys, `missing registry column: ${key}`).toContain(key)
    }
  })

  it('derives DEFAULT_VISIBLE_COLUMN_KEYS from defaultVisible, in registry order', () => {
    expect(DEFAULT_VISIBLE_COLUMN_KEYS).toEqual(
      INVENTORY_COLUMNS.filter((c) => c.defaultVisible).map((c) => c.key),
    )
  })

  it('points every filter at a column that exists, or at nothing on purpose', () => {
    // A typo'd columnKey would make the filter permanently invisible with no
    // error anywhere — it would just quietly never satisfy isFilterVisible.
    const keys = new Set(INVENTORY_COLUMNS.map((c) => c.key))
    for (const f of INVENTORY_FILTERS) {
      if (f.columnKey !== null) {
        expect(keys, `filter ${f.id} points at unknown column ${f.columnKey}`).toContain(f.columnKey)
      }
    }
  })

  it('hides a column-less filter by default and reveals it only under "show all"', () => {
    // set_name / card_number / artist filter on catalog fields the ordinary
    // admin search response does not carry, so they have no column to follow.
    const catalogOnly = INVENTORY_FILTERS.filter((f) => f.columnKey === null)
    expect(catalogOnly.length).toBeGreaterThan(0)
    for (const f of catalogOnly) {
      expect(isFilterVisible(f, new Set(DEFAULT_VISIBLE_COLUMN_KEYS), false)).toBe(false)
      expect(isFilterVisible(f, new Set(DEFAULT_VISIBLE_COLUMN_KEYS), true)).toBe(true)
    }
  })
})

describe('loadVisibleColumnKeys tolerates whatever is in localStorage', () => {
  beforeEach(() => {
    window.localStorage.clear()
  })

  it('returns the defaults when nothing is stored', () => {
    expect(loadVisibleColumnKeys()).toEqual(DEFAULT_VISIBLE_COLUMN_KEYS)
  })

  it('drops a saved key that is no longer in the registry', () => {
    window.localStorage.setItem(
      COLUMN_STORAGE_KEY,
      JSON.stringify(['display_name', 'a_column_that_was_renamed', 'status']),
    )
    expect(loadVisibleColumnKeys()).toEqual(['display_name', 'status'])
  })

  it('falls back to the defaults rather than throwing on unparseable JSON', () => {
    // This runs on mount. An exception here blanks the whole page.
    window.localStorage.setItem(COLUMN_STORAGE_KEY, '{not json at all')
    expect(() => loadVisibleColumnKeys()).not.toThrow()
    expect(loadVisibleColumnKeys()).toEqual(DEFAULT_VISIBLE_COLUMN_KEYS)
  })

  it('falls back to the defaults when the stored value is valid JSON of the wrong shape', () => {
    for (const junk of ['null', '42', '"display_name"', '{"display_name":true}']) {
      window.localStorage.setItem(COLUMN_STORAGE_KEY, junk)
      expect(loadVisibleColumnKeys(), `for stored value ${junk}`).toEqual(DEFAULT_VISIBLE_COLUMN_KEYS)
    }
  })

  it('ignores non-string members instead of rendering them', () => {
    window.localStorage.setItem(COLUMN_STORAGE_KEY, JSON.stringify(['status', 7, null, { key: 'kind' }]))
    expect(loadVisibleColumnKeys()).toEqual(['status'])
  })

  it('falls back to the defaults when nothing in the saved list survives validation', () => {
    // Every saved key retired at once (a registry rewrite without a version
    // bump). An empty table is worse than a reset one.
    window.localStorage.setItem(COLUMN_STORAGE_KEY, JSON.stringify(['gone_a', 'gone_b']))
    expect(loadVisibleColumnKeys()).toEqual(DEFAULT_VISIBLE_COLUMN_KEYS)
  })

  it('returns keys in registry order regardless of the order they were saved in', () => {
    // Otherwise the columns rearrange themselves according to the sequence the
    // admin happened to tick the boxes in.
    window.localStorage.setItem(COLUMN_STORAGE_KEY, JSON.stringify(['status', 'display_name']))
    expect(loadVisibleColumnKeys()).toEqual(['display_name', 'status'])
  })
})

describe('storage access that throws is survivable', () => {
  beforeEach(() => {
    window.localStorage.clear()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  // Spy on Storage.prototype, NOT on the `window.localStorage` instance. jsdom
  // backs Storage with a Proxy whose defineProperty trap writes a storage ENTRY
  // for any string key — so `vi.spyOn(window.localStorage, 'getItem')` silently
  // stores an item called "getItem" and leaves the real method in place. The
  // test then passes against unpatched code, which is how this nearly shipped.

  it('returns the defaults when reading localStorage throws', () => {
    // Safari private mode / storage disabled by policy throws SecurityError.
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('SecurityError')
    })
    expect(loadVisibleColumnKeys()).toEqual(DEFAULT_VISIBLE_COLUMN_KEYS)
  })

  it('does not throw out of a click handler when writing localStorage fails', () => {
    // saveVisibleColumnKeys is called from the picker's onChange. A
    // QuotaExceededError escaping there takes the page down over a checkbox.
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('QuotaExceededError')
    })
    expect(() => saveVisibleColumnKeys(['status'])).not.toThrow()
  })
})

// ===========================================================================
// RFC 0011 T1/T2 — every column is sortable
// ===========================================================================
//
// The backend registry (`services/inventory_sort.SORT_FIELDS`) covers every
// model field. These pin the frontend half: that we actually MARK the columns,
// and that the keys stay parseable as `{field}_{direction}`.

describe('every column is sortable except the two that cannot be', () => {
  // `_image` renders art resolved client-side from card_id — there is no
  // server-side value to order by. `_actions` is a pinned button cell.
  const UNSORTABLE = new Set(['_image', '_actions'])

  it('marks every data column sortable', () => {
    const unmarked = INVENTORY_COLUMNS
      .filter((c) => !UNSORTABLE.has(c.key) && !c.sortable)
      .map((c) => c.key)

    expect(unmarked).toEqual([])
  })

  it('leaves the image and action cells unsortable', () => {
    for (const key of UNSORTABLE) {
      expect(INVENTORY_COLUMNS.find((c) => c.key === key)?.sortable).toBeFalsy()
    }
  })

  it('uses keys the backend can parse as {field}_{direction}', () => {
    // The page sends `${key}_${dir}` and the backend rsplits on the LAST
    // underscore, so a key ending in _asc or _desc would parse as a direction
    // and lose its field entirely.
    for (const col of INVENTORY_COLUMNS) {
      expect(col.key.endsWith('_asc')).toBe(false)
      expect(col.key.endsWith('_desc')).toBe(false)
    }
  })
})

// ===========================================================================
// RFC 0011 T4 — a dedicated filter for every column
// ===========================================================================
//
// The show/hide behaviour already shipped in RFC 0008 T6; what was missing was
// COVERAGE — twelve filters for thirty-three columns. These pin that the
// registry is now total, and that `buildFilterParams` speaks both spellings the
// backend accepts (T3): the pre-existing named parameters, and the generic
// repeatable `filter={field}:{op}:{value}`.

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

  it('gives every filter a unique label', () => {
    // The panel is queried BY LABEL, in the page tests and by an admin's screen
    // reader alike. Two filters sharing one accessible name make
    // `getByLabelText` ambiguous, which fails as "found multiple elements"
    // rather than as anything that names the duplicate.
    const labels = INVENTORY_FILTERS.map((f) => f.label)
    const dupes = labels.filter((l, i) => labels.indexOf(l) !== i)
    expect(dupes).toEqual([])
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

  it('parses a comma on the LEGACY money params too', () => {
    // min_price/max_price keep their named parameter, but they are still money
    // fields typed by the same person. Passing "1,300" through untouched sends
    // it at a `Decimal` query param and 422s the whole list.
    expect(buildFilterParams({ minPrice: '1,300' }).params.min_price).toBe('1300')
  })

  it('drops a half-typed bound rather than sending one the backend will reject', () => {
    // The value changes on every keystroke, so "1," exists for as long as it
    // takes to type the next digit. Sending it 422s the list mid-type.
    expect(buildFilterParams({ costBasisMin: '1,' }).filters).toEqual([])
  })

  it('sends a date bound through untouched, in the ISO form the input produced', () => {
    // `<input type="date">` already yields YYYY-MM-DD. Routing it through
    // `new Date()` would reinterpret it as UTC midnight and shift it a day.
    expect(buildFilterParams({ acquiredFrom: '2026-08-13' }).filters)
      .toEqual(['acquired_at:gte:2026-08-13'])
  })

  it('AND-combines two bounds on one field into two triples', () => {
    const { filters } = buildFilterParams({ gradeMin: '9', gradeMax: '10' })
    expect(filters).toEqual(['grade:gte:9', 'grade:lte:10'])
  })

  it('omits an empty value entirely', () => {
    const { params, filters } = buildFilterParams({ notes: '', status: '' })
    expect(filters).toEqual([])
    expect(params).toEqual({})
  })

  it('only ever emits ops the backend registry accepts for that kind', () => {
    // A `contains` on a SELECT field is a 422, not a wider match. This is the
    // one place the two registries can silently disagree.
    const OPS_BY_KIND: Record<string, string[]> = {
      text: ['contains', 'eq'],
      select: ['eq'],
      range: ['gte', 'lte'],
      dateRange: ['gte', 'lte'],
      presence: ['isnull', 'notnull'],
    }
    for (const def of INVENTORY_FILTERS) {
      if (def.legacyParam) continue
      const probe = def.kind === 'presence' ? 'has'
        : def.kind === 'dateRange' ? '2026-08-13'
        : def.kind === 'range' ? '1'
        : 'x'
      const [triple] = buildFilterParams({ [def.id]: probe }).filters
      expect(triple, `filter ${def.id} produced nothing`).toBeTruthy()
      const op = triple.split(':')[1]
      expect(OPS_BY_KIND[def.kind], `filter ${def.id} emitted op ${op}`).toContain(op)
    }
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
