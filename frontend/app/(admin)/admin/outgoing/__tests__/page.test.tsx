import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, act, waitFor, within } from '@testing-library/react'
import AdminPrepQueuePage from '../page'

const getMock = vi.fn()
const putMock = vi.fn()
const mockApi = {
  get: getMock, post: vi.fn(), put: putMock, patch: vi.fn(), del: vi.fn(),
  isAuthenticated: true, isLoading: false,
}

vi.mock('@/lib/admin-api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/admin-api')>('@/lib/admin-api')
  return { ...actual, useAdminApi: () => mockApi }
})

describe('AdminPrepQueuePage bulk pricing', () => {
  beforeEach(() => {
    getMock.mockReset()
    putMock.mockReset()
    putMock.mockResolvedValue({})
    getMock.mockImplementation((path: string) => {
      if (path === '/inventory/search') {
        return Promise.resolve({
          items: [
            { item_id: 'item-1', display_name: 'Pikachu', status: 'available', location: 'binder' },
            { item_id: 'item-2', display_name: 'Charizard', status: 'available', location: 'binder' },
          ],
        })
      }
      if (path === '/locations') return Promise.resolve([{ value: 'binder', label: 'Binder' }])
      return Promise.resolve({})
    })
  })

  it('bulk-applies a sticker price to all selected items', async () => {
    render(<AdminPrepQueuePage />)
    await act(async () => { await Promise.resolve() })

    fireEvent.click(screen.getByLabelText(/select all/i))

    const priceInput = screen.getByPlaceholderText('0.00')
    fireEvent.change(priceInput, { target: { value: '9.99' } })
    fireEvent.click(screen.getByRole('button', { name: /set sticker/i }))

    await waitFor(() => expect(putMock).toHaveBeenCalledWith('/inventory/item-1', { sticker_price: '9.99' }))
    expect(putMock).toHaveBeenCalledWith('/inventory/item-2', { sticker_price: '9.99' })
  })

  it('rejects a negative bulk sticker price without applying it to any item (finding 5)', async () => {
    // Unlike Show Prep's bulk/single sticker editors, the Prep Queue bulk
    // apply had no min/NaN guard — a negative value would silently apply to
    // every selected item and drop them all from the queue (its whole
    // criterion is "no sticker price yet").
    render(<AdminPrepQueuePage />)
    await act(async () => { await Promise.resolve() })

    fireEvent.click(screen.getByLabelText(/select all/i))

    const priceInput = screen.getByPlaceholderText('0.00')
    fireEvent.change(priceInput, { target: { value: '-5' } })
    fireEvent.click(screen.getByRole('button', { name: /set sticker/i }))

    await act(async () => { await Promise.resolve() })
    expect(putMock).not.toHaveBeenCalled()
  })

  it('the bulk sticker price input flags a negative value inline', async () => {
    // This used to assert min="0" on a native number input. RFC 0010 T1 made
    // the field a text input so `1,300` can be typed at all, which means the
    // browser no longer enforces the bound — `parseMoney` does, by rejecting a
    // negative outright, and the operator is told rather than silently ignored.
    render(<AdminPrepQueuePage />)
    await act(async () => { await Promise.resolve() })

    fireEvent.click(screen.getByLabelText(/select all/i))
    fireEvent.change(screen.getByPlaceholderText('0.00'), { target: { value: '-5' } })
    expect(screen.getByRole('alert')).toBeInTheDocument()
  })
})

describe('AdminPrepQueuePage inline location edit no-op guard', () => {
  beforeEach(() => {
    getMock.mockReset()
    putMock.mockReset()
    putMock.mockResolvedValue({})
    getMock.mockImplementation((path: string) => {
      if (path === '/inventory/search') {
        // A null-location item — Buy/Trade can leave location unset by
        // design, and the inline editor no longer has a "— None —" option
        // to explicitly re-select once location became required (finding 6).
        return Promise.resolve({
          items: [{ item_id: 'item-1', display_name: 'Pikachu', status: 'available', location: null }],
        })
      }
      if (path === '/locations') return Promise.resolve([{ value: 'binder', label: 'Binder' }])
      return Promise.resolve({})
    })
  })

  it('does not PUT when the location editor is opened and blurred without a change', async () => {
    render(<AdminPrepQueuePage />)
    await act(async () => { await Promise.resolve() })

    fireEvent.click(screen.getByLabelText(/edit location for pikachu/i))
    const select = screen.getByLabelText(/edit location for pikachu/i, { selector: 'select' })
    fireEvent.blur(select)

    await act(async () => { await Promise.resolve() })
    expect(putMock).not.toHaveBeenCalled()
  })
})

