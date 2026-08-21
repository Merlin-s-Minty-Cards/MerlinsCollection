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

    // RFC 0013 T4e converted this list to a DataTable — the clickable unit
    // is now a `<tr>` (implicit `role="row"`, matched via `closest('tr')`
    // the same way Triage/Inventory's own DataTable-row tests do), not a
    // hand-rolled `role="button"` card.
    const name = await screen.findByText('Portland Card Show')
    const row = name.closest('tr') as HTMLElement
    expect(within(row).getByText(/Aug 10, 2026/)).toBeInTheDocument()
    expect(within(row).queryByText(/Aug 9, 2026/)).not.toBeInTheDocument()
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

// ---------------------------------------------------------------------------
// RFC 0010 T10 — one real transaction renders as one line
// ---------------------------------------------------------------------------

/** Five cards bought in ONE session — five ledger rows, one transaction. */
const BATCH = Array.from({ length: 5 }, (_, i) => ({
  txn_id: `txn-b${i}`,
  type: 'purchase',
  item_id: `item-b${i}`,
  date: '2026-08-10',
  amount: '40.00',
  payment_method: 'cash',
  batch_id: 'buy-1',
}))

/** Written before `batch_id` existed. Deliberately never backfilled. */
const LEGACY = {
  txn_id: 'txn-legacy',
  type: 'sale',
  item_id: 'item-legacy',
  date: '2026-08-09',
  amount: '75.00',
  payment_method: 'venmo',
  batch_id: null,
}

