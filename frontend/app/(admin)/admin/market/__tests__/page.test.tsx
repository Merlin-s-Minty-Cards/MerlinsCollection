import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, act, waitFor } from '@testing-library/react'
import AdminMarketPage from '../page'
import { getCoverageBannerState, type MarketCoverage } from '@/lib/market-coverage'

const getMock = vi.fn()
const postMock = vi.fn()
// Stable reference — a fresh object literal per render would break the
// useCallback memoization in the component under test (new deps every
// render => effects re-firing every render => an infinite render loop).
const apiStub = {
  get: getMock,
  post: postMock,
  del: vi.fn(),
  put: vi.fn(),
  patch: vi.fn(),
  isAuthenticated: true,
  isLoading: false,
}

vi.mock('@/lib/admin-api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/admin-api')>('@/lib/admin-api')
  return {
    ...actual,
    useAdminApi: () => apiStub,
  }
})

describe('getCoverageBannerState', () => {
  const base: MarketCoverage = {
    total_items: 100,
    items_with_market_value: 80,
    catalog_cards: 50,
    catalog_cards_with_prices: 40,
    unmatched_sample: [],
  }

  it('formats the summary string exactly', () => {
    const state = getCoverageBannerState(base)
    expect(state.summary).toBe('80/100 items priced · catalog 40/50 cards priced')
  })

  it('flags an empty catalog', () => {
    const state = getCoverageBannerState({ ...base, catalog_cards: 0, catalog_cards_with_prices: 0 })
    expect(state.catalogEmpty).toBe(true)
  })

  it('does not flag a non-empty catalog as empty', () => {
    const state = getCoverageBannerState(base)
    expect(state.catalogEmpty).toBe(false)
  })

  it('shows the unmatched list when priced ratio is below 0.5', () => {
    const unmatched = Array.from({ length: 15 }, (_, i) => ({ item_id: `item-${i}`, name: `Card ${i}` }))
    const state = getCoverageBannerState({
      ...base,
      items_with_market_value: 10,
      total_items: 100,
      unmatched_sample: unmatched,
    })
    expect(state.showUnmatched).toBe(true)
    expect(state.unmatchedItems).toHaveLength(10)
    expect(state.unmatchedItems[0]).toEqual({ item_id: 'item-0', name: 'Card 0' })
  })

  it('hides the unmatched list when priced ratio is at or above 0.5', () => {
    const state = getCoverageBannerState({
      ...base,
      items_with_market_value: 50,
      total_items: 100,
      unmatched_sample: [{ item_id: 'x', name: 'y' }],
    })
    expect(state.showUnmatched).toBe(false)
  })
})

describe('AdminMarketPage sync poll lifecycle', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    getMock.mockReset()
    postMock.mockReset()
    getMock.mockImplementation((path: string) => {
      if (path === '/market/coverage') {
        return Promise.resolve({
          total_items: 10,
          items_with_market_value: 8,
          catalog_cards: 5,
          catalog_cards_with_prices: 5,
          unmatched_sample: [],
        })
      }
      if (path === '/market/search') {
        return Promise.resolve({ items: [], total: 0 })
      }
      return Promise.resolve({})
    })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('polls sync status every 3s while running, then stops on completion', async () => {
    postMock.mockResolvedValueOnce({ state: 'started' })
    getMock.mockImplementationOnce(() => Promise.resolve({ // initial coverage call
      total_items: 10,
      items_with_market_value: 8,
      catalog_cards: 5,
      catalog_cards_with_prices: 5,
      unmatched_sample: [],
    }))

    render(<AdminMarketPage />)

    await act(async () => {
      await Promise.resolve()
    })

    const syncButton = screen.getByRole('button', { name: /sync prices/i })

    getMock.mockImplementationOnce(() =>
      Promise.resolve({ state: 'running', started_at: 't1', finished_at: null, priced_cards: null, updated_items: null, error: null }),
    )

    await act(async () => {
      fireEvent.click(syncButton)
      await Promise.resolve()
    })

    // First interval tick (t=3s) consumes the queued 'running' status.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000)
    })

    const statusCallsAfterTrigger = getMock.mock.calls.filter((c) => c[0] === '/market/sync/status').length
    expect(statusCallsAfterTrigger).toBe(1)

    getMock.mockImplementationOnce(() =>
      Promise.resolve({ state: 'completed', started_at: 't1', finished_at: 't2', priced_cards: 5, updated_items: 12, error: null }),
    )

    // Second interval tick (t=6s) consumes the queued 'completed' status.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000)
    })

    expect(screen.getByText(/priced 5 cards, updated 12 items/i)).toBeInTheDocument()

    const statusCallsAfterCompletion = getMock.mock.calls.filter((c) => c[0] === '/market/sync/status').length
    expect(statusCallsAfterCompletion).toBeGreaterThan(statusCallsAfterTrigger)

    // Advancing further should NOT issue another status poll — interval must be cleared.
    const callsBeforeFurtherAdvance = getMock.mock.calls.filter((c) => c[0] === '/market/sync/status').length
    await act(async () => {
      await vi.advanceTimersByTimeAsync(9000)
    })
    const callsAfterFurtherAdvance = getMock.mock.calls.filter((c) => c[0] === '/market/sync/status').length
    expect(callsAfterFurtherAdvance).toBe(callsBeforeFurtherAdvance)
  })

  it('stops polling when the sync fails', async () => {
    postMock.mockResolvedValueOnce({ state: 'started' })

    render(<AdminMarketPage />)
    await act(async () => {
      await Promise.resolve()
    })

    const syncButton = screen.getByRole('button', { name: /sync prices/i })
    await act(async () => {
      fireEvent.click(syncButton)
      await Promise.resolve()
    })

    getMock.mockImplementationOnce(() =>
      Promise.resolve({ state: 'failed', started_at: 't1', finished_at: 't2', priced_cards: null, updated_items: null, error: 'boom' }),
    )

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000)
    })

    expect(screen.getByText('boom')).toBeInTheDocument()

    const callsAfterFailure = getMock.mock.calls.filter((c) => c[0] === '/market/sync/status').length
    await act(async () => {
      await vi.advanceTimersByTimeAsync(9000)
    })
    const callsAfterMoreTime = getMock.mock.calls.filter((c) => c[0] === '/market/sync/status').length
    expect(callsAfterMoreTime).toBe(callsAfterFailure)
  })

  it('clears the poll interval on unmount', async () => {
    postMock.mockResolvedValueOnce({ state: 'started' })

    const { unmount } = render(<AdminMarketPage />)
    await act(async () => {
      await Promise.resolve()
    })

    const syncButton = screen.getByRole('button', { name: /sync prices/i })
    await act(async () => {
      fireEvent.click(syncButton)
      await Promise.resolve()
    })

    getMock.mockImplementation((path: string) => {
      if (path === '/market/sync/status') {
        return Promise.resolve({ state: 'running', started_at: 't1', finished_at: null, priced_cards: null, updated_items: null, error: null })
      }
      return Promise.resolve({})
    })

    unmount()

    const callsAtUnmount = getMock.mock.calls.filter((c) => c[0] === '/market/sync/status').length

    await act(async () => {
      await vi.advanceTimersByTimeAsync(9000)
    })

    const callsAfterUnmount = getMock.mock.calls.filter((c) => c[0] === '/market/sync/status').length
    expect(callsAfterUnmount).toBe(callsAtUnmount)
  })
})

