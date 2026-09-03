import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, act, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AdminInventoryPage from '../page'
import { COLUMN_STORAGE_KEY, INVENTORY_FILTERS } from '@/lib/admin-inventory-columns'

const getMock = vi.fn()
const postMock = vi.fn()
const putMock = vi.fn()
const mockApi = {
  get: getMock, post: postMock, put: putMock, patch: vi.fn(), del: vi.fn(),
  isAuthenticated: true, isLoading: false,
}

vi.mock('@/lib/admin-api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/admin-api')>('@/lib/admin-api')
  return { ...actual, useAdminApi: () => mockApi }
})

describe('AdminInventoryPage location pickers use the live location list', () => {
  beforeEach(() => {
    getMock.mockReset()
    postMock.mockReset()
    putMock.mockReset()
    postMock.mockResolvedValue({ item_id: 'new-1' })
    putMock.mockResolvedValue({})
    getMock.mockImplementation((path: string) => {
      if (path === '/locations') {
        return Promise.resolve([{ value: 'custom_shelf', label: 'Custom Shelf' }])
      }
      if (path === '/inventory/search') {
        return Promise.resolve({
          items: [{ item_id: 'item-1', display_name: 'Pikachu', location: 'custom_shelf', status: 'available' }],
          total: 1,
        })
      }
      return Promise.resolve({})
    })
  })

  it('create-form location select uses live options, not the static LOCATION_OPTIONS list', async () => {
    render(<AdminInventoryPage />)
    await act(async () => { await Promise.resolve() })

    // Real accessible name confirmed by reading inventory/page.tsx's header
    // button: it reads "Add Item" (with a Plus icon), not "New Item".
    fireEvent.click(screen.getByRole('button', { name: /add item/i }))

    // Scope to the create-form dialog itself, not the whole document. The
    // filter-bar location <select> (page.tsx, already wired to useLocations()
    // before this task) also renders a "Custom Shelf" <option> once its own
    // useLocations() call resolves, so an unscoped screen.findByRole('option',
    // { name: 'Custom Shelf' }) can pass on the filter bar's option alone —
    // proving nothing about CreateItemModal's own select. Scoping via
    // within(dialog) makes both the positive and negative assertions actually
    // exercise CreateItemModal's dropdown.
    const dialog = await screen.findByRole('dialog', { name: /add new item/i })

    expect(await within(dialog).findByRole('option', { name: 'Custom Shelf' })).toBeInTheDocument()
    // "Glass Case" is not an actual LOCATION_OPTIONS label (the static list has
    // "Glass" and "Display Case" as separate entries), so it would never appear
    // either way — that assertion wouldn't catch a regression. "Toploader" is a
    // real static-list label, so its absence actually proves the dropdown is no
    // longer sourced from the static list (mirrors the negative check used in
    // CardDetailModal.test.tsx).
    expect(within(dialog).queryByRole('option', { name: /Toploader/i })).not.toBeInTheDocument()
  })

  it('filters by needs_review via the Needs Review select', async () => {
    render(<AdminInventoryPage />)
    await act(async () => { await Promise.resolve() })

    // T6: filters now follow the visible columns, and the Review column is not
    // one of the defaults — so this control lives behind the escape hatch
    // rather than always on the panel.
    fireEvent.click(screen.getByRole('button', { name: /show all filters/i }))
    fireEvent.change(screen.getByLabelText(/needs review/i), { target: { value: 'true' } })

    await waitFor(() =>
      expect(getMock).toHaveBeenCalledWith(
        '/inventory/search',
        expect.objectContaining({ needs_review: 'true' }),
      )
    )
  })

  it('create-form defaults location to the first live option, not a hardcoded "toploader" (finding 2)', async () => {
    // "toploader" is deletable via DELETE /admin/locations/{value} once no
    // item uses it (Task 7's whole point) — a hardcoded default that
    // survives its deletion 422s "Unknown location" on submit unless the
    // admin happens to touch the dropdown themselves.
    render(<AdminInventoryPage />)
    await act(async () => { await Promise.resolve() })

    fireEvent.click(screen.getByRole('button', { name: /add item/i }))
    const dialog = await screen.findByRole('dialog', { name: /add new item/i })

    fireEvent.change(within(dialog).getByLabelText(/^name$/i), { target: { value: 'Pikachu' } })
    fireEvent.click(within(dialog).getByRole('button', { name: /^create$/i }))

    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith(
        '/inventory',
        expect.objectContaining({ location: 'custom_shelf' }),
      )
    )
  })
})

