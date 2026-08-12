/**
 * RFC 0010 T8 — every date on Show Analytics was a day early.
 *
 * The owner's report: *"Display date on show analytics is wrong by one date
 * backward, Aug 10 shows as Aug 9. However, the 'pick a date' option shows the
 * correct date."* The picker was right because it binds the ISO string and
 * never builds a `Date`; everything else went through one that did.
 *
 * THE TZ PIN IS THE TEST. At UTC every assertion below passes against the
 * unfixed code — `new Date("2026-08-10")` is UTC midnight, and it only slips
 * back a day at a negative offset. Without `pinTimeZone(PACIFIC)` this file is
 * theatre.
 */
import { describe, it, expect, vi, beforeAll, afterAll, beforeEach } from 'vitest'
import { render, screen, fireEvent, act, waitFor, within } from '@testing-library/react'
import AdminAnalyticsPage from '../page'
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

const SHOW = {
  show_id: 'show-1',
  name: 'Portland Card Show',
  date: '2026-08-10',
  location: 'Expo Center',
}

const TXN = {
  txn_id: 'txn-1',
  type: 'sale',
  item_id: 'item-1',
  date: '2026-08-10',
  amount: '40.00',
  payment_method: 'cash',
}

let restoreTz: () => void

beforeAll(() => {
  restoreTz = pinTimeZone(PACIFIC)
})
afterAll(() => {
  restoreTz()
  vi.useRealTimers()
})

beforeEach(() => {
  // 6:30pm Pacific on Aug 10 — the evening the business is actually selling.
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date('2026-08-11T01:30:00Z'))
  getMock.mockReset()
  postMock.mockReset()
  getMock.mockImplementation((path: string) => {
    if (path === '/analytics/dates') return Promise.resolve({ dates: ['2026-08-10'] })
    if (path === '/analytics/daily') {
      return Promise.resolve({
        date: '2026-08-10',
        total_sold: '40.00',
        total_bought: '200.00',
        net_sales: '-160.00',
        items_sold_count: 1,
        items_bought_count: 1,
        trades_count: 0,
        inventory_value_at_start: '5000.00',
        sell_through_rate: null,
      })
    }
    if (path === '/transactions') return Promise.resolve({ items: [TXN] })
    if (path === '/shows') return Promise.resolve({ shows: [SHOW] })
    if (path === '/analytics/by-date') return Promise.resolve({ analytics: [] })
    if (path === '/shows/show-1/analytics') return Promise.resolve(null)
    return Promise.resolve({})
  })
})

async function renderPage() {
  render(<AdminAnalyticsPage />)
  await act(async () => { await Promise.resolve() })
}

describe('Show Analytics dates (RFC 0010 T8)', () => {
  it('renders a transaction dated 2026-08-10 as Aug 10, not Aug 9', async () => {
    await renderPage()
    const picker = document.querySelector('input[type="date"]') as HTMLInputElement
    fireEvent.change(picker, { target: { value: '2026-08-10' } })

    const row = await screen.findByText('cash')
    const table = row.closest('table') as HTMLElement
    expect(within(table).getByText('Aug 10, 2026')).toBeInTheDocument()
    expect(within(table).queryByText('Aug 9, 2026')).not.toBeInTheDocument()
  })

  it('renders the show archive list entry as Aug 10, not Aug 9', async () => {
    await renderPage()
    fireEvent.click(screen.getByRole('button', { name: 'Shows' }))

    const name = await screen.findByText('Portland Card Show')
    const card = name.closest('[role="button"]') as HTMLElement
    expect(within(card).getByText(/Aug 10, 2026/)).toBeInTheDocument()
    expect(within(card).queryByText(/Aug 9, 2026/)).not.toBeInTheDocument()
  })

  it('renders the selected-show header as Aug 10, not Aug 9', async () => {
    await renderPage()
    fireEvent.click(screen.getByRole('button', { name: 'Shows' }))
    fireEvent.click(await screen.findByText('Portland Card Show'))

    // The detail view's own header, below the show name.
    const heading = await screen.findByRole('heading', { name: 'Portland Card Show' })
    const header = heading.closest('header') as HTMLElement
    await waitFor(() =>
      expect(within(header).getByText(/Aug 10, 2026/)).toBeInTheDocument(),
    )
    expect(within(header).queryByText(/Aug 9, 2026/)).not.toBeInTheDocument()
  })

  it('defaults the shows date range to the LOCAL today, not the UTC one', async () => {
    // Same defect, different door: the range's `end` was
    // `new Date().toISOString().split('T')[0]`, which at 6:30pm Pacific is
    // tomorrow — so the picker beside the list disagreed with the list.
    await renderPage()
    fireEvent.click(screen.getByRole('button', { name: 'Shows' }))
    await screen.findByText('Portland Card Show')

    const dateInputs = Array.from(
      document.querySelectorAll('input[type="date"]'),
    ) as HTMLInputElement[]
    const end = dateInputs[dateInputs.length - 1]
    expect(end.value).toBe('2026-08-10')
  })
})

// ---------------------------------------------------------------------------
// RFC 0010 T9 — a sale reads +$40, a purchase reads −$200
// ---------------------------------------------------------------------------

describe('Show Analytics signed amounts (RFC 0010 T9)', () => {
  beforeEach(() => {
    getMock.mockImplementation((path: string) => {
      if (path === '/analytics/dates') return Promise.resolve({ dates: ['2026-08-10'] })
      if (path === '/analytics/daily') {
        return Promise.resolve({
          date: '2026-08-10',
          total_sold: '40.00',
          total_bought: '200.00',
          // A buying-heavy day: net genuinely went the other way.
          net_sales: '-160.00',
          items_sold_count: 1,
          items_bought_count: 1,
          trades_count: 0,
          inventory_value_at_start: '5000.00',
          sell_through_rate: null,
        })
      }
      if (path === '/transactions') {
        return Promise.resolve({
          items: [
            TXN,
            {
              txn_id: 'txn-2',
              type: 'purchase',
              item_id: 'item-2',
              date: '2026-08-10',
              amount: '200.00',
              payment_method: 'venmo',
            },
          ],
        })
      }
      if (path === '/shows') return Promise.resolve({ shows: [SHOW] })
      if (path === '/analytics/by-date') return Promise.resolve({ analytics: [] })
      return Promise.resolve({})
    })
  })

  async function openTheDay() {
    await renderPage()
    const picker = document.querySelector('input[type="date"]') as HTMLInputElement
    fireEvent.change(picker, { target: { value: '2026-08-10' } })
    await screen.findByText('venmo')
  }

  it('renders a purchase row as −$200.00', async () => {
    await openTheDay()
    const row = screen.getByText('venmo').closest('tr') as HTMLElement
    expect(within(row).getByTestId('signed-amount')).toHaveTextContent('−$200.00')
  })

  it('renders a sale row as +$40.00', async () => {
    await openTheDay()
    const row = screen.getByText('cash').closest('tr') as HTMLElement
    expect(within(row).getByTestId('signed-amount')).toHaveTextContent('+$40.00')
  })

  it('renders a negative Net Sales signed, not as a bare figure', async () => {
    // Today it renders a plain number that reads as profit whichever direction
    // the day actually went.
    await openTheDay()
    const tile = screen.getByText('Net Sales').closest('div')
      ?.parentElement as HTMLElement
    expect(within(tile).getByTestId('signed-amount')).toHaveTextContent('−$160.00')
  })
})
