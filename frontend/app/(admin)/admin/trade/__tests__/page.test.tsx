import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, act, waitFor } from '@testing-library/react'
import AdminTradePage from '../page'
import { AdminApiError } from '@/lib/admin-api'

const getMock = vi.fn()
const postMock = vi.fn()

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

async function renderTradePage() {
  render(<AdminTradePage />)
  await act(async () => { await Promise.resolve() })
  return screen.getByPlaceholderText('Name')
}

describe('AdminTradePage incoming-leg catalog search failure states', () => {
  beforeEach(() => {
    getMock.mockReset()
    postMock.mockReset()
    postMock.mockResolvedValue({ trade_id: 'trade-1' })
    getMock.mockImplementation(() => Promise.resolve({}))
  })

  it('shows an error state — not "no catalog match" — when the search rejects', async () => {
    // A 500 is what the live site actually returned (the ECS task role was
    // missing dynamodb:Scan), so that is what this reproduces. The banner must
    // name the server error and must NOT blame the connection: the old copy
    // hard-coded "a connection problem", which pointed the investigation at
    // the network while the real fault was an IAM policy.
    getMock.mockImplementation((path: string) => {
      if (path === '/market/search') {
        return Promise.reject(new AdminApiError(500, 'Internal Server Error'))
      }
      return Promise.resolve({})
    })

    const input = await renderTradePage()
    fireEvent.change(input, { target: { value: 'Pikachu' } })

    await waitFor(() =>
      expect(getMock).toHaveBeenCalledWith('/market/search', { name: 'Pikachu' }),
    )

    expect(await screen.findByText(/server hit an error \(500\)/i)).toBeInTheDocument()
    expect(screen.queryByText(/connection/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/no catalog match/i)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument()
  })

  it('calls an unreachable server a connection problem — and only then', async () => {
    // The counterpart: a rejected fetch really is a network fault, and this is
    // the one case where saying so is accurate.
    getMock.mockImplementation((path: string) => {
      if (path === '/market/search') return Promise.reject(new TypeError('Failed to fetch'))
      return Promise.resolve({})
    })

    const input = await renderTradePage()
    fireEvent.change(input, { target: { value: 'Pikachu' } })

    expect(await screen.findByText(/could not be reached/i)).toBeInTheDocument()
    expect(screen.queryByText(/no catalog match/i)).not.toBeInTheDocument()
  })

  it('retries the search when the error state\'s retry button is pressed', async () => {
    getMock.mockImplementation((path: string) => {
      if (path === '/market/search') return Promise.reject(new Error('gateway timeout'))
      return Promise.resolve({})
    })

    const input = await renderTradePage()
    fireEvent.change(input, { target: { value: 'Pikachu' } })
    const retry = await screen.findByRole('button', { name: /retry/i })

    getMock.mockImplementation((path: string) => {
      if (path === '/market/search') {
        return Promise.resolve({ items: [catalogCard('c1', 'Pikachu VMAX')], total: 1 })
      }
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
      return Promise.resolve({})
    })

    const input = await renderTradePage()

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

describe('AdminTradePage vendor mode removal (RFC 0008 §F3)', () => {
  // `mode: "customer"|"vendor"` gated the percent-based margin split from RFC
  // 0007 §A1, retired by the Round 3 OWNER RULING 2026-08-04 and replaced by
  // the unconditional basis_mode selector. Nothing on the backend branches on
  // "vendor" — the toggle was purely cosmetic.
  beforeEach(() => {
    getMock.mockReset()
    postMock.mockReset()
    postMock.mockResolvedValue({ trade_id: 'trade-1' })
    getMock.mockImplementation(() => Promise.resolve({}))
  })

  it('renders no vendor/customer mode toggle', async () => {
    await renderTradePage()

    expect(screen.queryByRole('button', { name: /vendor mode/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^customer mode$/i })).not.toBeInTheDocument()
  })

  it('leaves the Customer View toggle alone — it is a different, live control', async () => {
    await renderTradePage()

    expect(screen.getByRole('button', { name: /customer view/i })).toBeInTheDocument()
  })

  it('omits any "(vendor mode)" suffix from the confirm-trade dialog', async () => {
    getMock.mockImplementation((path: string) => {
      if (path === '/inventory/search') {
        return Promise.resolve({
          items: [{ item_id: 'i-1', display_name: 'Charizard', current_market_value: '100.00' }],
        })
      }
      return Promise.resolve({})
    })

    await renderTradePage()

    fireEvent.change(screen.getByPlaceholderText('Search our inventory…'), {
      target: { value: 'Charizard' },
    })
    const result = await screen.findByText('Charizard')
    await act(async () => { fireEvent.click(result) })

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /confirm trade/i }))
    })

    expect(await screen.findByText(/execute trade:/i)).toBeInTheDocument()
    expect(screen.queryByText(/vendor mode/i)).not.toBeInTheDocument()
  })

  it('still renders all three basis modes — the live control must not be collateral damage', async () => {
    await renderTradePage()

    expect(screen.getByRole('button', { name: 'Transfer' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Split' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Manual' })).toBeInTheDocument()
  })
})

