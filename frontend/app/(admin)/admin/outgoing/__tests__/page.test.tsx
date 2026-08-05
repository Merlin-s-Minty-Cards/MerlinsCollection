import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, act, waitFor } from '@testing-library/react'
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

  it('the bulk sticker price input rejects negative values at the HTML level too', async () => {
    render(<AdminPrepQueuePage />)
    await act(async () => { await Promise.resolve() })

    fireEvent.click(screen.getByLabelText(/select all/i))
    expect(screen.getByPlaceholderText('0.00')).toHaveAttribute('min', '0')
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
