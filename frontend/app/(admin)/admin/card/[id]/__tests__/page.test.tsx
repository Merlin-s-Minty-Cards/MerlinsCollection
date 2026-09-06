import { describe, it, expect, vi, beforeEach, beforeAll, afterAll } from 'vitest'
import { render, screen } from '@testing-library/react'
import AdminCardDetailPage from '../page'
import { pinTimeZone, PACIFIC } from '@/lib/__tests__/_timezone'

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

// ---------------------------------------------------------------------------
// RFC 0010 T8 — the acquired date rendered a day early
// ---------------------------------------------------------------------------

describe('AdminCardDetailPage dates (RFC 0010 T8)', () => {
  let restoreTz: () => void
  beforeAll(() => { restoreTz = pinTimeZone(PACIFIC) })
  afterAll(() => restoreTz())

  beforeEach(() => {
    getMock.mockReset()
    getMock.mockImplementation((path: string) => {
      if (path === '/inventory/item-1') {
        return Promise.resolve({
          item_id: 'item-1',
          display_name: 'Pikachu',
          status: 'available',
          cost_basis: '10.00',
          acquired_at: '2026-08-10',
        })
      }
      if (path === '/inventory/item-1/timeline') return Promise.resolve({ events: [] })
      if (path === '/inventory/item-1/price-chart') {
        return Promise.resolve({ points: [], buy_marker: null, timeframe: '1yr', item_id: 'item-1' })
      }
      return Promise.resolve({})
    })
  })

  it('renders an acquired_at of 2026-08-10 as Aug 10, not Aug 9', async () => {
    render(<AdminCardDetailPage />)
    expect(await screen.findByText('Aug 10, 2026')).toBeInTheDocument()
    expect(screen.queryByText('Aug 9, 2026')).not.toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// RFC 0023 follow-ups #2/#3 — this page used to hardcode an English-only
// TCGplayer link and render a stored `tcg_url` as an `<a href>` with no
// validation (a `javascript:` value is a stored-XSS sink that fires on one
// click).
// ---------------------------------------------------------------------------

describe('AdminCardDetailPage TCGplayer link', () => {
  beforeEach(() => {
    getMock.mockReset()
  })

  function mockItem(overrides: Record<string, unknown>) {
    getMock.mockImplementation((path: string) => {
      if (path === '/inventory/item-1') {
        return Promise.resolve({
          item_id: 'item-1',
          display_name: 'Pikachu',
          status: 'available',
          cost_basis: '10.00',
          ...overrides,
        })
      }
      if (path === '/inventory/item-1/timeline') return Promise.resolve({ events: [] })
      if (path === '/inventory/item-1/price-chart') {
        return Promise.resolve({ points: [], buy_marker: null, timeframe: '1yr', item_id: 'item-1' })
      }
      return Promise.resolve({})
    })
  }

  it('links directly to a stored tcg_url when one is a real http(s) URL', async () => {
    mockItem({ tcg_url: 'https://www.tcgplayer.com/product/12345', language: 'EN' })
    render(<AdminCardDetailPage />)

    const link = await screen.findByRole('link', { name: /TCGplayer \(stored\)/i })
    expect(link).toHaveAttribute('href', 'https://www.tcgplayer.com/product/12345')
  })

  it('generates a Japan-category search link for a JP item with no stored tcg_url', async () => {
    mockItem({ language: 'JP' })
    render(<AdminCardDetailPage />)

    const link = await screen.findByRole('link', { name: /^TCGplayer$/i })
    expect(link).toHaveAttribute(
      'href',
      'https://www.tcgplayer.com/search/pokemon-japan/product?productLineName=pokemon-japan&q=Pikachu&view=grid',
    )
  })

  it('shows a no-link message, not a link, for a language TCGplayer has no category for', async () => {
    mockItem({ language: 'KO' })
    render(<AdminCardDetailPage />)

    expect(await screen.findByText('No TCGplayer link')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /TCGplayer/i })).not.toBeInTheDocument()
  })

  it('falls back to a generated search link instead of using an unsafe stored tcg_url as href', async () => {
    mockItem({ tcg_url: 'javascript:alert(1)', language: 'EN' })
    render(<AdminCardDetailPage />)

    const link = await screen.findByRole('link', { name: /^TCGplayer$/i })
    expect(link).toHaveAttribute(
      'href',
      'https://www.tcgplayer.com/search/pokemon/product?q=Pikachu&view=grid',
    )
    expect(screen.queryByRole('link', { name: /TCGplayer \(stored\)/i })).not.toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// Set name + card number — the header and the "Card Number"/"Set" DetailRows
// have carried these fields since the page was written, but the endpoint
// never populated them (a raw dump of the stored item, no catalog join),
// so both silently rendered nothing on every single item. Regression test
// for `admin_get_item` now attaching `set_name`/`card_number` from the
// catalog.
// ---------------------------------------------------------------------------

describe('AdminCardDetailPage set name and card number', () => {
  beforeEach(() => {
    getMock.mockReset()
  })

  it('shows the catalog set name and print number once the backend attaches them', async () => {
    getMock.mockImplementation((path: string) => {
      if (path === '/inventory/item-1') {
        return Promise.resolve({
          item_id: 'item-1',
          display_name: 'Pikachu',
          status: 'available',
          cost_basis: '10.00',
          set_name: 'Base Set',
          card_number: '25',
        })
      }
      if (path === '/inventory/item-1/timeline') return Promise.resolve({ events: [] })
      if (path === '/inventory/item-1/price-chart') {
        return Promise.resolve({ points: [], buy_marker: null, timeframe: '1yr', item_id: 'item-1' })
      }
      return Promise.resolve({})
    })

    render(<AdminCardDetailPage />)

    // Rendered in BOTH the header line and the "Set"/"Card Number" DetailRow
    // body — the whole point of the fix, so two matches is the expected,
    // passing shape here, not an ambiguity to work around.
    expect(await screen.findAllByText('Base Set')).toHaveLength(2)
    expect(screen.getByText('#25')).toBeInTheDocument()
    const numberRow = screen.getByText('Card Number').closest('div')
    expect(numberRow).toHaveTextContent('25')
  })

  it('shows the placeholder, not a crash, for an item the catalog has no record for', async () => {
    getMock.mockImplementation((path: string) => {
      if (path === '/inventory/item-1') {
        return Promise.resolve({
          item_id: 'item-1',
          display_name: 'Pikachu',
          status: 'available',
          cost_basis: '10.00',
          set_name: null,
          card_number: null,
        })
      }
      if (path === '/inventory/item-1/timeline') return Promise.resolve({ events: [] })
      if (path === '/inventory/item-1/price-chart') {
        return Promise.resolve({ points: [], buy_marker: null, timeframe: '1yr', item_id: 'item-1' })
      }
      return Promise.resolve({})
    })

    render(<AdminCardDetailPage />)

    await screen.findByText('Pikachu')
    // Both DetailRows still render the "—" placeholder rather than throwing
    // or disappearing — `DetailRow`'s existing `value || '—'` fallback.
    const setRow = screen.getByText('Set').closest('div')
    const numberRow = screen.getByText('Card Number').closest('div')
    expect(setRow).toHaveTextContent('—')
    expect(numberRow).toHaveTextContent('—')
  })
})