// ===========================================================================
// Card art on the staged trade legs
// ===========================================================================

describe('AdminTradePage staged leg card art', () => {
  beforeEach(() => {
    getMock.mockReset()
    postMock.mockReset()
    postMock.mockImplementation((path: string) => {
      if (path === '/trades') return Promise.resolve({ trade_id: 'trade-1' })
      if (path === '/inventory/card-images') {
        return Promise.resolve({
          'en:sv1-25': 'https://img.example/pika.png',
          'en:base1-4': 'https://img.example/zard.png',
        })
      }
      return Promise.resolve({})
    })
    getMock.mockImplementation(() => Promise.resolve({}))
  })

  it('shows art on a card staged to go out', async () => {
    // Going Out is the leg where the business gives up stock. Confirming the
    // right physical card left the case is exactly what the art is for.
    getMock.mockImplementation((path: string) => {
      if (path === '/inventory/search') {
        return Promise.resolve({
          items: [{
            item_id: 'item-1', display_name: 'Pikachu #25',
            card_id: 'en:sv1-25', current_market_value: '20.00',
          }],
        })
      }
      return Promise.resolve({})
    })

    render(<AdminTradePage />)
    await act(async () => { await Promise.resolve() })

    fireEvent.change(screen.getByPlaceholderText(/search our inventory/i), {
      target: { value: 'Pikachu' },
    })
    const hit = await screen.findByText('Pikachu #25')
    await act(async () => { fireEvent.click(hit) })

    await waitFor(() => {
      const srcs = screen.getAllByRole('img').map((i) => i.getAttribute('src'))
      expect(srcs).toContain('https://img.example/pika.png')
    })
  })

  it('carries the chosen catalog card art onto a staged incoming leg', async () => {
    // Picking a catalog match already proves which card it is; the staged row
    // has to keep showing that, or the confirmation step goes back to text.
    getMock.mockImplementation((path: string) => {
      if (path === '/market/search') {
        return Promise.resolve({
          items: [{
            card_id: 'en:base1-4', name: 'Charizard', set_id: 'en:base1',
            set_name: 'Base Set', number: '004',
          }],
          total: 1,
        })
      }
      return Promise.resolve({})
    })

    render(<AdminTradePage />)
    await act(async () => { await Promise.resolve() })

    fireEvent.change(screen.getByPlaceholderText('Name'), { target: { value: 'Charizard' } })
    const suggestion = await screen.findByText('Charizard')
    await act(async () => { fireEvent.click(suggestion) })

    // Value is required before the leg can be staged.
    fireEvent.change(screen.getByLabelText(/trade-in value/i), { target: { value: '100' } })
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /add incoming card/i }))
    })

    await waitFor(() => {
      const srcs = screen.getAllByRole('img').map((i) => i.getAttribute('src'))
      expect(srcs).toContain('https://img.example/zard.png')
    })
  })
})
