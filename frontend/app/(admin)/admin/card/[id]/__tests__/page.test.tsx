import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import AdminCardDetailPage from '../page'

const getMock = vi.fn()
// A stable object identity is required: the page's fetch callbacks depend on
// `api` in their useEffect/useCallback deps, and a new object every render
// (as a naive factory would produce) causes an infinite fetch loop — see the
// same note in app/(admin)/admin/show-prep/__tests__/page.test.tsx.
const mockApi = {
  get: getMock,
  post: vi.fn(),
  put: vi.fn(),
  patch: vi.fn(),
  del: vi.fn(),
  isAuthenticated: true,
  isLoading: false,
}

vi.mock('next/navigation', () => ({
  useParams: () => ({ id: 'item-1' }),
  useRouter: () => ({ push: vi.fn(), back: vi.fn() }),
}))

vi.mock('@/lib/admin-api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/admin-api')>('@/lib/admin-api')
  return {
    ...actual,
    useAdminApi: () => mockApi,
  }
})

describe('AdminCardDetailPage consignment fields', () => {
  beforeEach(() => {
    getMock.mockReset()
    getMock.mockImplementation((path: string) => {
      if (path === '/inventory/item-1') {
        return Promise.resolve({
          item_id: 'item-1',
          display_name: 'Pikachu',
          status: 'available',
          cost_basis: '10.00',
          consignment: { consignor_id: 'cons-1', split_percent: '0.5', paid_out: false },
        })
      }
      if (path === '/inventory/item-1/timeline') {
        return Promise.resolve({ events: [] })
      }
      if (path === '/inventory/item-1/price-chart') {
        return Promise.resolve({ points: [], buy_marker: null, timeframe: '1yr', item_id: 'item-1' })
      }
      return Promise.resolve({})
    })
  })

  it('renders the consigner id and split percent from the nested consignment object', async () => {
    render(<AdminCardDetailPage />)

    expect(await screen.findByText('cons-1')).toBeInTheDocument()
    expect(await screen.findByText('50%')).toBeInTheDocument()
  })
})