describe('Show Analytics transaction grouping (RFC 0010 T10)', () => {
  beforeEach(() => {
    getMock.mockImplementation((path: string) => {
      if (path === '/analytics/dates') return Promise.resolve({ dates: ['2026-08-10'] })
      if (path === '/analytics/daily') {
        return Promise.resolve({
          date: '2026-08-10',
          total_sold: '75.00',
          total_bought: '200.00',
          net_sales: '-125.00',
          items_sold_count: 1,
          items_bought_count: 5,
          trades_count: 0,
          inventory_value_at_start: '5000.00',
          sell_through_rate: null,
        })
      }
      // The endpoint's own order: `(date, txn_id)` descending.
      if (path === '/transactions') return Promise.resolve({ items: [...BATCH, LEGACY] })
      if (path === '/shows') return Promise.resolve({ shows: [SHOW] })
      if (path === '/analytics/by-date') return Promise.resolve({ analytics: [] })
      return Promise.resolve({})
    })
    // SaleDetailModal's batched name/image lookup (owner report: sale rows
    // need image, name and price) — only hit when a "Cards" cell is clicked.
    postMock.mockImplementation((path: string) => {
      if (path === '/inventory/items-brief') return Promise.resolve({})
      return Promise.resolve({})
    })
  })

  async function openTheDay() {
    await renderPage()
    const picker = document.querySelector('input[type="date"]') as HTMLInputElement
    fireEvent.change(picker, { target: { value: '2026-08-10' } })
    await waitFor(() => expect(screen.getAllByTestId('txn-group').length).toBeGreaterThan(0))
  }

  it('renders five rows sharing a batch_id as ONE summary row', async () => {
    await openTheDay()
    // Six ledger rows in, two groups out: the five-card buy and the legacy sale.
    expect(screen.getAllByTestId('txn-group')).toHaveLength(2)
  })

  it('totals the group from its legs, signed', async () => {
    await openTheDay()
    const group = screen.getAllByTestId('txn-group')[0]
    expect(within(group).getByTestId('signed-amount')).toHaveTextContent('−$200.00')
  })

  it('shows how many cards the transaction covered', async () => {
    await openTheDay()
    const group = screen.getAllByTestId('txn-group')[0]
    expect(within(group).getByText(/5 cards/)).toBeInTheDocument()
  })

  // Rewritten: the inline chevron-expand (a raw item_id, no image or name)
  // was replaced by SaleDetailModal — owner report: *"listed sales should
  // have details of the cards sold including image, name, and price...
  // click on the bundled sale to view the individual components... in a
  // popup similar to how you would click on an inventory item."* See
  // TransactionGroups.test.tsx's "sale detail modal" block for the modal's
  // own behavior (image/name/price rendering, void/restore); this page-level
  // test only pins that the click reaches the popup with the right legs.
  it('opens the sale detail modal with all five legs when the cards cell is clicked', async () => {
    await openTheDay()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

    const group = screen.getAllByTestId('txn-group')[0]
    fireEvent.click(within(group).getByRole('button', { name: /view the 5 cards/i }))

    const dialog = await screen.findByRole('dialog')
    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith('/inventory/items-brief', {
        item_ids: BATCH.map((r) => r.item_id),
      }),
    )
    expect(within(dialog).getByText('5 cards')).toBeInTheDocument()
  })

  it('offers the same popup for a legacy row with no batch_id — a group of one still has no card identity inline', async () => {
    // No backfill: a (date, payment_method, type) heuristic would merge two
    // separate cash sales on one show day into a transaction that never
    // happened. A one-item group is a truthful rendering of what is known.
    //
    // The OLD chevron deliberately hid itself for a group of one ("a twisty
    // that reveals the same row is noise"). That reasoning no longer
    // applies: the popup shows real new information — image and resolved
    // name — that the collapsed row never carried for ANY group size, so a
    // one-card legacy sale gets the same "View" affordance as a five-card one.
    await openTheDay()
    const legacy = screen.getAllByTestId('txn-group')[1]
    expect(within(legacy).getByText(/1 card/)).toBeInTheDocument()

    fireEvent.click(within(legacy).getByRole('button', { name: /view the 1 card/i }))
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
  })

  it('keeps the endpoint order — grouping does not reorder the archive', async () => {
    await openTheDay()
    const groups = screen.getAllByTestId('txn-group')
    expect(within(groups[0]).getByText('Aug 10, 2026')).toBeInTheDocument()
    expect(within(groups[1]).getByText('Aug 9, 2026')).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// RFC 0010 T11 — an accidental sale can be undone, and a voided one is visible
// ---------------------------------------------------------------------------

/** Three cards sold in ONE session, so the void targets the whole transaction. */
const SALE_BATCH = Array.from({ length: 3 }, (_, i) => ({
  txn_id: `txn-s${i}`,
  type: 'sale',
  item_id: `item-s${i}`,
  date: '2026-08-10',
  amount: '40.00',
  payment_method: 'cash',
  batch_id: 'sell-1',
}))

const VOIDED_ROW = {
  txn_id: 'txn-void',
  type: 'sale',
  item_id: 'item-void',
  date: '2026-08-10',
  amount: '95.00',
  payment_method: 'venmo',
  batch_id: null,
  voided_at: '2026-08-11T18:30:00Z',
  voided_by: 'merlin',
  void_reason: 'Rang up the wrong card',
}

describe('Show Analytics transaction void (RFC 0010 T11)', () => {
  beforeEach(() => {
    getMock.mockImplementation((path: string) => {
      if (path === '/analytics/dates') return Promise.resolve({ dates: ['2026-08-10'] })
      if (path === '/analytics/daily') {
        return Promise.resolve({
          date: '2026-08-10', total_sold: '120.00', total_bought: '0.00',
          net_sales: '120.00', items_sold_count: 3, items_bought_count: 0,
          trades_count: 0, inventory_value_at_start: '5000.00',
          sell_through_rate: null,
        })
      }
      if (path === '/transactions') {
        return Promise.resolve({ items: [...SALE_BATCH, VOIDED_ROW] })
      }
      if (path === '/shows') return Promise.resolve({ shows: [SHOW] })
      if (path === '/analytics/by-date') return Promise.resolve({ analytics: [] })
      return Promise.resolve({})
    })
    postMock.mockResolvedValue({})
  })

  async function openTheDay() {
    await renderPage()
    const picker = document.querySelector('input[type="date"]') as HTMLInputElement
    fireEvent.change(picker, { target: { value: '2026-08-10' } })
    await waitFor(() => expect(screen.getAllByTestId('txn-group').length).toBeGreaterThan(0))
  }

  it('renders a voided row as voided, with its reason, on the archive too', async () => {
    await openTheDay()
    const voided = screen.getAllByTestId('txn-group')[1]
    expect(voided.className).toMatch(/line-through/)
    expect(within(voided).getByTestId('voided-note')).toHaveTextContent(
      /Rang up the wrong card/,
    )
  })

  it('voids the WHOLE transaction through the batch endpoint', async () => {
    await openTheDay()
    const group = screen.getAllByTestId('txn-group')[0]
    fireEvent.click(within(group).getByRole('button', { name: /void this transaction/i }))

    expect(screen.getByText(/void this whole transaction \(3 cards\)/i)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText(/reason/i), { target: { value: 'wrong customer' } })
    fireEvent.click(screen.getAllByRole('button', { name: /^void$/i }).at(-1)!)

    await waitFor(() => {
      expect(postMock).toHaveBeenCalledWith(
        '/transactions/batch/sell-1/void', { reason: 'wrong customer' },
      )
    })
  })

  it('restores a voided row through the single-row endpoint', async () => {
    await openTheDay()
    const voided = screen.getAllByTestId('txn-group')[1]
    fireEvent.click(within(voided).getByRole('button', { name: /restore/i }))

    await waitFor(() => {
      expect(postMock).toHaveBeenCalledWith('/transactions/txn-void/restore')
    })
  })
})

describe('Show Analytics stale snapshots (RFC 0010 T11)', () => {
  const STALE_SNAPSHOT = {
    show_id: 'show-1', date: '2026-08-10', total_sold: '80.00',
    total_bought: '20.00', net_sales: '60.00', items_sold_count: 2,
    items_bought_count: 1, trades_count: 0, stale: true,
  }

  beforeEach(() => {
    getMock.mockImplementation((path: string) => {
      if (path === '/analytics/dates') return Promise.resolve({ dates: [] })
      if (path === '/shows') return Promise.resolve({ shows: [SHOW] })
      if (path === '/analytics/by-date') {
        return Promise.resolve({ analytics: [STALE_SNAPSHOT] })
      }
      if (path === '/shows/show-1/analytics') return Promise.resolve(STALE_SNAPSHOT)
      return Promise.resolve({})
    })
  })

  it('never serves a stale snapshot silently — the list row says so', async () => {
    await renderPage()
    fireEvent.click(screen.getByRole('button', { name: 'Shows' }))

    // See the note above — the row is a DataTable `<tr>`, not a `role="button"` card.
    const name = await screen.findByText('Portland Card Show')
    const row = name.closest('tr') as HTMLElement
    expect(within(row).getByText(/out of date/i)).toBeInTheDocument()
  })

  it('says so on the detail view too, next to the regenerate button', async () => {
    await renderPage()
    fireEvent.click(screen.getByRole('button', { name: 'Shows' }))
    fireEvent.click(await screen.findByText('Portland Card Show'))

    expect(await screen.findByRole('alert')).toHaveTextContent(/out of date/i)
  })
})
