import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@/lib/api', () => ({ apiFetch: vi.fn() }))

// The panel reads the Cognito access token from the NextAuth session.
vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { accessToken: 'test-token' },
    status: 'authenticated',
  }),
}))

import { apiFetch } from '@/lib/api'
import FilterPanel from '@/components/inventory/FilterPanel'
import type { InventoryItem, InventorySearchResult } from '@/lib/inventory'

const mockedApiFetch = vi.mocked(apiFetch)

beforeEach(() => {
  vi.clearAllMocks()
})

const charizard: InventoryItem = {
  kind: 'raw',
  item_id: '01JRAWCHARIZARDNM0000000001',
  card_id: 'base1-4',
  listed_price: '250.42',
  current_market_value: '300.00',
  acquired_at: '2026-04-01',
  finish: 'holofoil',
  condition: 'NM',
  card: {
    card_id: 'base1-4',
    name: 'Charizard',
    set_id: 'base1',
    set_name: 'Base',
    number: '4',
    rarity: 'Rare Holo',
    image_small: 'https://img/charizard.png',
  },
}

function response(items: InventoryItem[]): InventorySearchResult {
  return { items, total: items.length }
}

function sentQuery(): URLSearchParams {
  const path = String(mockedApiFetch.mock.calls[0][0])
  return new URLSearchParams(path.split('?')[1] ?? '')
}

describe('FilterPanel', () => {
  it('searches with backend param names and renders matching items', async () => {
    mockedApiFetch.mockResolvedValue(response([charizard]))
    render(<FilterPanel />)

    await userEvent.type(screen.getByLabelText(/name/i), 'Charizard')
    await userEvent.click(screen.getByRole('button', { name: /search/i }))

    expect(String(mockedApiFetch.mock.calls[0][0])).toBe('/inventory/search?name=Charizard')
    expect(await screen.findByText('Charizard')).toBeInTheDocument()
    expect(screen.getByText('$250.42')).toBeInTheDocument()
  })

  it('sends the set as a set_id (display names map to pokemontcg.io ids)', async () => {
    mockedApiFetch.mockResolvedValue(response([]))
    render(<FilterPanel />)

    await userEvent.selectOptions(screen.getByLabelText(/set/i), 'Base')
    await userEvent.click(screen.getByRole('button', { name: /search/i }))

    expect(sentQuery().get('set_id')).toBe('base1')
    expect(sentQuery().get('set')).toBeNull()
  })

  it('offers raw-condition grades instead of a Pokémon type filter', async () => {
    mockedApiFetch.mockResolvedValue(response([]))
    render(<FilterPanel />)

    expect(screen.queryByLabelText(/type/i)).toBeNull()

    await userEvent.selectOptions(screen.getByLabelText(/condition/i), 'NM')
    await userEvent.click(screen.getByRole('button', { name: /search/i }))

    expect(sentQuery().get('condition')).toBe('NM')
  })

  it('sends language=JP when Japanese is selected', async () => {
    mockedApiFetch.mockResolvedValue(response([]))
    render(<FilterPanel />)

    await userEvent.selectOptions(screen.getByLabelText(/language/i), 'Japanese')
    await userEvent.click(screen.getByRole('button', { name: /search/i }))

    expect(sentQuery().get('language')).toBe('JP')
  })

  it('omits the language param when "All languages" is selected', async () => {
    mockedApiFetch.mockResolvedValue(response([]))
    render(<FilterPanel />)

    // Select Japanese, then switch back to All languages — must not send it.
    await userEvent.selectOptions(screen.getByLabelText(/language/i), 'Japanese')
    await userEvent.selectOptions(screen.getByLabelText(/language/i), 'All languages')
    await userEvent.click(screen.getByRole('button', { name: /search/i }))

    expect(sentQuery().get('language')).toBeNull()
  })

  it('swaps an inverted price range before searching (backend rejects it with 422)', async () => {
    mockedApiFetch.mockResolvedValue(response([]))
    render(<FilterPanel />)
    await userEvent.type(screen.getByLabelText(/min price/i), '50')
    await userEvent.type(screen.getByLabelText(/max price/i), '10')
    await userEvent.click(screen.getByRole('button', { name: /search/i }))

    expect(sentQuery().get('min_price')).toBe('10')
    expect(sentQuery().get('max_price')).toBe('50')
  })

  it('forwards the Cognito access token from the session as a bearer token', async () => {
    mockedApiFetch.mockResolvedValue(response([]))
    render(<FilterPanel />)

    await userEvent.click(screen.getByRole('button', { name: /search/i }))

    expect(mockedApiFetch).toHaveBeenCalledWith(
      expect.stringContaining('/inventory/search'),
      expect.objectContaining({ token: 'test-token' }),
    )
  })

  it('submits on Enter from the name field', async () => {
    mockedApiFetch.mockResolvedValue(response([charizard]))
    render(<FilterPanel />)
    await userEvent.type(screen.getByLabelText(/name/i), 'Charizard{Enter}')
    expect(String(mockedApiFetch.mock.calls[0][0])).toBe('/inventory/search?name=Charizard')
  })

  it('shows the total from the backend', async () => {
    mockedApiFetch.mockResolvedValue({ items: [charizard], total: 1 })
    render(<FilterPanel />)
    await userEvent.click(screen.getByRole('button', { name: /search/i }))
    expect(await screen.findByText(/1 result\b/i)).toBeInTheDocument()
  })

  it('shows an empty state when nothing matches', async () => {
    mockedApiFetch.mockResolvedValue(response([]))
    render(<FilterPanel />)
    await userEvent.click(screen.getByRole('button', { name: /search/i }))
    expect(await screen.findByText(/no cards/i)).toBeInTheDocument()
  })

  it('shows an error state when the request fails', async () => {
    mockedApiFetch.mockRejectedValue(new Error('boom'))
    render(<FilterPanel />)
    await userEvent.click(screen.getByRole('button', { name: /search/i }))
    expect(await screen.findByText(/something went wrong/i)).toBeInTheDocument()
  })

  it('ignores a stale response when a newer search resolves first', async () => {
    let resolveFirst: (value: InventorySearchResult) => void = () => {}
    const firstPending = new Promise<InventorySearchResult>((res) => {
      resolveFirst = res
    })
    const blastoise: InventoryItem = {
      ...charizard,
      card_id: 'base1-2',
      card: { ...charizard.card!, card_id: 'base1-2', name: 'Blastoise' },
    }
    mockedApiFetch
      .mockImplementationOnce(() => firstPending)
      .mockImplementationOnce(() => Promise.resolve(response([blastoise])))

    render(<FilterPanel />)
    const search = screen.getByRole('button', { name: /search/i })
    await userEvent.click(search) // first request — stays pending
    await userEvent.click(search) // second request — resolves immediately

    expect(await screen.findByText('Blastoise')).toBeInTheDocument()

    // The stale first request now resolves; it must not overwrite the newer result.
    resolveFirst(response([charizard]))
    await waitFor(() => expect(screen.queryByText('Charizard')).not.toBeInTheDocument())
    expect(screen.getByText('Blastoise')).toBeInTheDocument()
  })
})
