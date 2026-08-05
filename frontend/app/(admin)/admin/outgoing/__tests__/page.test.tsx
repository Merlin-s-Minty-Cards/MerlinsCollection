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
})