// ===========================================================================
// T11 — "Send to Triage" reaches this page too
// ===========================================================================
//
// The second half of the shared-modal pin (see the twin in
// app/(admin)/admin/inventory/__tests__/page.test.tsx). Asserting the button
// from ONE page proves only that CardDetailModal renders it; asserting it from
// two proves the modal is genuinely the shared insertion point T11 is betting
// on. The Prep Queue is the sharper of the two cases — its route is still
// /admin/outgoing and it is easy to forget it mounts this modal at all.
describe('AdminPrepQueuePage — Send to Triage (RFC 0008 T11)', () => {
  beforeEach(() => {
    getMock.mockReset()
    putMock.mockReset()
    putMock.mockResolvedValue({})
    getMock.mockImplementation((path: string) => {
      if (path === '/inventory/search') {
        return Promise.resolve({
          items: [{
            item_id: 'item-1', kind: 'raw', display_name: 'Pikachu',
            status: 'available', location: 'binder', needs_review: false,
          }],
        })
      }
      if (path === '/locations') return Promise.resolve([{ value: 'binder', label: 'Binder' }])
      // `null`, not `{}` — this block opens CardDetailModal, whose PriceChart
      // reads `chartData.points` and crashes the tree on an object with no
      // `points` key. `null` is its real "no data yet" shape.
      return Promise.resolve(null)
    })
  })

  it('reaches the shared detail modal opened from the Prep Queue', async () => {
    render(<AdminPrepQueuePage />)
    await act(async () => { await Promise.resolve() })

    fireEvent.click(screen.getByText('Pikachu'))

    const modal = await screen.findByRole('dialog', { name: /details for/i })
    expect(within(modal).getByRole('button', { name: /send to triage/i })).toBeInTheDocument()
  })

  it('flags a row straight from the queue table', async () => {
    render(<AdminPrepQueuePage />)
    await act(async () => { await Promise.resolve() })

    fireEvent.click(await screen.findByRole('button', { name: /send pikachu to triage/i }))

    await waitFor(() =>
      expect(putMock).toHaveBeenCalledWith('/inventory/item-1', { needs_review: true }),
    )
  })
})

// ---------------------------------------------------------------------------
// RFC 0010 T1 — money fields accept what a human types
// ---------------------------------------------------------------------------

describe('AdminPrepQueuePage money input', () => {
  beforeEach(() => {
    getMock.mockReset()
    putMock.mockReset()
    putMock.mockResolvedValue({})
    getMock.mockImplementation((path: string) => {
      if (path === '/inventory/search') {
        return Promise.resolve({
          items: [
            { item_id: 'item-1', display_name: 'Pikachu', status: 'available', location: 'binder' },
          ],
        })
      }
      if (path === '/locations') return Promise.resolve([{ value: 'binder', label: 'Binder' }])
      return Promise.resolve({})
    })
  })

  it('bulk sticker sends the PARSED number, never the raw typed string', async () => {
    // The defect this names: the guard reads parseFloat(value) and the PUT
    // sends `value`. Harmless only while the input is type="number".
    render(<AdminPrepQueuePage />)
    await act(async () => { await Promise.resolve() })

    fireEvent.click(screen.getByLabelText(/select all/i))
    fireEvent.change(screen.getByPlaceholderText('0.00'), { target: { value: '1,300' } })
    fireEvent.click(screen.getByRole('button', { name: /set sticker/i }))

    await waitFor(() => expect(putMock).toHaveBeenCalledWith('/inventory/item-1', { sticker_price: '1300' }))
  })

  it('does not apply a bulk sticker price it cannot read', async () => {
    render(<AdminPrepQueuePage />)
    await act(async () => { await Promise.resolve() })

    fireEvent.click(screen.getByLabelText(/select all/i))
    fireEvent.change(screen.getByPlaceholderText('0.00'), { target: { value: '1,30' } })
    fireEvent.click(screen.getByRole('button', { name: /set sticker/i }))

    await act(async () => { await Promise.resolve() })
    expect(putMock).not.toHaveBeenCalled()
    expect(screen.getByRole('alert')).toBeInTheDocument()
  })

  it('inline sticker edit commits a comma-grouped amount as its parsed value', async () => {
    render(<AdminPrepQueuePage />)
    await act(async () => { await Promise.resolve() })

    fireEvent.click(screen.getByLabelText(/edit sticker price for/i))
    const input = screen.getByRole('textbox')
    fireEvent.change(input, { target: { value: '1,300' } })
    await act(async () => { fireEvent.keyDown(input, { key: 'Enter' }) })

    await waitFor(() => expect(putMock).toHaveBeenCalledWith('/inventory/item-1', { sticker_price: '1300' }))
  })
})