// ===========================================================================
// final-review Fix 6 — the C2 plan (docs/plans/rfc-0012/c2-inventory-filter.md)
// specified this page-level test and it was never written. The registry test
// (lib/__tests__/admin-inventory-columns.test.ts) only asserts the entry's
// SHAPE — it would still pass even if page.tsx's `selectOptions()`
// 'cosigners' branch (which sources the options from `useCosigners()`) or the
// filter's wiring into the search request were deleted outright.
// ===========================================================================
describe('AdminInventoryPage Consignor filter (RFC 0012 C2)', () => {
  beforeEach(() => {
    getMock.mockReset()
    postMock.mockReset()
    putMock.mockReset()
    getMock.mockImplementation((path: string) => {
      if (path === '/cosigners') {
        return Promise.resolve([{ consignor_id: 'cos-1', name: 'Alex' }])
      }
      if (path === '/inventory/search') {
        return Promise.resolve({ items: [], total: 0 })
      }
      // "Show all filters" renders every registry entry, not just Consignor —
      // useLocations()/useShows()/catalog-sets all expect an array back, so
      // these need explicit empty-array responses rather than falling through
      // to the bare `{}` default (which crashes ColumnFilter's `options.map`).
      if (path === '/locations') return Promise.resolve([])
      if (path === '/shows') return Promise.resolve([])
      if (path === '/catalog/sets') return Promise.resolve([])
      return Promise.resolve({})
    })
  })

  it('renders the Consignor filter sourced from useCosigners(), with the cosigner option', async () => {
    render(<AdminInventoryPage />)
    await act(async () => { await Promise.resolve() })

    fireEvent.click(screen.getByRole('button', { name: /show all filters/i }))

    const select = await screen.findByLabelText('Consignor')
    expect(within(select).getByRole('option', { name: 'Alex' })).toBeInTheDocument()
  })

  it('sends consignor_id on the search request when a consignor option is selected', async () => {
    render(<AdminInventoryPage />)
    await act(async () => { await Promise.resolve() })

    fireEvent.click(screen.getByRole('button', { name: /show all filters/i }))
    const select = await screen.findByLabelText('Consignor')
    fireEvent.change(select, { target: { value: 'cos-1' } })

    await waitFor(() =>
      expect(getMock).toHaveBeenCalledWith(
        '/inventory/search',
        expect.objectContaining({ consignor_id: 'cos-1' }),
      ),
    )
  })
})

describe('AdminInventoryPage inline location edit no-op guard', () => {
  beforeEach(() => {
    getMock.mockReset()
    postMock.mockReset()
    putMock.mockReset()
    putMock.mockResolvedValue({})
    getMock.mockImplementation((path: string) => {
      if (path === '/locations') {
        return Promise.resolve([{ value: 'glass', label: 'Glass' }])
      }
      if (path === '/inventory/search') {
        // A null-location item — Buy/Trade can leave location unset by
        // design, and the inline editor no longer has a "— None —" option
        // to explicitly re-select once location became required (finding 6).
        return Promise.resolve({
          items: [{ item_id: 'item-1', display_name: 'Pikachu', location: null, status: 'available' }],
          total: 1,
        })
      }
      return Promise.resolve({})
    })
  })

  it('does not PUT when the location editor is opened and blurred without a change', async () => {
    render(<AdminInventoryPage />)
    await act(async () => { await Promise.resolve() })

    fireEvent.click(screen.getByRole('button', { name: 'Edit Location' }))
    const select = screen.getByRole('combobox', { name: /edit location/i })
    fireEvent.blur(select)

    await act(async () => { await Promise.resolve() })
    expect(putMock).not.toHaveBeenCalled()
  })
})

