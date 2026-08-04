import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import AdminShowPrepPage from '../page'

const getMock = vi.fn()
const postMock = vi.fn()
const putMock = vi.fn()
// A stable object identity is required: the page's fetch callbacks depend on
// `api` in their useEffect/useCallback deps, and a new object every render
// (as a naive factory would produce) causes an infinite fetch loop.
const mockApi = {
  get: getMock,
  post: postMock,
  del: vi.fn(),
  put: putMock,
  patch: vi.fn(),
  isAuthenticated: true,
  isLoading: false,
}

vi.mock('@/lib/admin-api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/admin-api')>('@/lib/admin-api')
  return {
    ...actual,
    useAdminApi: () => mockApi,
  }
})

const mispricedItem = {
  item_id: 'item-1',
  name: 'Pikachu VMAX',
  location: 'binder-a',
  cost_basis: '10.00',
  current_market_value: '30.00',
  sticker_price: '25.00',
  tcg_url: null,
  delta_pct: '200',
}

describe('AdminShowPrepPage inline sticker editing', () => {
  beforeEach(() => {
    getMock.mockReset()
    postMock.mockReset()
    putMock.mockReset()
    putMock.mockResolvedValue({})
    getMock.mockImplementation((path: string) => {
      if (path === '/show-prep/mispriced') {
        return Promise.resolve({ items: [mispricedItem], total_flagged: 1 })
      }
      if (path === '/show-prep/location-summary') {
        return Promise.resolve({ locations: { 'binder-a': 1 }, total: 1 })
      }
      if (path === '/locations') {
        return Promise.resolve([{ value: 'binder-a', label: 'Binder A' }])
      }
      return Promise.resolve({})
    })
  })

  it('saves an edited sticker price via PUT and refetches the mispriced list', async () => {
    render(<AdminShowPrepPage />)

    await act(async () => {
      await Promise.resolve()
    })

    const stickerDisplay = await screen.findByRole('button', { name: /edit sticker price for pikachu vmax/i })
    fireEvent.click(stickerDisplay)

    const input = screen.getByPlaceholderText('0.00')
    fireEvent.change(input, { target: { value: '19.99' } })

    const mispricedCallsBefore = getMock.mock.calls.filter((c) => c[0] === '/show-prep/mispriced').length

    await act(async () => {
      fireEvent.keyDown(input, { key: 'Enter' })
      await Promise.resolve()
    })

    expect(putMock).toHaveBeenCalledWith('/inventory/item-1', { sticker_price: '19.99' })

    const mispricedCallsAfter = getMock.mock.calls.filter((c) => c[0] === '/show-prep/mispriced').length
    expect(mispricedCallsAfter).toBeGreaterThan(mispricedCallsBefore)
  })
})
