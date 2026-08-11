import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, act, waitFor, within } from '@testing-library/react'
import AdminMarketPage from '../page'
import { AdminApiError } from '@/lib/admin-api'
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

  // RFC 0010 T17 — the weekly cycle promises every catalog card is re-priced by
  // Friday. That needs a number the owner can check, not a cadence that should
  // produce it, and the two counts are different facts: `brief` has never been
  // priced at all, `stale` was priced once and the cycle has since missed it.

  it('reports the weekly cycle counts and flags a cycle that is behind', () => {
    const state = getCoverageBannerState({
      ...base,
      catalog_cards_brief: 1200,
      catalog_cards_stale: 3,
      catalog_stale_threshold_days: 8,
    })
    expect(state.cycle).toBe('weekly cycle: 1200 never priced · 3 past 8 days')
    expect(state.cycleBehind).toBe(true)
  })

  it('does not flag a healthy cycle, even while the first pass is still running', () => {
    // ~31,300 rows are `brief` until the first cycle finishes, which takes ~6
    // nights. That is the cycle working, not failing — only a stale `full` row
    // means a slot was missed.
    const state = getCoverageBannerState({
      ...base,
      catalog_cards_brief: 31300,
      catalog_cards_stale: 0,
      catalog_stale_threshold_days: 8,
    })
    expect(state.cycleBehind).toBe(false)
  })

  it('renders no cycle line at all when the API did not send the counts', () => {
    // Never "0 never priced" from absent data: that is a claim the response did
    // not make, and it would read as a healthy cycle on an API that has none.
    expect(getCoverageBannerState(base).cycle).toBeNull()
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
      if (path === '/market/search') {
        return Promise.reject(new AdminApiError(500, 'Internal Server Error'))
      }
      return Promise.resolve({})
    })

    const input = await renderMarketPage()
    fireEvent.change(input, { target: { value: 'Pikachu' } })

    await waitFor(() =>
      expect(getMock).toHaveBeenCalledWith('/market/search', { name: 'Pikachu' }),
    )

    // Names the server error rather than asserting "a connection problem" —
    // the live failure was a 500 from a missing dynamodb:Scan grant, and the
    // old hard-coded copy actively misdirected the diagnosis.
    expect(await screen.findByText(/server hit an error \(500\)/i)).toBeInTheDocument()
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

// ---------------------------------------------------------------------------
// RFC 0010 T1 — money fields accept what a human types
// ---------------------------------------------------------------------------

describe('AdminMarketPage watchlist target price', () => {
  const promptSpy = vi.spyOn(window, 'prompt')

  beforeEach(() => {
    getMock.mockReset()
    postMock.mockReset()
    promptSpy.mockReset()
    postMock.mockResolvedValue({})
    getMock.mockImplementation((path: string) => {
      if (path === '/market/search') {
        return Promise.resolve({ items: [{ card_id: 'c1', name: 'Charizard ex', set_id: 'en:sv1', set_name: 'Scarlet & Violet' }], total: 1 })
      }
      if (path === '/watchlist') return Promise.resolve({ entries: [] })
      return Promise.resolve({})
    })
  })

  afterEach(() => { promptSpy.mockReset() })

  async function starTheFirstResult(typed: string | null) {
    promptSpy.mockReturnValue(typed)
    render(<AdminMarketPage />)
    await act(async () => { await Promise.resolve() })
    fireEvent.change(screen.getByPlaceholderText(/search catalog by name/i), { target: { value: 'Charizard' } })
    await waitFor(() => expect(screen.getByText('Charizard ex')).toBeInTheDocument())
    fireEvent.click(screen.getByTitle('Add to watchlist'))
  }

  it('sends 1300 when the admin types 1,300', async () => {
    await starTheFirstResult('1,300')
    await waitFor(() => expect(postMock).toHaveBeenCalledWith('/watchlist', expect.objectContaining({ target_buy_price: 1300 })))
  })

  it('still sends 1300 for a plain 1300 (regression gate)', async () => {
    await starTheFirstResult('1300')
    await waitFor(() => expect(postMock).toHaveBeenCalledWith('/watchlist', expect.objectContaining({ target_buy_price: 1300 })))
  })

  it('does not add a watchlist entry with a price it cannot read', async () => {
    await starTheFirstResult('1,30')
    await act(async () => { await Promise.resolve() })
    expect(postMock).not.toHaveBeenCalledWith('/watchlist', expect.anything())
  })

  it('still adds with no target price when the prompt is cancelled', async () => {
    await starTheFirstResult(null)
    await waitFor(() => expect(postMock).toHaveBeenCalledWith('/watchlist', expect.objectContaining({ target_buy_price: null })))
  })
})

// ---------------------------------------------------------------------------
// RFC 0010 T15 — a card picker shows name, image AND price
// ---------------------------------------------------------------------------

describe('AdminMarketPage catalog picker (RFC 0010 T15)', () => {
  const priced = {
    card_id: 'en:base1-4',
    name: 'Charizard',
    set_id: 'base1',
    set_name: 'Base Set',
    number: '004',
    rarity: 'Rare Holo',
    images: { small: 'https://img.example/zard.png' },
    display_price: '189.99',
    display_finish: 'holofoil',
    detail: 'full',
    last_synced_at: new Date().toISOString(),
  }

  beforeEach(() => {
    getMock.mockReset()
    postMock.mockReset()
    postMock.mockResolvedValue({})
    getMock.mockImplementation((path: string) => {
      if (path === '/market/search') return Promise.resolve({ items: [priced], total: 1 })
      if (path === '/watchlist') return Promise.resolve({ entries: [] })
      // The trend/confidence shapes are spelled out because clicking a row is
      // now exercised: a bare `{}` here does not resemble the real response,
      // and the page reads `points` off it unguarded (see follow-ups.md).
      if (path.endsWith('/trend')) return Promise.resolve({ card_id: 'en:base1-4', points: [] })
      if (path.endsWith('/confidence')) {
        return Promise.resolve({ level: 'low', points: 0, volatility_pct: '0', trend_pct: '0', reason: 'no data' })
      }
      return Promise.resolve({})
    })
  })

  async function search() {
    render(<AdminMarketPage />)
    await act(async () => { await Promise.resolve() })
    fireEvent.change(screen.getByPlaceholderText(/search catalog by name/i), { target: { value: 'Charizard' } })
    return screen.findByTestId('card-picker-row')
  }

  it('renders both the art and the price on every candidate', async () => {
    const row = await search()
    expect(within(row).getByAltText('Charizard')).toHaveAttribute('src', 'https://img.example/zard.png')
    expect(within(row).getByTestId('card-picker-price').textContent).toContain('$189.99')
  })

  it('still loads the price history when a candidate is clicked', async () => {
    const row = await search()
    fireEvent.click(within(row).getByRole('button', { name: /Charizard/ }))

    await waitFor(() => expect(getMock).toHaveBeenCalledWith(
      '/market/card/en:base1-4/trend',
      { days: 90 },
    ))
  })

  it('still stars a candidate onto the watchlist', async () => {
    const promptSpy = vi.spyOn(window, 'prompt').mockReturnValue(null)
    const row = await search()
    fireEvent.click(within(row).getByTitle('Add to watchlist'))

    await waitFor(() => expect(postMock).toHaveBeenCalledWith(
      '/watchlist',
      expect.objectContaining({ card_id: 'en:base1-4' }),
    ))
    promptSpy.mockRestore()
  })
})
