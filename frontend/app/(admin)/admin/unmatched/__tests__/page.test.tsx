import { describe, it, expect, vi, beforeEach, afterAll } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AdminUnmatchedPage from '../page'
import { PACIFIC, pinTimeZone } from '@/lib/__tests__/_timezone'

/**
 * T8 — `/admin/unmatched`, the queue of cards TCGdex does not carry.
 * docs/plans/rfc-0011/t8-unmatched-queue-page.md
 *
 * The owner's ask: *"there should be a new tab that is just for cards that do
 * not have a match in TCGdex… this tab would let us move cards out of triage,
 * so triage is specifically for cards that actually have errors."*
 *
 * Two things this page is NOT:
 *
 * - it is not a second list endpoint. The list is
 *   `GET /admin/inventory/search?no_catalog_match=true` (T5), exactly as Triage
 *   reuses the same search with `?triage=true`;
 * - it is not a queue meant to reach zero. A card sits here until the catalog
 *   catches up, which may be never. The header copy has to say so, or an admin
 *   reads a permanently non-empty list as a backlog they are failing to clear.
 */

// Dates render here, so pin a NEGATIVE-offset zone. Every date bug RFC 0010 T8
// fixes is invisible at UTC. No fake timers at all: `formatTimestamp` reads the
// value off the row, and full fake timers deadlock `waitFor`.
const restoreTz = pinTimeZone(PACIFIC)
afterAll(restoreTz)

const getMock = vi.fn()
const putMock = vi.fn()

// One STABLE object, not a fresh literal per call. The real `useAdminApi`
// memoizes its return value and this page's fetch is a `useCallback` keyed on
// it — a mock with a new identity every render is an infinite fetch loop.
const mockApi = {
  get: getMock,
  post: vi.fn(),
  put: putMock,
  patch: vi.fn(),
  del: vi.fn(),
  isAuthenticated: true,
  isLoading: false,
}

vi.mock('@/lib/admin-api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/admin-api')>('@/lib/admin-api')
  return { ...actual, useAdminApi: () => mockApi }
})

// --- fixtures -------------------------------------------------------------

type Row = Record<string, unknown>

function parkedItem(over: Row = {}): Row {
  return {
    item_id: 'x',
    kind: 'raw',
    card_id: null,
    language: 'EN',
    display_name: 'Charizard #4',
    display_name_override: null,
    condition: 'NM',
    condition_modifier: null,
    no_catalog_match: true,
    no_catalog_match_at: '2026-06-01T12:00:00Z',
    current_market_value: '40.00',
    ...over,
  }
}

function candidate(over: Row = {}): Row {
  return {
    card_id: 'en:base1-4',
    name: 'Charizard',
    set_id: 'base1',
    set_name: 'Base Set',
    number: '4',
    rarity: 'Rare',
    image_small: 'https://img/1.png',
    market_price: '100.00',
    detail: 'full',
    last_synced_at: '2026-06-01T00:00:00Z',
    score: 1.0,
    why: 'name and number match',
    ...over,
  }
}

/**
 * Route by URL rather than queueing `mockResolvedValueOnce`s in call order.
 *
 * The page fires the list and the suggestions together; their resolution order
 * is not something a test should be asserting by accident, and a queue that
 * outlives its test poisons the next one.
 */
function mockApiRoutes({
  items = [] as Row[],
  suggestions = { items: [] as Row[], items_with_candidates: 0 },
  catalog = [] as Row[],
} = {}) {
  getMock.mockImplementation((path: string) => {
    if (path === '/inventory/search') return Promise.resolve({ items })
    if (path === '/unmatched/suggestions') return Promise.resolve(suggestions)
    if (path === '/market/search') return Promise.resolve({ items: catalog })
    return Promise.resolve({})
  })
}

beforeEach(() => {
  // reset, NOT clearAllMocks — `clearAllMocks` does not drain a
  // `mockResolvedValueOnce` queue, and leftovers cascade into the next test.
  getMock.mockReset()
  putMock.mockReset()
  putMock.mockResolvedValue({})
  mockApiRoutes()
})

// --- tests ----------------------------------------------------------------