// ===========================================================================
// RFC 0010 T5 — a modal edit patches the row, and a priced row still leaves
// ===========================================================================

describe('AdminPrepQueuePage — pricing from the detail modal (RFC 0010 T5)', () => {
  beforeEach(() => {
    getMock.mockReset()
    putMock.mockReset()
    putMock.mockResolvedValue({})
    getMock.mockImplementation((path: string) => {
      if (path === '/inventory/search') {
        return Promise.resolve({
          items: [{
            item_id: 'item-1', kind: 'raw', display_name: 'Pikachu',
            status: 'available', location: 'binder', sticker_price: null,
          }],
        })
      }
      if (path === '/locations') return Promise.resolve([{ value: 'binder', label: 'Binder' }])
      // `null` — CardDetailModal's PriceChart reads `chartData.points`.
      return Promise.resolve(null)
    })
  })

  it('removes a row priced through the modal, the same as the inline editor does', async () => {
    // "Priced → removed" is this queue's documented behaviour and its whole
    // criterion is "no sticker price yet". The inline cell already does it; an
    // edit made through the shared modal must not leave a priced card sitting
    // in a queue of unpriced ones.
    render(<AdminPrepQueuePage />)
    await act(async () => { await Promise.resolve() })

    fireEvent.click(screen.getByText('Pikachu'))
    const modal = await screen.findByRole('dialog', { name: /details for/i })

    fireEvent.click(within(modal).getByLabelText('Edit Sticker Price'))
    fireEvent.change(within(modal).getByRole('spinbutton'), { target: { value: '9.99' } })
    putMock.mockResolvedValueOnce({
      item_id: 'item-1', kind: 'raw', display_name: 'Pikachu',
      status: 'available', location: 'binder', sticker_price: '9.99',
    })
    fireEvent.click(within(modal).getByLabelText('Save'))

    // The queue's own empty message, not a row count: a refetch blanks the
    // table for a tick while `loading` is true, so counting rows can read zero
    // for the wrong reason and pass against the unfixed code.
    expect(
      await screen.findByText(/no items awaiting sticker prices/i),
    ).toBeInTheDocument()
  })
})

// ===========================================================================
// RFC 0010 T7 — the queue filters and sorts by location
// ===========================================================================
//
// Owner report: "Prep queue is great but have an option to sort by location as
// we often just price glass in certain cases." The FILTER is the primary
// control that report is asking for; sorting is the cheap extra.
//
// Everything here is frontend wiring — `location`, `sort=location_asc` and the
// `cost_basis` / `current_market_value` sort fields all already exist on
// GET /inventory/search.