// ===========================================================================
// T11 — "Send to Triage" reaches this page
// ===========================================================================
//
// Two separate claims are pinned here, because they fail independently:
//   1. the row-level QUICK ACTION exists on this list-heavy page (spotting a
//      bad card mid-workflow is the actual use case, and a modal round-trip
//      per card defeats it);
//   2. the SHARED MODAL's button actually reaches an item opened from this
//      page. T5 established CardDetailModal is mounted by five pages, not
//      "any admin page" as its docstring once claimed — so the cross-page
//      reach is only real if asserted from a page. Its twin lives in
//      app/(admin)/admin/outgoing/__tests__/page.test.tsx.
describe('AdminInventoryPage — Send to Triage (RFC 0008 T11)', () => {
  beforeEach(() => {
    getMock.mockReset()
    postMock.mockReset()
    putMock.mockReset()
    putMock.mockResolvedValue({})
    postMock.mockResolvedValue({})
    getMock.mockImplementation((path: string) => {
      if (path === '/locations') return Promise.resolve([{ value: 'glass', label: 'Glass' }])
      if (path === '/inventory/search') {
        return Promise.resolve({
          items: [{
            item_id: 'item-1', kind: 'raw', display_name: 'Pikachu',
            location: 'glass', status: 'available', needs_review: false,
          }],
          total: 1,
        })
      }
      // `null`, not `{}` — this block opens CardDetailModal, whose PriceChart
      // reads `chartData.points` and crashes the whole tree on an object with
      // no `points` key. `null` is its real "no data yet" shape (see the same
      // note in CardDetailModal.test.tsx).
      return Promise.resolve(null)
    })
  })

  it('flags a row straight from the table, with no modal round-trip', async () => {
    render(<AdminInventoryPage />)
    await act(async () => { await Promise.resolve() })

    fireEvent.click(await screen.findByRole('button', { name: /send pikachu to triage/i }))

    // The quick action is deliberately note-less: it is the mid-workflow "this
    // one is wrong" gesture. The note lives on the modal's slower path.
    await waitFor(() =>
      expect(putMock).toHaveBeenCalledWith('/inventory/item-1', { needs_review: true }),
    )
  })

  it('offers an Undo, because a misclick on a row action is inevitable', async () => {
    render(<AdminInventoryPage />)
    await act(async () => { await Promise.resolve() })

    fireEvent.click(await screen.findByRole('button', { name: /send pikachu to triage/i }))
    fireEvent.click(await screen.findByRole('button', { name: /undo/i }))

    await waitFor(() =>
      expect(putMock).toHaveBeenLastCalledWith('/inventory/item-1', {
        needs_review: false,
        review_reason: null,
      }),
    )
  })

  it('reaches the shared detail modal opened from this page', async () => {
    render(<AdminInventoryPage />)
    await act(async () => { await Promise.resolve() })

    fireEvent.click(screen.getByText('Pikachu'))

    const modal = await screen.findByRole('dialog', { name: /details for/i })
    expect(within(modal).getByRole('button', { name: /send to triage/i })).toBeInTheDocument()
  })
})

// ===========================================================================
// T6 — Configurable columns, and filters that follow them (RFC 0008 §F5)
// ===========================================================================
//
// Two owner decisions are pinned here and neither is negotiable by a later
// refactor:
//   * filters follow the VISIBLE columns, with a "show all filters" escape
//     hatch (RFC Q9);
//   * hiding a column never silently drops a filter, and a filter whose column
//     is hidden is marked as such — silent invisible filtering is the failure
//     mode this whole section exists to avoid.

const DEFAULT_HEADERS = [
  'Name', 'Status', 'Kind', 'Cond', 'Location', 'Price Paid', 'Market', 'Sticker', 'Ownership', 'Consignor',
  // RFC 0023 T5 — finish_attributes joined the default-visible set.
  'Finish Attributes', '',
]

function headers(): string[] {
  return screen.getAllByRole('columnheader').map((th) => th.textContent ?? '')
}

async function openPicker(): Promise<HTMLElement> {
  fireEvent.click(screen.getByRole('button', { name: /^columns$/i }))
  return screen.findByRole('group', { name: /column visibility/i })
}

