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
