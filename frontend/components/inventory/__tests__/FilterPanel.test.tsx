import { render, screen, waitFor, cleanup } from '@testing-library/react'
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
import type { InventoryItem, InventorySearchResult, InventoryFacets } from '@/lib/inventory'

const mockedApiFetch = vi.mocked(apiFetch)

// Facets response that the FilterPanel loads on mount.
const MOCK_FACETS: InventoryFacets = {
  sets: [
    { id: 'en:base1', name: 'Base' },
    { id: 'en:base2', name: 'Jungle' },
    { id: 'en:sv01', name: 'Scarlet & Violet' },
  ],
  rarities: ['Common', 'Rare Holo', 'Ultra Rare'],
  conditions: ['NM', 'LP', 'MP'],
  languages: ['EN', 'JP'],
}

beforeEach(() => {
  vi.clearAllMocks()
  // Default: facets call resolves, search calls need per-test mocking.
  mockedApiFetch.mockImplementation((path: string) => {
    if (String(path).includes('/inventory/facets')) {
      return Promise.resolve(MOCK_FACETS)
    }
    return Promise.resolve(response([]))
  })
})

const charizard: InventoryItem = {
  kind: 'raw',
  item_id: '01JRAWCHARIZARDNM0000000001',
  card_id: 'base1-4',
  listed_price: '250.42',
  current_market_value: '300.00',
  sticker_price: '250.42',
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
    market_price: null,
  },
}

function response(items: InventoryItem[], hiddenNoPrice = 0): InventorySearchResult {
  return { items, total: items.length, hidden_no_price: hiddenNoPrice }
}

function searchCalls(): string[] {
  return mockedApiFetch.mock.calls
    .map((c) => String(c[0]))
    .filter((p) => p.includes('/inventory/search'))
}

function lastSearchQuery(): URLSearchParams {
  const calls = searchCalls()
  const path = calls[calls.length - 1] ?? ''
  return new URLSearchParams(path.split('?')[1] ?? '')
}