describe('AdminInventoryPage — configurable columns', () => {
  beforeEach(() => {
    window.localStorage.clear()
    getMock.mockReset()
    postMock.mockReset()
    putMock.mockReset()
    putMock.mockResolvedValue({})
    getMock.mockImplementation((path: string) => {
      if (path === '/locations') {
        return Promise.resolve([
          { value: 'glass', label: 'Glass' },
          { value: 'binder', label: 'Binder' },
        ])
      }
      if (path === '/inventory/search') {
        return Promise.resolve({
          items: [{
            item_id: 'item-1', kind: 'raw', display_name: 'Pikachu',
            location: 'glass', status: 'available', condition: 'NM',
            cost_basis: '4.00', current_market_value: '12.00', needs_review: false,
          }],
          total: 1,
        })
      }
      return Promise.resolve(null)
    })
  })

  it('renders exactly the defaultVisible registry columns on a first visit', async () => {
    render(<AdminInventoryPage />)
    await act(async () => { await Promise.resolve() })

    expect(headers()).toEqual(DEFAULT_HEADERS)
  })

  it('removes a column from the table when it is unchecked', async () => {
    render(<AdminInventoryPage />)
    await act(async () => { await Promise.resolve() })

    const picker = await openPicker()
    fireEvent.click(within(picker).getByRole('checkbox', { name: 'Market' }))

    expect(headers()).not.toContain('Market')
    expect(headers()).toContain('Name')
  })

  it('remembers the choice across a remount', async () => {
    const first = render(<AdminInventoryPage />)
    await act(async () => { await Promise.resolve() })

    const picker = await openPicker()
    fireEvent.click(within(picker).getByRole('checkbox', { name: 'Market' }))
    first.unmount()

    render(<AdminInventoryPage />)
    await act(async () => { await Promise.resolve() })

    expect(headers()).not.toContain('Market')
  })

  it('ignores a saved key that is no longer in the registry and still renders', async () => {
    window.localStorage.setItem(
      COLUMN_STORAGE_KEY,
      JSON.stringify(['display_name', 'status', 'a_column_that_was_renamed']),
    )
    render(<AdminInventoryPage />)
    await act(async () => { await Promise.resolve() })

    expect(headers()).toEqual(['Name', 'Status', ''])
    expect(await screen.findByText('Pikachu')).toBeInTheDocument()
  })

  it('falls back to the defaults on a corrupt saved value instead of throwing', async () => {
    // This read happens on mount; an exception here blanks the page.
    window.localStorage.setItem(COLUMN_STORAGE_KEY, '{not json at all')
    render(<AdminInventoryPage />)
    await act(async () => { await Promise.resolve() })

    expect(headers()).toEqual(DEFAULT_HEADERS)
  })

  it('keeps column order fixed no matter what sequence the boxes are ticked in', async () => {
    render(<AdminInventoryPage />)
    await act(async () => { await Promise.resolve() })

    const picker = await openPicker()
    // Off in one order...
    fireEvent.click(within(picker).getByRole('checkbox', { name: 'Kind' }))
    fireEvent.click(within(picker).getByRole('checkbox', { name: 'Status' }))
    // ...back on in the other.
    fireEvent.click(within(picker).getByRole('checkbox', { name: 'Status' }))
    fireEvent.click(within(picker).getByRole('checkbox', { name: 'Kind' }))

    expect(headers()).toEqual(DEFAULT_HEADERS)
  })

  it('still edits location inline after the move into the registry', async () => {
    render(<AdminInventoryPage />)
    await act(async () => { await Promise.resolve() })

    fireEvent.click(screen.getByRole('button', { name: 'Edit Location' }))
    const select = screen.getByRole('combobox', { name: /edit location/i })
    // `select` commits on change now (RFC 0022), not on blur.
    fireEvent.change(select, { target: { value: 'binder' } })

    await waitFor(() =>
      expect(putMock).toHaveBeenCalledWith('/inventory/item-1', { location: 'binder' }),
    )
  })
})

