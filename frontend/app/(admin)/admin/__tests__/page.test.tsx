import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import AdminDashboardPage from '../page'

/**
 * The dashboard is the landing page, so its job is to answer three questions
 * without a click: what needs doing, what is the position worth, and is the
 * pricing data healthy.
 */

const getMock = vi.fn()

const mockApi = {
  get: getMock,
  post: vi.fn(),
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

const defaults = {
  inventory: {
    items: [
      { item_id: 'a', status: 'available', cost_basis: '100.00', current_market_value: '250.00', consignment: null },
      { item_id: 'b', status: 'available', cost_basis: '100.00', current_market_value: '150.00', consignment: null },
    ],
    total: 2,
  },
  mispriced: { total_flagged: 3 },
  locations: { locations: { glass: 2 }, total: 2 },
  triage: { total: 4, reasons: { flagged: 2, missing_card_id: 2 } },
  prepQueue: { items: [{ item_id: 'a' }], total: 1 },
  coverage: {
    total_items: 10, items_with_market_value: 8,
    catalog_cards: 100, catalog_cards_with_prices: 90, unmatched_sample: [],
  },
  daily: {
    date: '2026-08-07', total_sold: '420.00', items_sold_count: 3,
    net_sales: '420.00', total_bought: '0', items_bought_count: 0, trades_count: 0,
  },
}

function mockBackend(over: Partial<typeof defaults> = {}) {
  const d = { ...defaults, ...over }
  getMock.mockImplementation((path: string, params?: Record<string, unknown>) => {
    if (path === '/inventory/search') {
      // The Prep Queue count uses the same endpoint with a filter.
      if (params?.missing_sticker) return Promise.resolve(d.prepQueue)
      return Promise.resolve(d.inventory)
    }
    if (path === '/show-prep/mispriced') return Promise.resolve(d.mispriced)
    if (path === '/show-prep/location-summary') return Promise.resolve(d.locations)
    if (path === '/triage/counts') return Promise.resolve(d.triage)
    if (path === '/market/coverage') return Promise.resolve(d.coverage)
    if (path === '/analytics/daily') return Promise.resolve(d.daily)
    return Promise.resolve({})
  })
}

beforeEach(() => {
  getMock.mockReset()
  mockBackend()
})

describe('Dashboard money', () => {
  it('shows what the stock on hand is worth and what it cost', async () => {
    render(<AdminDashboardPage />)

    // Addressed by card: cost basis and unrealized profit are both $200.00 in
    // this fixture, so plain text matching would not prove which is which.
    expect(await screen.findByTestId('stat-market')).toHaveTextContent('$400.00')
    expect(await screen.findByTestId('stat-cost')).toHaveTextContent('$200.00')
    expect(await screen.findByTestId('stat-on-hand')).toHaveTextContent('2')
  })

  it('shows unrealized profit with its margin', async () => {
    render(<AdminDashboardPage />)

    const profit = await screen.findByTestId('stat-unrealized')
    expect(profit).toHaveTextContent('$200.00')
    expect(profit).toHaveTextContent('100.0%')
  })
})

describe('Dashboard needs-action queues', () => {
  it('surfaces the triage count and links to the triage page', async () => {
    render(<AdminDashboardPage />)

    const triage = await screen.findByTestId('action-triage')
    expect(triage).toHaveTextContent('4')
    expect(triage.closest('a')).toHaveAttribute('href', '/admin/triage')
  })

  it('surfaces the unstickered prep-queue count and links to it', async () => {
    render(<AdminDashboardPage />)

    const queue = await screen.findByTestId('action-prep-queue')
    expect(queue).toHaveTextContent('1')
    expect(queue.closest('a')).toHaveAttribute('href', '/admin/outgoing')
  })

  it('says so plainly when there is nothing to fix', async () => {
    // Three zeros read as "something is broken". An explicit all-clear is the
    // useful empty state.
    mockBackend({
      triage: { total: 0, reasons: {} },
      prepQueue: { items: [], total: 0 },
      mispriced: { total_flagged: 0 },
    })
    render(<AdminDashboardPage />)

    expect(await screen.findByText(/nothing needs attention/i)).toBeInTheDocument()
  })
})

describe('Dashboard activity', () => {
  it("shows today's sales count and revenue", async () => {
    render(<AdminDashboardPage />)

    const today = await screen.findByTestId('stat-today')
    expect(today).toHaveTextContent('$420.00')
    expect(today).toHaveTextContent('3')
  })
})

describe('Dashboard market health', () => {
  it('shows the share of inventory that actually carries a price', async () => {
    render(<AdminDashboardPage />)

    const coverage = await screen.findByTestId('stat-coverage')
    expect(coverage).toHaveTextContent('80%')
  })

  it('flags thin coverage rather than reporting it as neutral', async () => {
    mockBackend({
      coverage: {
        total_items: 10, items_with_market_value: 2,
        catalog_cards: 100, catalog_cards_with_prices: 90, unmatched_sample: [],
      },
    })
    render(<AdminDashboardPage />)

    const coverage = await screen.findByTestId('stat-coverage')
    await waitFor(() => expect(coverage).toHaveAttribute('data-tone', 'warning'))
  })
})

describe('Dashboard resilience', () => {
  it('still renders the rest when one panel\'s request fails', async () => {
    // Six independent requests back this page; one 500 must not blank it.
    getMock.mockImplementation((path: string, params?: Record<string, unknown>) => {
      if (path === '/triage/counts') return Promise.reject(new Error('boom'))
      if (path === '/inventory/search') {
        if (params?.missing_sticker) return Promise.resolve(defaults.prepQueue)
        return Promise.resolve(defaults.inventory)
      }
      if (path === '/market/coverage') return Promise.resolve(defaults.coverage)
      if (path === '/analytics/daily') return Promise.resolve(defaults.daily)
      if (path === '/show-prep/mispriced') return Promise.resolve(defaults.mispriced)
      if (path === '/show-prep/location-summary') return Promise.resolve(defaults.locations)
      return Promise.resolve({})
    })

    render(<AdminDashboardPage />)

    expect(await screen.findByTestId('stat-market')).toHaveTextContent('$400.00')
    expect(await screen.findByTestId('stat-coverage')).toHaveTextContent('80%')
  })
})

describe('Dashboard quick actions', () => {
  it('keeps the four primary actions', async () => {
    render(<AdminDashboardPage />)
    const nav = await screen.findByTestId('quick-actions')

    for (const label of ['New Sale', 'New Buy', 'New Trade', 'Vault']) {
      expect(within(nav).getByText(label)).toBeInTheDocument()
    }
  })
})