describe('FilterPanel', () => {
  it('loads facets on mount and populates dropdowns from DB values', async () => {
    render(<FilterPanel />)
    // Wait for facets to load.
    await waitFor(() => {
      expect(mockedApiFetch).toHaveBeenCalledWith(
        '/inventory/facets',
        expect.objectContaining({ token: 'test-token' }),
      )
    })

    // Rarity dropdown has DB-driven options.
    const raritySelect = screen.getByLabelText(/rarity/i)
    const rarityOptions = Array.from(raritySelect.querySelectorAll('option')).map(
      (o) => o.textContent,
    )
    expect(rarityOptions).toContain('Common')
    expect(rarityOptions).toContain('Rare Holo')
    expect(rarityOptions).toContain('Ultra Rare')

    // Condition dropdown.
    const condSelect = screen.getByLabelText(/condition/i)
    const condOptions = Array.from(condSelect.querySelectorAll('option')).map(
      (o) => o.textContent,
    )
    expect(condOptions).toContain('NM')
    expect(condOptions).toContain('LP')
  })

  it('searches with backend param names and pushes matching items to the shared results pane', async () => {
    mockedApiFetch.mockImplementation((path: string) => {
      if (String(path).includes('/inventory/facets')) return Promise.resolve(MOCK_FACETS)
      return Promise.resolve(response([charizard]))
    })
    // RFC 0019: FilterPanel no longer renders its own results grid — it
    // pushes a normalized view up to the shared right-pane ResultsPane via
    // onResultsChange instead.
    const onResultsChange = vi.fn()
    render(<FilterPanel onResultsChange={onResultsChange} />)

    await userEvent.type(screen.getByLabelText(/name/i), 'Charizard')
    await userEvent.click(screen.getByRole('button', { name: /search/i }))

    const query = lastSearchQuery()
    expect(query.get('name')).toBe('Charizard')
    await waitFor(() => {
      expect(onResultsChange).toHaveBeenLastCalledWith(
        expect.objectContaining({
          status: 'success',
          cards: [expect.objectContaining({ title: 'Charizard' })],
        }),
      )
    })
  })

  it('sends the set_id from the combobox selection', async () => {
    render(<FilterPanel />)
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalled())

    // Type in the combobox to filter sets, then select one.
    const setInput = screen.getByLabelText(/set/i)
    await userEvent.click(setInput)
    await userEvent.type(setInput, 'Base')

    // Select "Base" from the listbox.
    const baseOption = await screen.findByRole('option', { name: 'Base' })
    await userEvent.click(baseOption)

    await userEvent.click(screen.getByRole('button', { name: /search/i }))

    expect(lastSearchQuery().get('set_id')).toBe('en:base1')
  })

  it('set combobox narrows options as user types', async () => {
    render(<FilterPanel />)
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalled())

    const setInput = screen.getByLabelText(/set/i)
    await userEvent.click(setInput)
    await userEvent.type(setInput, 'Scar')

    // Only "Scarlet & Violet" should match.
    const options = screen.getAllByRole('option')
    const optionTexts = options.map((o) => o.textContent)
    expect(optionTexts).toContain('Scarlet & Violet')
    expect(optionTexts).not.toContain('Jungle')
  })

  it('sends condition param from DB-driven dropdown', async () => {
    render(<FilterPanel />)
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalled())

    await userEvent.selectOptions(screen.getByLabelText(/condition/i), 'NM')
    await userEvent.click(screen.getByRole('button', { name: /search/i }))

    expect(lastSearchQuery().get('condition')).toBe('NM')
  })

  it('sends language=JP when Japanese is selected', async () => {
    render(<FilterPanel />)
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalled())

    await userEvent.selectOptions(screen.getByLabelText(/language/i), 'JP')
    await userEvent.click(screen.getByRole('button', { name: /search/i }))

    expect(lastSearchQuery().get('language')).toBe('JP')
  })

  it('omits the language param when "All languages" is selected', async () => {
    render(<FilterPanel />)
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalled())

    await userEvent.selectOptions(screen.getByLabelText(/language/i), 'JP')
    await userEvent.selectOptions(screen.getByLabelText(/language/i), 'All languages')
    await userEvent.click(screen.getByRole('button', { name: /search/i }))

    expect(lastSearchQuery().get('language')).toBeNull()
  })

  it('swaps an inverted price range before searching (backend rejects it with 422)', async () => {
    render(<FilterPanel />)
    await userEvent.type(screen.getByLabelText(/min price/i), '50')
    await userEvent.type(screen.getByLabelText(/max price/i), '10')
    await userEvent.click(screen.getByRole('button', { name: /search/i }))

    expect(lastSearchQuery().get('min_price')).toBe('10')
    expect(lastSearchQuery().get('max_price')).toBe('50')
  })

  it('forwards the Cognito access token from the session as a bearer token', async () => {
    render(<FilterPanel />)
    await userEvent.click(screen.getByRole('button', { name: /search/i }))

    const searchCall = mockedApiFetch.mock.calls.find((c) =>
      String(c[0]).includes('/inventory/search'),
    )
    expect(searchCall?.[1]).toEqual(expect.objectContaining({ token: 'test-token' }))
  })

  it('submits on Enter from the name field', async () => {
    mockedApiFetch.mockImplementation((path: string) => {
      if (String(path).includes('/inventory/facets')) return Promise.resolve(MOCK_FACETS)
      return Promise.resolve(response([charizard]))
    })
    render(<FilterPanel />)
    await userEvent.type(screen.getByLabelText(/name/i), 'Charizard{Enter}')
    expect(searchCalls().length).toBeGreaterThan(0)
    expect(lastSearchQuery().get('name')).toBe('Charizard')
  })

  it('reports the total from the backend as the shared pane\'s header label', async () => {
    mockedApiFetch.mockImplementation((path: string) => {
      if (String(path).includes('/inventory/facets')) return Promise.resolve(MOCK_FACETS)
      return Promise.resolve({ items: [charizard], total: 1, hidden_no_price: 0 })
    })
    const onResultsChange = vi.fn()
    render(<FilterPanel onResultsChange={onResultsChange} />)
    await userEvent.click(screen.getByRole('button', { name: /search/i }))
    await waitFor(() => {
      expect(onResultsChange).toHaveBeenLastCalledWith(
        expect.objectContaining({ headerLabel: '1 result' }),
      )
    })
  })

  it('surfaces the count of cards the price bound hid for having no price', async () => {
    mockedApiFetch.mockImplementation((path: string) => {
      if (String(path).includes('/inventory/facets')) return Promise.resolve(MOCK_FACETS)
      return Promise.resolve(response([charizard], 3))
    })
    const onResultsChange = vi.fn()
    render(<FilterPanel onResultsChange={onResultsChange} />)
    await userEvent.click(screen.getByRole('button', { name: /search/i }))
    await waitFor(() => {
      expect(onResultsChange).toHaveBeenLastCalledWith(
        expect.objectContaining({ truncatedNotice: '3 cards hidden (no price on file)' }),
      )
    })
  })

  it('surfaces the hidden count even when the price bound hid everything', async () => {
    mockedApiFetch.mockImplementation((path: string) => {
      if (String(path).includes('/inventory/facets')) return Promise.resolve(MOCK_FACETS)
      return Promise.resolve(response([], 12))
    })
    const onResultsChange = vi.fn()
    render(<FilterPanel onResultsChange={onResultsChange} />)
    await userEvent.click(screen.getByRole('button', { name: /search/i }))
    await waitFor(() => {
      expect(onResultsChange).toHaveBeenLastCalledWith(
        expect.objectContaining({ truncatedNotice: '12 cards hidden (no price on file)' }),
      )
    })
  })

  it('reports an empty-state message with no cards when nothing matches', async () => {
    const onResultsChange = vi.fn()
    render(<FilterPanel onResultsChange={onResultsChange} />)
    await userEvent.click(screen.getByRole('button', { name: /search/i }))
    await waitFor(() => {
      expect(onResultsChange).toHaveBeenLastCalledWith(
        expect.objectContaining({
          status: 'success',
          cards: [],
          emptyMessage: expect.stringMatching(/no cards/i),
        }),
      )
    })
  })

  it('reports an error status when the search request fails', async () => {
    mockedApiFetch.mockImplementation((path: string) => {
      if (String(path).includes('/inventory/facets')) return Promise.resolve(MOCK_FACETS)
      return Promise.reject(new Error('boom'))
    })
    const onResultsChange = vi.fn()
    render(<FilterPanel onResultsChange={onResultsChange} />)
    await userEvent.click(screen.getByRole('button', { name: /search/i }))
    await waitFor(() => {
      expect(onResultsChange).toHaveBeenLastCalledWith(
        expect.objectContaining({ status: 'error' }),
      )
    })
  })

  it('reports the idle prompt before any search has run', () => {
    const onResultsChange = vi.fn()
    render(<FilterPanel onResultsChange={onResultsChange} />)
    expect(onResultsChange).toHaveBeenLastCalledWith(
      expect.objectContaining({
        status: 'idle',
        cards: [],
        emptyMessage: expect.stringMatching(/set your filters/i),
      }),
    )
  })

  it('does not render its own card grid or results text — that belongs to the shared ResultsPane', async () => {
    mockedApiFetch.mockImplementation((path: string) => {
      if (String(path).includes('/inventory/facets')) return Promise.resolve(MOCK_FACETS)
      return Promise.resolve(response([charizard]))
    })
    render(<FilterPanel />)
    await userEvent.click(screen.getByRole('button', { name: /search/i }))
    await waitFor(() => expect(searchCalls().length).toBeGreaterThan(0))
    expect(screen.queryByText('Charizard')).toBeNull()
    expect(screen.queryByRole('heading', { name: 'Charizard' })).toBeNull()
  })
})