describe('AdminInventoryPage — filters follow the visible columns', () => {
  beforeEach(() => {
    window.localStorage.clear()
    getMock.mockReset()
    postMock.mockReset()
    putMock.mockReset()
    putMock.mockResolvedValue({})
    getMock.mockImplementation((path: string) => {
      if (path === '/locations') return Promise.resolve([{ value: 'glass', label: 'Glass' }])
      if (path === '/inventory/search') {
        return Promise.resolve({
          items: [{
            item_id: 'item-1', kind: 'raw', display_name: 'Pikachu',
            location: 'glass', status: 'available', needs_review: false,
          }],
          total: 1,
        })
      }
      return Promise.resolve(null)
    })
  })

  it('offers only the filters whose column is visible', async () => {
    render(<AdminInventoryPage />)
    await act(async () => { await Promise.resolve() })

    const filters = screen.getByRole('group', { name: /^filters$/i })
    // Status is a default column, so its filter is on the panel.
    expect(within(filters).getByLabelText('Status')).toBeInTheDocument()
    // Review is not a default column, so its filter is not.
    expect(within(filters).queryByLabelText('Needs Review')).not.toBeInTheDocument()
    // Set/Card #/Artist filter catalog fields the admin search response does
    // not carry, so they have no column to follow at all.
    expect(within(filters).queryByLabelText('Artist')).not.toBeInTheDocument()
  })

  it('reveals every filterable field under "Show all filters"', async () => {
    // Loops the registry rather than spot-checking two. A filter declared in
    // INVENTORY_FILTERS with no control on the page renders as nothing at all
    // and is otherwise completely silent — the escape hatch would just be
    // missing a field with no error anywhere.
    render(<AdminInventoryPage />)
    await act(async () => { await Promise.resolve() })

    fireEvent.click(screen.getByRole('button', { name: /show all filters/i }))

    const filters = screen.getByRole('group', { name: /^filters$/i })
    for (const f of INVENTORY_FILTERS) {
      expect(
        within(filters).queryByLabelText(f.label),
        `no control rendered for filter "${f.id}" (label "${f.label}")`,
      ).toBeInTheDocument()
    }
  })

  it('clears a hidden-column filter from its chip', async () => {
    render(<AdminInventoryPage />)
    await act(async () => { await Promise.resolve() })

    fireEvent.click(screen.getByRole('button', { name: /show all filters/i }))
    fireEvent.change(screen.getByLabelText('Artist'), { target: { value: 'Mitsuhiro Arita' } })

    const notice = await screen.findByRole('region', { name: /hidden column/i })
    fireEvent.click(within(notice).getByRole('button', { name: /clear artist filter/i }))

    expect(screen.queryByRole('region', { name: /hidden column/i })).not.toBeInTheDocument()
    await waitFor(() =>
      expect(getMock).toHaveBeenLastCalledWith(
        '/inventory/search',
        expect.not.objectContaining({ artist: expect.anything() }),
      ),
    )
  })

  it('marks a filter whose column is hidden, and offers to show that column', async () => {
    render(<AdminInventoryPage />)
    await act(async () => { await Promise.resolve() })

    fireEvent.click(screen.getByRole('button', { name: /show all filters/i }))
    fireEvent.change(screen.getByLabelText('Needs Review'), { target: { value: 'true' } })

    const notice = await screen.findByRole('region', { name: /hidden column/i })
    expect(within(notice).getByText(/needs review/i)).toBeInTheDocument()

    // One click puts the column back — the point is that the admin can see
    // WHY the result set shrank.
    fireEvent.click(within(notice).getByRole('button', { name: /show column/i }))
    expect(headers()).toContain('Review')
    expect(screen.queryByRole('region', { name: /hidden column/i })).not.toBeInTheDocument()
  })

  it('keeps an active filter applied when its column is hidden', async () => {
    render(<AdminInventoryPage />)
    await act(async () => { await Promise.resolve() })

    fireEvent.change(screen.getByLabelText('Status'), { target: { value: 'available' } })
    await waitFor(() =>
      expect(getMock).toHaveBeenCalledWith('/inventory/search', expect.objectContaining({ status: 'available' })),
    )

    const picker = await openPicker()
    fireEvent.click(within(picker).getByRole('checkbox', { name: 'Status' }))

    // Dropping the filter because a column was hidden is data loss from the
    // admin's point of view. Force a refetch and prove the filter is still on
    // the wire, and that it is flagged rather than silent.
    //
    // Scoped: the picker is open, and its "Kind" checkbox carries the same
    // accessible name as the Kind filter.
    const filters = screen.getByRole('group', { name: /^filters$/i })
    fireEvent.change(within(filters).getByLabelText('Kind'), { target: { value: 'raw' } })
    await waitFor(() =>
      expect(getMock).toHaveBeenLastCalledWith(
        '/inventory/search',
        expect.objectContaining({ status: 'available', kind: 'raw' }),
      ),
    )
    const notice = screen.getByRole('region', { name: /hidden column/i })
    expect(within(notice).getByText(/status/i)).toBeInTheDocument()
  })
})