describe('AdminUnmatchedPage — the list', () => {
  it('fetches only the parked cohort, from the shared search endpoint', async () => {
    render(<AdminUnmatchedPage />)

    await waitFor(() => expect(getMock).toHaveBeenCalledWith(
      '/inventory/search',
      expect.objectContaining({ no_catalog_match: 'true' }),
    ))
  })

  it('says the list is empty without implying something is broken', async () => {
    // The queue SHIPS empty (owner decision 4 — nothing is backfilled). An
    // empty state that reads as failure would make a correct install look wrong.
    render(<AdminUnmatchedPage />)

    expect(
      await screen.findByText(/nothing is waiting on the catalog/i),
    ).toBeInTheDocument()
  })

  it('says out loud that this list is not meant to reach zero', async () => {
    // Unlike Triage. A card waits here until TCGdex carries it, which may be
    // never, so a non-empty queue is not a backlog anyone is failing to clear.
    mockApiRoutes({ items: [parkedItem()] })
    render(<AdminUnmatchedPage />)

    expect(await screen.findByText(/not meant to reach zero/i)).toBeInTheDocument()
  })

  it('floats rows with candidates to the top', async () => {
    // "Which card can I pair now" is the question this page answers, so rows
    // that became actionable rise. Within a group, oldest park first.
    mockApiRoutes({
      items: [
        parkedItem({ item_id: 'none', display_name: 'Zzz',
                     no_catalog_match_at: '2026-01-01T00:00:00Z' }),
        parkedItem({ item_id: 'has', display_name: 'Aaa',
                     no_catalog_match_at: '2026-06-01T00:00:00Z' }),
      ],
      suggestions: {
        items: [{ item_id: 'has', candidates: [candidate()] }],
        items_with_candidates: 1,
      },
    })
    render(<AdminUnmatchedPage />)

    await screen.findByText('Aaa')
    const rows = screen.getAllByRole('row')
    expect(rows[1]).toHaveTextContent('Aaa')
  })

  it('renders the parked date in LOCAL time', async () => {
    // `new Date('2026-06-01')` is UTC midnight and renders as May 31 in every US
    // zone. This value is a datetime, so it goes through `formatTimestamp`.
    mockApiRoutes({ items: [parkedItem({ no_catalog_match_at: '2026-06-01T12:00:00Z' })] })
    render(<AdminUnmatchedPage />)

    expect(await screen.findByText(/Jun 1, 2026/)).toBeInTheDocument()
  })
})

describe('AdminUnmatchedPage — candidates', () => {
  it('shows name, image AND price on every candidate', async () => {
    // Owner rule, absolute: a card is never identified by name alone.
    mockApiRoutes({
      items: [parkedItem()],
      suggestions: {
        items: [{ item_id: 'x', candidates: [candidate()] }],
        items_with_candidates: 1,
      },
    })
    render(<AdminUnmatchedPage />)

    const row = await screen.findByTestId('card-picker-row')
    expect(within(row).getByRole('img', { name: /charizard/i })).toBeInTheDocument()
    expect(within(row).getByText('$100.00')).toBeInTheDocument()
    expect(within(row).getByText('Charizard')).toBeInTheDocument()
  })

  it('renders an absent price honestly, never as zero', async () => {
    // A missing band means no provider published a figure. `$0.00` is a lie,
    // and `detail: 'full'` is what says waiting will not help.
    mockApiRoutes({
      items: [parkedItem()],
      suggestions: {
        items: [{ item_id: 'x', candidates: [candidate({ market_price: null })] }],
        items_with_candidates: 1,
      },
    })
    render(<AdminUnmatchedPage />)

    const row = await screen.findByTestId('card-picker-row')
    expect(within(row).getByText(/not priced/i)).toBeInTheDocument()
    expect(screen.queryByText('$0.00')).not.toBeInTheDocument()
  })

  it('labels the price as a Near Mint catalog figure', async () => {
    // A catalog price is NOT condition-adjusted — there is no item condition in
    // a catalog row. Unlabelled, it reads as this DMG card's sale price.
    mockApiRoutes({
      items: [parkedItem({ condition: 'DMG' })],
      suggestions: {
        items: [{ item_id: 'x', candidates: [candidate()] }],
        items_with_candidates: 1,
      },
    })
    render(<AdminUnmatchedPage />)

    expect(await screen.findByText(/market \(nm\)/i)).toBeInTheDocument()
  })

  it('shows the reason a candidate was suggested, not its score', async () => {
    mockApiRoutes({
      items: [parkedItem()],
      suggestions: {
        items: [{ item_id: 'x', candidates: [
          candidate({ score: 0.7, why: 'name matches, number differs' }),
        ] }],
        items_with_candidates: 1,
      },
    })
    render(<AdminUnmatchedPage />)

    expect(await screen.findByText(/name matches, number differs/i)).toBeInTheDocument()
    expect(screen.queryByText('0.7')).not.toBeInTheDocument()
  })

  it('offers a full catalog search even on a row that HAS candidates', async () => {
    // Owner constraint, verbatim: "you must also have the option for the user to
    // search the whole catalog if none of those candidates match." An escape
    // hatch reachable only when the primary path fails cannot be reached in the
    // case where the primary path succeeds and is wrong.
    mockApiRoutes({
      items: [parkedItem()],
      suggestions: {
        items: [{ item_id: 'x', candidates: [candidate()] }],
        items_with_candidates: 1,
      },
    })
    render(<AdminUnmatchedPage />)

    expect(
      await screen.findByRole('button', { name: /search catalog/i }),
    ).toBeInTheDocument()
  })
})