describe('AdminMarketPage catalog search failure states', () => {
  const coverage = {
    total_items: 10,
    items_with_market_value: 8,
    catalog_cards: 5,
    catalog_cards_with_prices: 5,
    unmatched_sample: [],
  }

  function catalogCard(card_id: string, name: string) {
    return { card_id, name, set_id: 'en:sv1', set_name: 'Scarlet & Violet', number: '001' }
  }

  beforeEach(() => {
    getMock.mockReset()
    postMock.mockReset()
    getMock.mockImplementation((path: string) => {
      if (path === '/market/coverage') return Promise.resolve(coverage)
      return Promise.resolve({})
    })
  })

  async function renderMarketPage() {
    render(<AdminMarketPage />)
    await act(async () => { await Promise.resolve() })
    return screen.getByPlaceholderText(/search catalog by name/i)
  }

  it('shows an error state — not "no cards found" — when the search rejects', async () => {
    getMock.mockImplementation((path: string) => {
      if (path === '/market/coverage') return Promise.resolve(coverage)
      if (path === '/market/search') return Promise.reject(new Error('gateway timeout'))
      return Promise.resolve({})
    })

    const input = await renderMarketPage()
    fireEvent.change(input, { target: { value: 'Pikachu' } })

    await waitFor(() =>
      expect(getMock).toHaveBeenCalledWith('/market/search', { name: 'Pikachu' }),
    )

    expect(await screen.findByText(/catalog search failed/i)).toBeInTheDocument()
    expect(screen.queryByText(/no cards found in catalog/i)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument()
  })

  it('ignores a stale response that resolves after a newer query', async () => {
    const resolvers: Record<string, (value: unknown) => void> = {}
    getMock.mockImplementation((path: string, params?: { name: string }) => {
      if (path === '/market/coverage') return Promise.resolve(coverage)
      if (path === '/market/search') {
        return new Promise((resolve) => { resolvers[params!.name] = resolve })
      }
      return Promise.resolve({})
    })

    const input = await renderMarketPage()

    fireEvent.change(input, { target: { value: 'Pik' } })
    await waitFor(() => expect(resolvers['Pik']).toBeDefined())

    fireEvent.change(input, { target: { value: 'Pikachu' } })
    await waitFor(() => expect(resolvers['Pikachu']).toBeDefined())

    await act(async () => {
      resolvers['Pikachu']({ items: [catalogCard('c2', 'Pikachu VMAX')], total: 1 })
    })
    await act(async () => {
      resolvers['Pik']({ items: [catalogCard('c1', 'Pikipek')], total: 1 })
    })

    expect(screen.getByText('Pikachu VMAX')).toBeInTheDocument()
    expect(screen.queryByText('Pikipek')).not.toBeInTheDocument()
  })
})