// ===========================================================================
// RFC 0011 T4 — a dedicated filter for every column
// ===========================================================================
//
// The owner's ask, verbatim: "each column should have a dedicated filter that
// shows up and disappears when the column is selected or unselected." The
// show/hide MECHANISM shipped in RFC 0008 T6; what T4 adds is that there is
// something to show for every column, and that the new ones reach the backend
// as the generic repeatable `filter={field}:{op}:{value}` triple T3 accepts.
describe('AdminInventoryPage — a filter for every column (RFC 0011 T4)', () => {
  beforeEach(() => {
    window.localStorage.clear()
    getMock.mockReset()
    postMock.mockReset()
    putMock.mockReset()
    putMock.mockResolvedValue({})
    getMock.mockImplementation((path: string) => {
      if (path === '/locations') return Promise.resolve([{ value: 'glass', label: 'Glass' }])
      if (path === '/inventory/search') {
        return Promise.resolve({
          items: [{
            item_id: 'item-1', kind: 'raw', display_name: 'Pikachu',
            location: 'glass', status: 'available', needs_review: false,
          }],
          total: 1,
        })
      }
      return Promise.resolve(null)
    })
  })

  /**
   * Scoped to the panel on purpose. The column picker's checkbox for a column
   * carries the SAME accessible name as that column's own filter, so once the
   * picker is open an unscoped `getByLabelText` matches both and fails as
   * "found multiple elements" rather than as anything about the filter.
   */
  const panel = () => screen.getByRole('group', { name: /^filters$/i })

  it('shows a column filter when the column is turned on, and hides it again', async () => {
    const user = userEvent.setup({ delay: null })   // never the default: it is per-keystroke
    render(<AdminInventoryPage />)
    await act(async () => { await Promise.resolve() })

    expect(within(panel()).queryByLabelText('Notes')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /^columns$/i }))
    const picker = await screen.findByRole('group', { name: /column visibility/i })
    await user.click(within(picker).getByRole('checkbox', { name: 'Notes' }))
    expect(within(panel()).getByLabelText('Notes')).toBeInTheDocument()

    await user.click(within(picker).getByRole('checkbox', { name: 'Notes' }))
    expect(within(panel()).queryByLabelText('Notes')).not.toBeInTheDocument()
  })

  it('sends a generic filter triple for a column that has no named param', async () => {
    const user = userEvent.setup({ delay: null })
    render(<AdminInventoryPage />)
    await act(async () => { await Promise.resolve() })

    await user.click(screen.getByRole('button', { name: /^columns$/i }))
    const picker = await screen.findByRole('group', { name: /column visibility/i })
    await user.click(within(picker).getByRole('checkbox', { name: 'Notes' }))
    await user.type(within(panel()).getByLabelText('Notes'), 'foil')

    await waitFor(() =>
      expect(getMock).toHaveBeenLastCalledWith(
        '/inventory/search',
        expect.objectContaining({ filter: ['notes:contains:foil'] }),
      ),
    )
  })

  it('keeps sending the named param for a filter that has one', async () => {
    // T3 left four named parameters hand-written on the backend because each
    // does something a field comparison cannot. Rewriting them as `filter=`
    // would silently narrow what they match.
    render(<AdminInventoryPage />)
    await act(async () => { await Promise.resolve() })

    fireEvent.change(within(panel()).getByLabelText('Status'), { target: { value: 'available' } })

    await waitFor(() =>
      expect(getMock).toHaveBeenLastCalledWith(
        '/inventory/search',
        expect.objectContaining({ status: 'available' }),
      ),
    )
    expect(getMock).not.toHaveBeenCalledWith(
      '/inventory/search',
      expect.objectContaining({ filter: expect.arrayContaining(['status:eq:available']) }),
    )
  })

  it('offers a Min and a Max box for a money column, neither of them type=number', async () => {
    // A native number input refuses the comma in `1,300`, which makes the
    // owner's input un-typeable rather than correct. CLAUDE.md, "MONEY INPUT".
    const user = userEvent.setup({ delay: null })
    render(<AdminInventoryPage />)
    await act(async () => { await Promise.resolve() })

    const min = within(panel()).getByLabelText('Price Paid Min')
    expect(min).toHaveAttribute('type', 'text')
    expect(within(panel()).getByLabelText('Price Paid Max')).toHaveAttribute('type', 'text')

    await user.type(min, '1,300')
    await waitFor(() =>
      expect(getMock).toHaveBeenLastCalledWith(
        '/inventory/search',
        expect.objectContaining({ filter: ['cost_basis:gte:1300'] }),
      ),
    )
  })

  it('renders every filter control with vault-field', async () => {
    // The admin theme is dark. An unstyled <select> inherits the theme's light
    // green text over the browser's white default — unreadable, and exactly how
    // the Slabs page shipped.
    render(<AdminInventoryPage />)
    await act(async () => { await Promise.resolve() })
    fireEvent.click(screen.getByRole('button', { name: /show all filters/i }))

    const controls = within(panel()).getAllByRole(
      'combobox', { hidden: true },
    ).concat(within(panel()).getAllByRole('textbox', { hidden: true }))
    expect(controls.length).toBeGreaterThan(10)
    for (const control of controls) {
      expect(control.className, `${control.getAttribute('aria-label')} has no vault-field`)
        .toContain('vault-field')
    }
  })
})

