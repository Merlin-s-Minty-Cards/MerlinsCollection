import { describe, it, expect, vi, beforeEach, afterAll } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import DealPage from '../page'
import { pinTimeZone, PACIFIC } from '@/lib/__tests__/_timezone'

/**
 * RFC 0011 T15 — one page, three modes (buy / sell / trade).
 *
 * The pre-unification page had its own deep test file covering catalog search
 * failure states, money-input parsing and card-art plumbing. That file tested
 * UI structure (`getByPlaceholderText('Name')`, the old two-column-only layout)
 * that T15 replaces outright, so this file supersedes it rather than extending
 * it — the underlying behaviours it protected (parseMoney everywhere, no
 * parseFloat, stale-response guards) live on inside `DealSearchPanel`,
 * `IncomingCardForm` and `lib/deal-session.ts`, each with their own tests.
 */

const apiGet = vi.fn()
const apiPost = vi.fn()
const apiPut = vi.fn()
const apiPatch = vi.fn()
const apiDel = vi.fn()

const mockApi = {
  get: apiGet,
  post: apiPost,
  put: apiPut,
  patch: apiPatch,
  del: apiDel,
  isAuthenticated: true,
  isLoading: false,
}

vi.mock('@/lib/admin-api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/admin-api')>('@/lib/admin-api')
  return { ...actual, useAdminApi: () => mockApi }
})

const replace = vi.fn()
let currentParams = new URLSearchParams()

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace }),
  usePathname: () => '/admin/trade',
  useSearchParams: () => currentParams,
}))

function mockSearchParams(params: Record<string, string>) {
  currentParams = new URLSearchParams(params)
}

const CARD = {
  card_id: 'en:base1-4',
  name: 'Charizard',
  set_id: 'base1',
  set_name: 'Base Set',
  number: '004',
  images: { small: 'https://img.example/zard.png' },
}

const INVENTORY_ITEM = {
  item_id: 'item-1',
  display_name: 'Pikachu #25',
  card_id: 'en:sv1-25',
  current_market_value: '20.00',
}

function defaultGet(path: string) {
  if (path === '/market/search') return Promise.resolve({ items: [CARD], total: 1 })
  if (path === '/inventory/search') return Promise.resolve({ items: [INVENTORY_ITEM] })
  if (path === '/locations') return Promise.resolve([])
  if (path === '/catalog/sets') return Promise.resolve([])
  return Promise.resolve({})
}

function defaultPost(path: string) {
  if (path === '/trades') return Promise.resolve({ trade_id: 'deal-1' })
  if (path === '/purchases') return Promise.resolve({ buy_id: 'deal-1' })
  if (path === '/sales') return Promise.resolve({ sell_id: 'deal-1' })
  if (path === '/inventory/card-images') {
    return Promise.resolve({
      'en:base1-4': 'https://img.example/zard.png',
      'en:sv1-25': 'https://img.example/pika.png',
    })
  }
  return Promise.resolve({})
}

let restoreTz: () => void
beforeEach(() => {
  restoreTz = pinTimeZone(PACIFIC)
  mockSearchParams({})
  replace.mockReset()
  apiGet.mockReset()
  apiPost.mockReset()
  apiPut.mockReset()
  apiPatch.mockReset()
  apiDel.mockReset()
  apiGet.mockImplementation(defaultGet)
  apiPost.mockImplementation(defaultPost)
  apiPut.mockResolvedValue({})
  apiPatch.mockResolvedValue({})
  apiDel.mockResolvedValue({})
})
afterAll(() => { restoreTz?.() })

/** Stages one incoming card via the catalog pick -> IncomingCardForm path. */
async function addOneIncoming(
  user: ReturnType<typeof userEvent.setup>,
  opts: { price?: string } = {},
) {
  const nameInput = await screen.findByLabelText('Card name')
  await user.type(nameInput, CARD.name)
  const row = await screen.findByTestId('card-picker-row')
  await user.click(within(row).getByRole('button', { name: new RegExp(CARD.name) }))
  const form = screen.getByTestId('incoming-form')
  const valueInput = within(form).getByLabelText('Value')
  await user.type(valueInput, opts.price ?? '10.00')
  await user.click(within(form).getByRole('button', { name: 'Add' }))
}

/** Stages one outgoing (our) card via the inventory search path. */
async function addOneOutgoing(
  user: ReturnType<typeof userEvent.setup>,
  opts: { price?: string } = {},
) {
  const inventoryRadio = screen.queryByRole('radio', { name: /^inventory$/i })
  if (inventoryRadio) await user.click(inventoryRadio)
  const nameInput = await screen.findByLabelText('Card name')
  await user.type(nameInput, 'Pikachu')
  const hit = await screen.findByRole('button', { name: /pikachu/i })
  await user.click(hit)
  if (opts.price) {
    const draft = await screen.findByLabelText(/outgoing value/i)
    await user.clear(draft)
    await user.type(draft, opts.price)
    await user.tab()
  }
}

