import { describe, it, expect, vi, beforeEach, afterEach, beforeAll, afterAll } from 'vitest'
import { render, screen, fireEvent, act, waitFor } from '@testing-library/react'
import AdminSellPage from '../page'
import { pinTimeZone, PACIFIC } from '@/lib/__tests__/_timezone'

const getMock = vi.fn()
const postMock = vi.fn()

const mockApi = {
  get: getMock,
  post: postMock,
  put: vi.fn(),
  patch: vi.fn(),
  del: vi.fn(),
  isAuthenticated: true,
  isLoading: false,
}

vi.mock('@/lib/admin-api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/admin-api')>('@/lib/admin-api')
  return { ...actual, useAdminApi: () => mockApi }
})

describe('AdminSellPage ownership indicator', () => {
  beforeEach(() => {
    getMock.mockReset()
    postMock.mockReset()
    postMock.mockResolvedValue({ sell_id: 'sell-1', status: 'draft' })
  })

  it('shows a Cosigned badge on a consigned item in the search results', async () => {
    getMock.mockImplementation((path: string) => {
      if (path === '/inventory/search') {
        return Promise.resolve({
          items: [{
            item_id: 'item-1',
            card_id: 'sv1-25',
            display_name: 'Pikachu',
            condition: 'NM',
            current_market_value: '30.00',
            cost_basis: '10.00',
            sticker_price: null,
            status: 'available',
            consignment: { consignor_id: 'cons-1', split_percent: '0.5', paid_out: false },
          }],
          total: 1,
        })
      }
      return Promise.resolve({})
    })

    render(<AdminSellPage />)
    await act(async () => { await Promise.resolve() })

    const searchInput = screen.getByPlaceholderText(/search/i)
    fireEvent.change(searchInput, { target: { value: 'Pikachu' } })
    await waitFor(() => expect(getMock).toHaveBeenCalledWith('/inventory/search', expect.anything()))

    expect(await screen.findByText('Cosigned')).toBeInTheDocument()
  })

  it('shows an Owned badge on a non-consigned item', async () => {
    getMock.mockImplementation((path: string) => {
      if (path === '/inventory/search') {
        return Promise.resolve({
          items: [{
            item_id: 'item-2',
            card_id: 'sv1-4',
            display_name: 'Charizard',
            condition: 'NM',
            current_market_value: '80.00',
            cost_basis: '40.00',
            sticker_price: null,
            status: 'available',
            consignment: null,
          }],
          total: 1,
        })
      }
      return Promise.resolve({})
    })

    render(<AdminSellPage />)
    await act(async () => { await Promise.resolve() })

    const searchInput = screen.getByPlaceholderText(/search/i)
    fireEvent.change(searchInput, { target: { value: 'Charizard' } })
    await waitFor(() => expect(getMock).toHaveBeenCalledWith('/inventory/search', expect.anything()))

    expect(await screen.findByText('Owned')).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// RFC 0010 T1 — money fields accept what a human types
// ---------------------------------------------------------------------------

describe('AdminSellPage money input', () => {
  beforeEach(() => {
    getMock.mockReset()
    postMock.mockReset()
    postMock.mockResolvedValue({ sell_id: 'sell-1', status: 'draft' })
    getMock.mockImplementation((path: string) => {
      if (path === '/inventory/search') {
        return Promise.resolve({
          items: [{
            item_id: 'item-1',
            card_id: 'sv1-25',
            display_name: 'Pikachu',
            condition: 'NM',
            current_market_value: '30.00',
            cost_basis: '10.00',
            sticker_price: null,
            status: 'available',
          }],
          total: 1,
        })
      }
      return Promise.resolve({})
    })
  })

  async function addPikachuToCart() {
    render(<AdminSellPage />)
    await act(async () => { await Promise.resolve() })
    fireEvent.change(screen.getByPlaceholderText(/search/i), { target: { value: 'Pikachu' } })
    fireEvent.click(await screen.findByText('Pikachu'))
    return await screen.findByLabelText(/agreed price/i)
  }

  it('totals 1,300 as $1300.00, not $1.00', async () => {
    const priceInput = await addPikachuToCart()
    fireEvent.change(priceInput, { target: { value: '1,300' } })
    // parseFloat('1,300') is 1 and never NaN, so the wrong total looks fine.
    expect(await screen.findByText('$1300.00')).toBeInTheDocument()
  })

  it('still totals a plain 1300 correctly (regression gate)', async () => {
    const priceInput = await addPikachuToCart()
    fireEvent.change(priceInput, { target: { value: '1300' } })
    expect(await screen.findByText('$1300.00')).toBeInTheDocument()
  })

  it('flags an unreadable agreed price inline', async () => {
    const priceInput = await addPikachuToCart()
    fireEvent.change(priceInput, { target: { value: '1,30' } })
    expect(await screen.findByRole('alert')).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// RFC 0010 T8 — the sale date defaulted to tomorrow after 5pm Pacific
// ---------------------------------------------------------------------------

describe('AdminSellPage default sale date', () => {
  let restoreTz: () => void
  beforeAll(() => { restoreTz = pinTimeZone(PACIFIC) })
  afterAll(() => { restoreTz(); vi.useRealTimers() })

  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-08-11T01:30:00Z')) // 6:30pm Pacific, Aug 10
    getMock.mockReset()
    postMock.mockReset()
    postMock.mockResolvedValue({ sell_id: 'sell-1', status: 'draft' })
    getMock.mockResolvedValue({ items: [], total: 0 })
  })
  afterEach(() => vi.useRealTimers())

  it('defaults to Aug 10 at 6:30pm Pacific, not Aug 11', async () => {
    render(<AdminSellPage />)
    await act(async () => { await Promise.resolve() })

    const date = document.querySelector('input[type="date"]') as HTMLInputElement
    expect(date).not.toBeNull()
    expect(date.value).toBe('2026-08-10')
  })
})