describe('AdminInventoryPage — set filter is a combobox over the whole catalog (T8)', () => {
  // The owner's ask, and the reason this list is NOT built from inventory
  // facets: "so we can double check if there is a set in the catalog we have no
  // cards of." A set with zero owned cards has to be pickable, which means the
  // options come from GET /admin/catalog/sets, not from the rows on screen.
  const CATALOG_SETS = [
    { set_id: 'en:base1', set_name: 'Base Set', language: 'EN', card_count: 102, owned_count: 2 },
    { set_id: 'ja:base1', set_name: 'Base Set', language: 'JP', card_count: 102, owned_count: 0 },
    { set_id: 'en:sv1', set_name: 'Scarlet & Violet', language: 'EN', card_count: 258, owned_count: 0 },
  ]

  beforeEach(() => {
    window.localStorage.clear()
    getMock.mockReset()
    postMock.mockReset()
    putMock.mockReset()
    putMock.mockResolvedValue({})
    getMock.mockImplementation((path: string) => {
      if (path === '/locations') return Promise.resolve([{ value: 'glass', label: 'Glass' }])
      if (path === '/catalog/sets') return Promise.resolve(CATALOG_SETS)
      if (path === '/inventory/search') {
        return Promise.resolve({
          items: [{
            item_id: 'item-1', kind: 'raw', display_name: 'Pikachu',
            location: 'glass', status: 'available', needs_review: false,
          }],
          total: 1,
        })
      }
      return Promise.resolve(null)
    })
  })

  /** The Set filter has no column to follow, so it lives behind the escape hatch. */
  async function openSetFilter() {
    render(<AdminInventoryPage />)
    await act(async () => { await Promise.resolve() })
    fireEvent.click(screen.getByRole('button', { name: /show all filters/i }))
    const filters = screen.getByRole('group', { name: /^filters$/i })
    return within(filters).getByLabelText('Set')
  }

  it('renders a combobox, not a free-text input', async () => {
    const input = await openSetFilter()
    // The old control was a plain <input type="text"> matched as a substring
    // against catalog set_name — no list, no way to see a set we own none of.
    expect(input).toHaveAttribute('role', 'combobox')
  })

  it('lists every catalog set, including ones with nothing owned', async () => {
    const input = await openSetFilter()
    await userEvent.click(input)

    const options = screen.getAllByRole('option').map((o) => o.textContent ?? '')
    expect(options.some((t) => t.includes('Scarlet & Violet'))).toBe(true)
    // The zero-owned set is the whole point; its count is shown, not hidden.
    expect(screen.getByText(/JP.*0 owned/)).toBeInTheDocument()
  })

  it('narrows the list as the admin types', async () => {
    const input = await openSetFilter()
    await userEvent.click(input)
    await userEvent.type(input, 'Scar')

    const options = screen.getAllByRole('option').map((o) => o.textContent ?? '')
    expect(options.some((t) => t.includes('Scarlet & Violet'))).toBe(true)
    expect(options.some((t) => t.includes('Base Set'))).toBe(false)
  })

  it('searches by set_id when a set is picked, never by set_name', async () => {
    // set_name cannot express this selection: "Base Set" names two different
    // sets here (EN and JA), and a substring match would return both.
    const input = await openSetFilter()
    await userEvent.click(input)

    const jpOption = screen
      .getAllByRole('option')
      .find((o) => o.textContent?.includes('Base Set') && o.textContent?.includes('JP'))!
    await userEvent.click(jpOption)

    await waitFor(() =>
      expect(getMock).toHaveBeenLastCalledWith(
        '/inventory/search',
        expect.objectContaining({ set_id: 'ja:base1' }),
      ),
    )
    expect(getMock).not.toHaveBeenCalledWith(
      '/inventory/search',
      expect.objectContaining({ set_name: expect.anything() }),
    )
  })

  it('still renders the page when the set list comes back malformed', async () => {
    // The set filter is one optional control on a page that does inventory ops.
    // A 200 carrying something other than an array — an error envelope, a
    // proxy's HTML, an older backend with no such route — must not reach
    // `.map()` during render and take the whole table down with it.
    getMock.mockImplementation((path: string) => {
      if (path === '/locations') return Promise.resolve([{ value: 'glass', label: 'Glass' }])
      if (path === '/catalog/sets') return Promise.resolve({ detail: 'Not Found' })
      if (path === '/inventory/search') {
        return Promise.resolve({
          items: [{ item_id: 'item-1', kind: 'raw', display_name: 'Pikachu', status: 'available' }],
          total: 1,
        })
      }
      return Promise.resolve(null)
    })

    render(<AdminInventoryPage />)
    await act(async () => { await Promise.resolve() })

    expect(screen.getByText('Pikachu')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /show all filters/i }))
    expect(screen.getByLabelText('Set')).toBeInTheDocument()
  })

  it('fetches the set list once, not on every keystroke', async () => {
    // ~400 sets are fetched up front and narrowed in the browser, mirroring the
    // public filter panel. Refetching per keystroke would put a full inventory
    // + catalog read behind every letter typed.
    const input = await openSetFilter()
    await userEvent.click(input)
    await userEvent.type(input, 'Base')

    const setCalls = getMock.mock.calls.filter((c) => c[0] === '/catalog/sets')
    expect(setCalls).toHaveLength(1)
  })
})

