import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import AdminHistoryPage from '../page'

/**
 * Card art on the History page.
 *
 * History answers "what happened to this card", and until now it answered it
 * entirely in text — search hits were a name plus a price, and the trade chain
 * was a row of ULID stubs. Both are places where the reader is identifying a
 * physical object, so both get the art.
 */

const getMock = vi.fn()
const postMock = vi.fn()

// One STABLE object: the real `useAdminApi` memoizes, and this page's
// callbacks are keyed on it. A fresh literal per render loops the effects.
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

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }))

const searchHit = {
  item_id: 'item-1',
  display_name: 'Pikachu #25',
  card_id: 'en:sv1-25',
  set_name: 'Scarlet & Violet',
  cost_basis: '20.00',
  status: 'available',
}

const chain = [
  { item_id: 'item-0', card_id: 'en:base1-4', name: 'Charizard', acquired_cost: '100.00', status: 'traded' },
  { item_id: 'item-1', card_id: 'en:sv1-25', name: 'Pikachu', acquired_cost: '20.00', status: 'available' },
]

function mockBackend({ images = {} as Record<string, string | null> } = {}) {
  getMock.mockImplementation((path: string) => {
    if (path === '/inventory/search') return Promise.resolve({ items: [searchHit], total: 1 })
    if (path.endsWith('/timeline')) return Promise.resolve({ item_id: 'item-1', events: [] })
    if (path.endsWith('/lineage')) {
      return Promise.resolve({ lineage_id: 'item-0', chain, chain_complete: false })
    }
    return Promise.resolve({})
  })
  postMock.mockImplementation((path: string) => {
    if (path === '/inventory/card-images') return Promise.resolve(images)
    return Promise.resolve({})
  })
}

async function searchAndSelect() {
  render(<AdminHistoryPage />)
  const input = screen.getByPlaceholderText(/search/i)
  fireEvent.change(input, { target: { value: 'Pikachu' } })
  const hit = await screen.findByText(/Pikachu #25/)
  fireEvent.click(hit)
  return hit
}

beforeEach(() => {
  getMock.mockReset()
  postMock.mockReset()
  postMock.mockResolvedValue({})
  mockBackend()
})

describe('AdminHistoryPage search results', () => {
  it('shows art on a search hit so near-identical names can be told apart', async () => {
    mockBackend({ images: { 'en:sv1-25': 'https://img.example/pika.png' } })

    render(<AdminHistoryPage />)
    fireEvent.change(screen.getByPlaceholderText(/search/i), { target: { value: 'Pika' } })

    const hit = await screen.findByText(/Pikachu #25/)
    const row = hit.closest('button')!
    await waitFor(() => {
      expect(within(row).getByRole('img')).toHaveAttribute(
        'src', 'https://img.example/pika.png',
      )
    })
  })
})

describe('AdminHistoryPage trade lineage', () => {
  it('shows each link of the chain as its own card art', async () => {
    // The chain is the one view where the reader is comparing DIFFERENT cards
    // side by side, so art per node is what makes the trade legible at all.
    mockBackend({
      images: {
        'en:base1-4': 'https://img.example/charizard.png',
        'en:sv1-25': 'https://img.example/pika.png',
      },
    })

    await searchAndSelect()
    fireEvent.click(await screen.findByRole('button', { name: /trade lineage/i }))

    await waitFor(() => {
      const srcs = screen.getAllByRole('img').map((i) => i.getAttribute('src'))
      expect(srcs).toContain('https://img.example/charizard.png')
      expect(srcs).toContain('https://img.example/pika.png')
    })
  })

  it('asks for every card in the chain in one batched request', async () => {
    await searchAndSelect()
    fireEvent.click(await screen.findByRole('button', { name: /trade lineage/i }))

    await waitFor(() => {
      const ids = postMock.mock.calls
        .filter(([p]) => p === '/inventory/card-images')
        .flatMap(([, body]) => body.card_ids as string[])
      expect(ids).toContain('en:base1-4')
      expect(ids).toContain('en:sv1-25')
    })
  })

  it('keeps a node readable when its link has no catalog card', async () => {
    // Sealed/bulk links legitimately have card_id: null. The node must still
    // render its name and cost rather than collapsing.
    getMock.mockImplementation((path: string) => {
      if (path === '/inventory/search') return Promise.resolve({ items: [searchHit], total: 1 })
      if (path.endsWith('/timeline')) return Promise.resolve({ item_id: 'item-1', events: [] })
      if (path.endsWith('/lineage')) {
        return Promise.resolve({
          lineage_id: 'item-9',
          chain: [{
            item_id: 'item-9', card_id: null, name: 'Booster Box',
            acquired_cost: '90.00', status: 'available',
          }],
          chain_complete: false,
        })
      }
      return Promise.resolve({})
    })

    await searchAndSelect()
    fireEvent.click(await screen.findByRole('button', { name: /trade lineage/i }))

    expect(await screen.findByText('Booster Box')).toBeInTheDocument()
  })
})