describe('AdminPrepQueuePage — location filter and sorting (RFC 0010 T7)', () => {
  const searchCalls = () => getMock.mock.calls.filter((c) => c[0] === '/inventory/search')
  const lastSearchParams = () =>
    (searchCalls().at(-1)?.[1] ?? {}) as Record<string, string>

  beforeEach(() => {
    getMock.mockReset()
    putMock.mockReset()
    putMock.mockResolvedValue({})
    getMock.mockImplementation((path: string, params?: Record<string, string>) => {
      if (path === '/inventory/search') {
        // Server-side filtering, mirrored here: the count and the estimated
        // value are derived from whatever the endpoint returns, so the mock has
        // to actually narrow or test 6 proves nothing.
        const all = [
          {
            item_id: 'item-1', display_name: 'Pikachu', status: 'available',
            location: 'glass', cost_basis: '4.00', current_market_value: '10.00',
          },
          {
            item_id: 'item-2', display_name: 'Charizard', status: 'available',
            location: 'vault_b', cost_basis: '9.00', current_market_value: '25.00',
          },
        ]
        const loc = params?.location
        return Promise.resolve({ items: loc ? all.filter((i) => i.location === loc) : all })
      }
      // `Vault B` is deliberately NOT in lib/constants' LOCATION_OPTIONS
      // fallback, so a hardcoded list cannot produce it.
      if (path === '/locations') {
        return Promise.resolve([
          { value: 'glass', label: 'Glass' },
          { value: 'vault_b', label: 'Vault B' },
        ])
      }
      return Promise.resolve(null)
    })
  })

  it('sends location=<value> without dropping the queue\'s own criterion', async () => {
    render(<AdminPrepQueuePage />)
    await act(async () => { await Promise.resolve() })

    fireEvent.change(screen.getByLabelText(/filter by location/i), {
      target: { value: 'glass' },
    })

    await waitFor(() =>
      expect(lastSearchParams()).toMatchObject({
        location: 'glass',
        status: 'available',
        missing_sticker: 'true',
      }),
    )
  })

  it('omits the location param while "All locations" is selected', async () => {
    render(<AdminPrepQueuePage />)
    await act(async () => { await Promise.resolve() })

    expect(searchCalls()).toHaveLength(1)
    expect(lastSearchParams()).not.toHaveProperty('location')

    const select = screen.getByLabelText(/filter by location/i)
    fireEvent.change(select, { target: { value: 'glass' } })
    await waitFor(() => expect(lastSearchParams()).toHaveProperty('location', 'glass'))

    // Back to All — the param must go away, not be sent as an empty string,
    // which the backend would treat as a location literally named "".
    fireEvent.change(select, { target: { value: '' } })
    await waitFor(() => expect(lastSearchParams()).not.toHaveProperty('location'))
  })

  it('takes its location options from useLocations(), not a hardcoded list', async () => {
    render(<AdminPrepQueuePage />)
    await act(async () => { await Promise.resolve() })

    const select = screen.getByLabelText(/filter by location/i)
    expect(within(select).getByRole('option', { name: /all locations/i })).toBeInTheDocument()
    expect(within(select).getByRole('option', { name: 'Vault B' })).toBeInTheDocument()
  })

  it('sorts by location ascending on the first header click and descending on the second', async () => {
    render(<AdminPrepQueuePage />)
    await act(async () => { await Promise.resolve() })

    const header = screen.getByRole('columnheader', { name: /location/i })

    fireEvent.click(header)
    await waitFor(() => expect(lastSearchParams()).toHaveProperty('sort', 'location_asc'))

    fireEvent.click(header)
    await waitFor(() => expect(lastSearchParams()).toHaveProperty('sort', 'location_desc'))
  })

  it('sorts by cost and market using the backend\'s own field names', async () => {
    // A table with exactly one sortable column reads as broken, and the backend
    // already supports both — but only under these exact names, because
    // _sort_admin_results splits on the LAST underscore.
    render(<AdminPrepQueuePage />)
    await act(async () => { await Promise.resolve() })

    fireEvent.click(screen.getByRole('columnheader', { name: /^cost$/i }))
    await waitFor(() => expect(lastSearchParams()).toHaveProperty('sort', 'cost_basis_asc'))

    fireEvent.click(screen.getByRole('columnheader', { name: /^market$/i }))
    await waitFor(() =>
      expect(lastSearchParams()).toHaveProperty('sort', 'current_market_value_asc'),
    )
  })

  it('shows the sort indicator on the active column only', async () => {
    render(<AdminPrepQueuePage />)
    await act(async () => { await Promise.resolve() })

    const locationHeader = screen.getByRole('columnheader', { name: /location/i })
    const costHeader = screen.getByRole('columnheader', { name: /^cost$/i })

    fireEvent.click(locationHeader)

    await waitFor(() =>
      expect(locationHeader.querySelector('.lucide-chevron-up')).not.toBeNull(),
    )
    expect(costHeader.querySelector('.lucide-chevron-up')).toBeNull()
    expect(costHeader.querySelector('.lucide-chevrons-up-down')).not.toBeNull()

    fireEvent.click(locationHeader)
    await waitFor(() =>
      expect(locationHeader.querySelector('.lucide-chevron-down')).not.toBeNull(),
    )
  })

  it('names the active location in the header counts, so a filtered count cannot be read as the whole queue', async () => {
    // Both figures are scoped to their own summary card. A bare
    // getByText('$10.00') matches the Est. value card AND the surviving row's
    // Market cell once the filter narrows to one item.
    const panelFor = (label: RegExp) => screen.getByText(label).parentElement as HTMLElement

    render(<AdminPrepQueuePage />)
    await act(async () => { await Promise.resolve() })

    expect(within(panelFor(/^in queue$/i)).getByText('2')).toBeInTheDocument()
    expect(within(panelFor(/^est\. value$/i)).getByText('$35.00')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText(/filter by location/i), {
      target: { value: 'glass' },
    })

    expect(await screen.findByText(/^in queue \(glass\)$/i)).toBeInTheDocument()
    expect(within(panelFor(/^in queue \(glass\)$/i)).getByText('1')).toBeInTheDocument()
    expect(within(panelFor(/^est\. value \(glass\)$/i)).getByText('$10.00')).toBeInTheDocument()
  })

  it('renders the location filter with vault-field', async () => {
    // The admin theme is dark with light-green text, so an unstyled <select>
    // renders light-green-on-white (CLAUDE.md).
    render(<AdminPrepQueuePage />)
    await act(async () => { await Promise.resolve() })

    expect(screen.getByLabelText(/filter by location/i).className).toContain('vault-field')
  })

  it('removes just the priced row without refetching, so the active filter is not reset', async () => {
    render(<AdminPrepQueuePage />)
    await act(async () => { await Promise.resolve() })

    fireEvent.change(screen.getByLabelText(/filter by location/i), {
      target: { value: 'glass' },
    })
    await waitFor(() => expect(lastSearchParams()).toHaveProperty('location', 'glass'))
    const callsBeforePricing = searchCalls().length

    fireEvent.click(screen.getByLabelText(/edit sticker price for pikachu/i))
    const input = screen.getByRole('textbox')
    fireEvent.change(input, { target: { value: '9.99' } })
    await act(async () => { fireEvent.keyDown(input, { key: 'Enter' }) })

    await waitFor(() =>
      expect(putMock).toHaveBeenCalledWith('/inventory/item-1', { sticker_price: '9.99' }),
    )
    expect(
      await screen.findByText(/no items awaiting sticker prices/i),
    ).toBeInTheDocument()
    expect(searchCalls()).toHaveLength(callsBeforePricing)
  })
})