describe('the unified deal page', () => {
  it('defaults to trade mode and shows both columns', async () => {
    render(<DealPage />)
    expect(await screen.findByRole('heading', { name: /coming in/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /going out/i })).toBeInTheDocument()
  })

  it('hides Going Out in buy mode', async () => {
    mockSearchParams({ mode: 'buy' })
    render(<DealPage />)
    expect(await screen.findByRole('heading', { name: /coming in/i })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: /going out/i })).not.toBeInTheDocument()
  })

  it('hides Coming In in sell mode', async () => {
    mockSearchParams({ mode: 'sell' })
    render(<DealPage />)
    expect(await screen.findByRole('heading', { name: /going out/i })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: /coming in/i })).not.toBeInTheDocument()
  })

  it('puts the mode in the URL when toggled', async () => {
    const user = userEvent.setup({ delay: null })
    render(<DealPage />)
    await screen.findByRole('heading', { name: /coming in/i })
    await user.click(screen.getByRole('radio', { name: /^buy$/i }))
    expect(replace).toHaveBeenCalledWith(expect.stringContaining('mode=buy'))
  })

  it('confirms before abandoning a non-empty session', async () => {
    const user = userEvent.setup({ delay: null })
    render(<DealPage />)
    await addOneIncoming(user)

    await user.click(screen.getByRole('radio', { name: /^sell$/i }))

    expect(await screen.findByRole('dialog')).toHaveTextContent(/discard/i)
  })

  it('switches modes without a dialog when nothing is staged', async () => {
    const user = userEvent.setup({ delay: null })
    render(<DealPage />)
    await screen.findByRole('heading', { name: /coming in/i })
    await user.click(screen.getByRole('radio', { name: /^sell$/i }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('shows image, name and price on every staged row', async () => {
    const user = userEvent.setup({ delay: null })
    render(<DealPage />)
    await addOneIncoming(user, { price: '120.00' })

    const stagedRow = within(screen.getByTestId('coming-in')).getByTestId('deal-card-row')
    expect(within(stagedRow).getByRole('img', { name: /charizard/i })).toBeInTheDocument()
    expect(within(stagedRow).getByText('Charizard')).toBeInTheDocument()
    expect(within(stagedRow).getByText('$120.00')).toBeInTheDocument()
  })

  it('removes cost basis and profit from the DOM in customer view', async () => {
    const user = userEvent.setup({ delay: null })
    render(<DealPage />)
    await addOneIncoming(user)
    await user.click(screen.getByRole('switch', { name: /customer view/i }))

    expect(screen.queryByText(/cost basis/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/profit/i)).not.toBeInTheDocument()
  })

  it('shows cost-basis mode only in trade', async () => {
    mockSearchParams({ mode: 'buy' })
    render(<DealPage />)
    await screen.findByRole('heading', { name: /coming in/i })
    expect(screen.queryByLabelText(/basis/i)).not.toBeInTheDocument()
  })

  it('defaults the date to the LOCAL today', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-08-13T23:30:00Z')) // 4:30pm PDT
    render(<DealPage />)
    expect(await screen.findByDisplayValue('2026-08-13')).toBeInTheDocument()
    vi.useRealTimers()
  })

  it('renders a net total for a mixed-direction trade', async () => {
    const user = userEvent.setup({ delay: null })
    render(<DealPage />)
    await addOneIncoming(user, { price: '30.00' })
    await addOneOutgoing(user, { price: '50.00' })

    expect(within(screen.getByTestId('deal-balance')).getByText('+$20.00'))
      .toBeInTheDocument()
  })

  it('patches the negotiated Going Out price to the session before confirm', async () => {
    const user = userEvent.setup({ delay: null })
    render(<DealPage />)
    await addOneOutgoing(user, { price: '15.00' })

    expect(apiPatch).toHaveBeenCalledWith(
      '/trades/deal-1/outgoing/item-1',
      { agreed_value: 15 },
    )
  })

  it('sends the selected payment method on Sell confirm, not a hardcoded cash default (Critical 2)', async () => {
    const user = userEvent.setup({ delay: null })
    mockSearchParams({ mode: 'sell' })
    render(<DealPage />)
    await addOneOutgoing(user, { price: '15.00' })

    await user.selectOptions(screen.getByLabelText(/^payment method$/i), 'venmo')
    await user.click(screen.getByRole('button', { name: /confirm sale/i }))
    await user.click(screen.getByRole('button', { name: /execute sell/i }))

    expect(apiPatch).toHaveBeenCalledWith(
      '/sales/deal-1',
      expect.objectContaining({ payment_method: 'venmo' }),
    )
  })

  it('gates "+ Manual entry" out of Sell mode, where a sale always has an existing item (Important 5)', async () => {
    mockSearchParams({ mode: 'sell' })
    render(<DealPage />)
    await screen.findByRole('heading', { name: /going out/i })
    expect(screen.queryByRole('button', { name: /manual entry/i })).not.toBeInTheDocument()
  })

  it('offers "+ Manual entry" in Buy and Trade modes', async () => {
    render(<DealPage />)
    await screen.findByRole('heading', { name: /coming in/i })
    expect(screen.getByRole('button', { name: /manual entry/i })).toBeInTheDocument()
  })

  it('allows Graded to be picked on an incoming card in Buy mode (RFC 0012 — regression coverage for trade/page.tsx wiring, not just IncomingCardForm internals)', async () => {
    const user = userEvent.setup({ delay: null })
    mockSearchParams({ mode: 'buy' })
    render(<DealPage />)

    const nameInput = await screen.findByLabelText('Card name')
    await user.type(nameInput, CARD.name)
    const row = await screen.findByTestId('card-picker-row')
    await user.click(within(row).getByRole('button', { name: new RegExp(CARD.name) }))
    const form = screen.getByTestId('incoming-form')

    expect(within(form).getByRole('radio', { name: /graded/i })).toBeEnabled()
  })
})