// ===========================================================================
// RFC 0010 T5 — an edit in the detail modal patches the row, it does not refetch
// ===========================================================================
//
// The owner's report has two halves and one cause: the edited value did not
// appear until the modal was closed and reopened, and closing it "often resets
// you to the top of the menu". The second half is the whole-list refetch that
// `onUpdated` triggered — it replaces the array, re-mounts the table, and
// throws away the scroll position of an admin who had scrolled well down.
//
// Scroll position is not observable in jsdom, so the fix is expressed as the
// thing that CAUSED it: the list request must not fire again.
describe('AdminInventoryPage — a modal edit patches one row (RFC 0010 T5)', () => {
  /** Every list request the page has made. */
  const searchCalls = () => getMock.mock.calls.filter(([p]) => p === '/inventory/search')

  beforeEach(() => {
    getMock.mockReset()
    postMock.mockReset()
    putMock.mockReset()
    postMock.mockResolvedValue({})
    putMock.mockResolvedValue({})
    getMock.mockImplementation((path: string) => {
      if (path === '/locations') {
        return Promise.resolve([
          { value: 'glass', label: 'Glass' },
          { value: 'custom_shelf', label: 'Custom Shelf' },
        ])
      }
      if (path === '/inventory/search') {
        return Promise.resolve({
          items: [{
            item_id: 'item-1', kind: 'raw', display_name: 'Pikachu',
            location: 'glass', status: 'available',
          }],
          total: 1,
        })
      }
      // `null`, not `{}` — CardDetailModal mounts PriceChart, which reads
      // `chartData.points` and takes the whole tree down on an object with no
      // `points` key. `null` is its real "no data yet" shape.
      return Promise.resolve(null)
    })
  })

  /** Open the modal on Pikachu and move its location to Custom Shelf. */
  async function editLocationInModal() {
    render(<AdminInventoryPage />)
    await act(async () => { await Promise.resolve() })

    fireEvent.click(screen.getByText('Pikachu'))
    const modal = await screen.findByRole('dialog', { name: /details for/i })

    fireEvent.click(within(modal).getByLabelText('Edit Location'))
    fireEvent.change(within(modal).getByRole('combobox'), {
      target: { value: 'custom_shelf' },
    })
    putMock.mockResolvedValueOnce({
      item_id: 'item-1', kind: 'raw', display_name: 'Pikachu',
      location: 'custom_shelf', status: 'available',
    })
    fireEvent.click(within(modal).getByLabelText('Save'))
    return modal
  }

  it('does not refetch the whole list after an edit', async () => {
    await editLocationInModal()

    await waitFor(() => expect(putMock).toHaveBeenCalled())
    // Flush anything a refetch would have queued before counting.
    await act(async () => { await Promise.resolve() })
    await act(async () => { await Promise.resolve() })
    expect(searchCalls()).toHaveLength(1)
  })

  it('shows the new value in the list row without closing the modal', async () => {
    await editLocationInModal()

    // Scoped to the TABLE: the modal is still open and its header also says
    // "Pikachu", so an unscoped lookup is ambiguous rather than wrong.
    await waitFor(() => {
      const row = within(screen.getByRole('table')).getByText('Pikachu').closest('tr')!
      expect(within(row).getByText('custom_shelf')).toBeInTheDocument()
    })
  })
})