// ===========================================================================
// RFC 0010 T16 — a card the catalog does not carry, on the sticker screen
// ===========================================================================
//
// Prep Queue is where a shelf gets priced, and after T7 it can be narrowed to
// one location. An unlinked row has no market figure to compare a sticker
// against and never will — no sync reaches it — so the row has to say so.
// Silence here reads as "the price just hasn't synced yet", which is the one
// wrong conclusion available.

describe('AdminPrepQueuePage hand-valued rows', () => {
  beforeEach(() => {
    getMock.mockReset()
    putMock.mockReset()
    putMock.mockResolvedValue({})
    getMock.mockImplementation((path: string) => {
      if (path === '/inventory/search') {
        return Promise.resolve({
          items: [
            {
              item_id: 'linked-1', card_id: 'sv1-25', display_name: 'Pikachu',
              status: 'available', location: 'glass',
              current_market_value: '10.00',
            },
            {
              item_id: 'unlinked-1', card_id: null, display_name: 'Mega Brave promo',
              status: 'available', location: 'glass',
              current_market_value: '23.20',
            },
          ],
        })
      }
      if (path === '/locations') return Promise.resolve([{ value: 'glass', label: 'Glass' }])
      return Promise.resolve({})
    })
  })

  it('marks a row with no catalog link as hand-valued, and leaves a linked one alone', async () => {
    render(<AdminPrepQueuePage />)
    await act(async () => { await Promise.resolve() })

    const rowFor = (name: RegExp) => screen.getByText(name).closest('tr')!
    expect(within(rowFor(/Mega Brave promo/)).getByText(/hand-valued/i)).toBeInTheDocument()
    expect(within(rowFor(/Pikachu/)).queryByText(/hand-valued/i)).not.toBeInTheDocument()
  })
})
