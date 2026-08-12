import { describe, it, expect, vi, beforeEach, afterEach, beforeAll, afterAll } from 'vitest'
import { render, screen, fireEvent, act, waitFor, within } from '@testing-library/react'
import AdminBuyPage from '../page'
import { AdminApiError } from '@/lib/admin-api'
import { pinTimeZone, PACIFIC } from '@/lib/__tests__/_timezone'

const getMock = vi.fn()
const postMock = vi.fn()

// Stable reference — a fresh object literal per render would give the page's
// useCallback new deps every render, re-firing its effects in a loop.
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

function catalogCard(card_id: string, name: string) {
  return { card_id, name, set_id: 'en:sv1', set_name: 'Scarlet & Violet', number: '001' }
}

async function renderBuyPage() {
  render(<AdminBuyPage />)
  await act(async () => { await Promise.resolve() })
  return screen.getByPlaceholderText(/search catalog or type name/i)
}

describe('AdminBuyPage catalog search failure states', () => {
  beforeEach(() => {
    getMock.mockReset()
    postMock.mockReset()
    postMock.mockResolvedValue({ buy_id: 'buy-1' })
    getMock.mockImplementation((path: string) => {
      if (path === '/locations') return Promise.resolve([])
      return Promise.resolve({})
    })
  })

  it('shows an error state — not "no matches" — when the catalog search rejects', async () => {
    // Reproduces the live failure: HTTP 500 from the missing dynamodb:Scan
    // grant, not the network fault the old copy asserted.
    getMock.mockImplementation((path: string) => {
      if (path === '/market/search') {
        return Promise.reject(new AdminApiError(500, 'Internal Server Error'))
      }
      if (path === '/locations') return Promise.resolve([])
      return Promise.resolve({})
    })

    const input = await renderBuyPage()
    fireEvent.change(input, { target: { value: 'Pikachu' } })

    await waitFor(() =>
      expect(getMock).toHaveBeenCalledWith('/market/search', { name: 'Pikachu' }),
    )

    expect(await screen.findByText(/server hit an error \(500\)/i)).toBeInTheDocument()
    // The whole point: a thrown request must never be dressed up as a
    // genuine zero-match, which is what made this undiagnosable from the UI.
    expect(screen.queryByText(/not found in catalog/i)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument()
  })

  it('retries the search when the error state\'s retry button is pressed', async () => {
    getMock.mockImplementation((path: string) => {
      if (path === '/market/search') return Promise.reject(new Error('gateway timeout'))
      if (path === '/locations') return Promise.resolve([])
      return Promise.resolve({})
    })

    const input = await renderBuyPage()
    fireEvent.change(input, { target: { value: 'Pikachu' } })
    const retry = await screen.findByRole('button', { name: /retry/i })

    getMock.mockImplementation((path: string) => {
      if (path === '/market/search') {
        return Promise.resolve({ items: [catalogCard('c1', 'Pikachu VMAX')], total: 1 })
      }
      if (path === '/locations') return Promise.resolve([])
      return Promise.resolve({})
    })

    await act(async () => { fireEvent.click(retry) })

    expect(await screen.findByText('Pikachu VMAX')).toBeInTheDocument()
    expect(screen.queryByText(/catalog search failed/i)).not.toBeInTheDocument()
  })

  it('ignores a stale response that resolves after a newer query', async () => {
    const resolvers: Record<string, (value: unknown) => void> = {}
    getMock.mockImplementation((path: string, params?: { name: string }) => {
      if (path === '/market/search') {
        return new Promise((resolve) => { resolvers[params!.name] = resolve })
      }
      if (path === '/locations') return Promise.resolve([])
      return Promise.resolve({})
    })

    const input = await renderBuyPage()

    fireEvent.change(input, { target: { value: 'Pik' } })
    await waitFor(() => expect(resolvers['Pik']).toBeDefined())

    fireEvent.change(input, { target: { value: 'Pikachu' } })
    await waitFor(() => expect(resolvers['Pikachu']).toBeDefined())

    // The current query resolves first...
    await act(async () => {
      resolvers['Pikachu']({ items: [catalogCard('c2', 'Pikachu VMAX')], total: 1 })
    })
    // ...and the abandoned one lands afterwards, as an 11-second scan does.
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

describe('AdminBuyPage money input', () => {
  beforeEach(() => {
    getMock.mockReset()
    postMock.mockReset()
    postMock.mockResolvedValue({ buy_id: 'buy-1' })
    getMock.mockImplementation((path: string) => {
      if (path === '/locations') return Promise.resolve([{ value: 'toploader', label: 'Toploader' }])
      if (path === '/market/search') {
        return Promise.resolve({ items: [catalogCard('c1', 'Charizard ex')], total: 1 })
      }
      return Promise.resolve({})
    })
  })

  // Gets the form into catalog mode, which is where Buy Price lives.
  async function pickACard() {
    const input = await renderBuyPage()
    fireEvent.change(input, { target: { value: 'Charizard' } })
    await waitFor(() => expect(screen.getByText('Charizard ex')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Charizard ex'))
    return screen.getByLabelText('Buy Price')
  }

  it('sends 1300 when the admin types 1,300 into Buy Price', async () => {
    const priceInput = await pickACard()
    fireEvent.change(priceInput, { target: { value: '1,300' } })
    fireEvent.click(screen.getByRole('button', { name: /add to purchase/i }))

    await waitFor(() => expect(postMock).toHaveBeenCalledWith(
      '/purchases/buy-1/items',
      expect.objectContaining({ buy_price: 1300 }),
    ))
  })

  it('still sends 1300 for a plain 1300 (regression gate)', async () => {
    const priceInput = await pickACard()
    fireEvent.change(priceInput, { target: { value: '1300' } })
    fireEvent.click(screen.getByRole('button', { name: /add to purchase/i }))

    await waitFor(() => expect(postMock).toHaveBeenCalledWith(
      '/purchases/buy-1/items',
      expect.objectContaining({ buy_price: 1300 }),
    ))
  })

  it('blocks the add and says so when the buy price is unreadable', async () => {
    const priceInput = await pickACard()
    // `1,30` is the plausible-looking typo the grouping rule exists to catch.
    fireEvent.change(priceInput, { target: { value: '1,30' } })
    expect(await screen.findByRole('alert')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /add to purchase/i }))
    await act(async () => { await Promise.resolve() })
    expect(postMock).not.toHaveBeenCalledWith('/purchases/buy-1/items', expect.anything())
  })

  it('totals the cart from the parsed amount, not a truncated one', async () => {
    const priceInput = await pickACard()
    fireEvent.change(priceInput, { target: { value: '1,300' } })
    fireEvent.click(screen.getByRole('button', { name: /add to purchase/i }))

    // parseFloat('1,300') is 1 — the total would read $1.00 and look plausible.
    // Two places show it: the cart row and the Total Cost line.
    expect(await screen.findAllByText('$1300.00')).toHaveLength(2)
  })
})

// ---------------------------------------------------------------------------
// RFC 0010 T15 — a card picker shows name, image AND price
// ---------------------------------------------------------------------------

describe('AdminBuyPage catalog picker (RFC 0010 T15)', () => {
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
    postMock.mockResolvedValue({ buy_id: 'buy-1' })
    getMock.mockImplementation((path: string) => {
      if (path === '/locations') return Promise.resolve([{ value: 'toploader', label: 'Toploader' }])
      if (path === '/market/search') return Promise.resolve({ items: [priced], total: 1 })
      return Promise.resolve({})
    })
  })

  it('renders both the art and the price on every candidate', async () => {
    const input = await renderBuyPage()
    fireEvent.change(input, { target: { value: 'Charizard' } })

    const row = await screen.findByTestId('card-picker-row')
    expect(within(row).getByAltText('Charizard')).toHaveAttribute('src', 'https://img.example/zard.png')
    expect(within(row).getByTestId('card-picker-price').textContent).toContain('$189.99')
  })

  it('still pre-fills the purchase form from the chosen candidate', async () => {
    // The regression half. Buy is a live money path; the display change must
    // not disturb what selecting a row actually does.
    const input = await renderBuyPage()
    fireEvent.change(input, { target: { value: 'Charizard' } })
    fireEvent.click(await screen.findByRole('button', { name: /Charizard/ }))

    await waitFor(() => expect(screen.getByLabelText('Buy Price')).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText('Buy Price'), { target: { value: '80' } })
    fireEvent.click(screen.getByRole('button', { name: /add to purchase/i }))

    await waitFor(() => expect(postMock).toHaveBeenCalledWith(
      '/purchases/buy-1/items',
      expect.objectContaining({ name: 'Charizard', buy_price: 80 }),
    ))
  })
})

// ---------------------------------------------------------------------------
// RFC 0010 T8 — the transaction date defaulted to tomorrow after 5pm Pacific
// ---------------------------------------------------------------------------

describe('AdminBuyPage default transaction date', () => {
  let restoreTz: () => void
  beforeAll(() => { restoreTz = pinTimeZone(PACIFIC) })
  afterAll(() => { restoreTz(); vi.useRealTimers() })

  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-08-11T01:30:00Z')) // 6:30pm Pacific, Aug 10
    getMock.mockReset()
    postMock.mockReset()
    postMock.mockResolvedValue({ buy_id: 'buy-1' })
    getMock.mockImplementation((path: string) => {
      if (path === '/locations') return Promise.resolve([{ value: 'toploader', label: 'Toploader' }])
      if (path === '/market/search') {
        return Promise.resolve({ items: [catalogCard('c1', 'Charizard ex')], total: 1 })
      }
      return Promise.resolve({})
    })
  })
  afterEach(() => vi.useRealTimers())

  it('defaults to Aug 10 at 6:30pm Pacific, not Aug 11', async () => {
    // The Transaction Date field only appears once the cart has something in
    // it, so a card has to be staged first.
    const input = await renderBuyPage()
    fireEvent.change(input, { target: { value: 'Charizard' } })
    await waitFor(() => expect(screen.getByText('Charizard ex')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Charizard ex'))
    fireEvent.change(screen.getByLabelText('Buy Price'), { target: { value: '10' } })
    fireEvent.click(screen.getByRole('button', { name: /add to purchase/i }))

    await waitFor(() =>
      expect(document.querySelector('input[type="date"]')).not.toBeNull(),
    )
    const date = document.querySelector('input[type="date"]') as HTMLInputElement
    expect(date.value).toBe('2026-08-10')
  })
})
