import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, act, waitFor } from '@testing-library/react'
import AdminBuyPage from '../page'

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
    getMock.mockImplementation((path: string) => {
      if (path === '/market/search') return Promise.reject(new Error('gateway timeout'))
      if (path === '/locations') return Promise.resolve([])
      return Promise.resolve({})
    })

    const input = await renderBuyPage()
    fireEvent.change(input, { target: { value: 'Pikachu' } })

    await waitFor(() =>
      expect(getMock).toHaveBeenCalledWith('/market/search', { name: 'Pikachu' }),
    )

    expect(await screen.findByText(/catalog search failed/i)).toBeInTheDocument()
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