describe('AdminUnmatchedPage — writes', () => {
  it('pairs a card by sending ONLY card_id', async () => {
    const user = userEvent.setup({ delay: null })
    mockApiRoutes({
      items: [parkedItem()],
      suggestions: {
        items: [{ item_id: 'x', candidates: [candidate({ card_id: 'en:base1-4' })] }],
        items_with_candidates: 1,
      },
    })
    render(<AdminUnmatchedPage />)

    await user.click(await screen.findByRole('button', { name: /^pair$/i }))
    await user.click(await screen.findByRole('button', { name: /^pair with/i }))

    // The server clears `no_catalog_match` when a `card_id` is assigned (T5).
    // Sending it here would be a second client-side copy of a server rule — and
    // sending it WITHOUT a card_id returns the row to Triage.
    await waitFor(() =>
      expect(putMock).toHaveBeenCalledWith('/inventory/x', { card_id: 'en:base1-4' }))
  })

  it('names the hand-set value the pairing is about to replace', async () => {
    // Same discipline as RepointDialog: it is the same write on the same
    // load-bearing field, and a dialog that silently discards $40.00 is the
    // surprise this codebase writes confirmation copy to prevent.
    const user = userEvent.setup({ delay: null })
    mockApiRoutes({
      items: [parkedItem({ current_market_value: '40.00' })],
      suggestions: {
        items: [{ item_id: 'x', candidates: [candidate()] }],
        items_with_candidates: 1,
      },
    })
    render(<AdminUnmatchedPage />)

    await user.click(await screen.findByRole('button', { name: /^pair$/i }))

    expect(await screen.findByText(/\$40\.00/)).toBeInTheDocument()
  })

  it('drops the paired row without refetching', async () => {
    const user = userEvent.setup({ delay: null })
    mockApiRoutes({
      items: [parkedItem()],
      suggestions: {
        items: [{ item_id: 'x', candidates: [candidate()] }],
        items_with_candidates: 1,
      },
    })
    render(<AdminUnmatchedPage />)

    await user.click(await screen.findByRole('button', { name: /^pair$/i }))
    const before = getMock.mock.calls.length
    await user.click(await screen.findByRole('button', { name: /^pair with/i }))

    await waitFor(() =>
      expect(screen.getByText(/nothing is waiting on the catalog/i)).toBeInTheDocument())
    expect(getMock.mock.calls.length).toBe(before)
  })

  it('sends a card back to triage', async () => {
    // The `unarchive` of this feature — parking that cannot be undone is just a
    // slower delete.
    const user = userEvent.setup({ delay: null })
    mockApiRoutes({ items: [parkedItem()] })
    render(<AdminUnmatchedPage />)

    await user.click(await screen.findByRole('button', { name: /back to triage/i }))

    await waitFor(() =>
      expect(putMock).toHaveBeenCalledWith('/inventory/x', { no_catalog_match: false }))
  })

  it('keeps the row and says so when a write fails', async () => {
    // A silent failure here looks identical to success: the row vanishes and
    // the admin believes the card was paired.
    const user = userEvent.setup({ delay: null })
    putMock.mockRejectedValue(new Error('nope'))
    mockApiRoutes({ items: [parkedItem()] })
    render(<AdminUnmatchedPage />)

    await user.click(await screen.findByRole('button', { name: /back to triage/i }))

    expect(await screen.findByText(/could not/i)).toBeInTheDocument()
    expect(screen.getByText(/Charizard/)).toBeInTheDocument()
  })

  it('writes the hand-set value through parseMoney, accepting a comma', async () => {
    // The owner types `1,300`. `parseFloat("1,300")` is 1 and is NOT NaN, so it
    // passes every isNaN guard and books a silent $1,299 loss.
    const user = userEvent.setup({ delay: null })
    mockApiRoutes({ items: [parkedItem({ current_market_value: null })] })
    render(<AdminUnmatchedPage />)

    const field = await screen.findByLabelText(/hand value/i)
    // A money field is a TEXT input, never `type="number"` — a native number
    // input cannot receive a comma, making the owner's input un-typeable.
    expect(field).toHaveAttribute('type', 'text')

    await user.type(field, '1,300')
    await user.tab()

    await waitFor(() =>
      expect(putMock).toHaveBeenCalledWith('/inventory/x',
        { current_market_value: '1300' }))
  })
})
