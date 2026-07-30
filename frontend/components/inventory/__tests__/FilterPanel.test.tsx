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
      market_price: null,
  },
}

function response(items: InventoryItem[], hiddenNoPrice = 0): InventorySearchResult {
  return { items, total: items.length, hidden_no_price: hiddenNoPrice }
}

function sentQuery(): URLSearchParams {
  const path = String(mockedApiFetch.mock.calls[0][0])
  return new URLSearchParams(path.split('?')[1] ?? '')
}

// Ground truth for the Set dropdown, verified against the live DynamoDB catalog
// table (full scan of catalog_card rows, matched on exact set_name).
//
// The catalog is TCGdex-sourced now, and `CatalogCard.set_id` is built as
// build_card_id(language, tcgdex_set_id) — a LANGUAGE-PREFIXED COMPOSITE
// (backend/src/merlins_collection/services/tcgdex.py). The backend's set_id
// filter looks the value up verbatim via repo.list_cards_by_set(set_id), so a
// bare pokemontcg.io id ("base1") matches zero rows and the dropdown silently
// returns "no cards". Every id below therefore carries the `en:` prefix, and
// two sets' TCGdex spelling also differs from the old pokemontcg.io spelling
// (sv1 → sv01, sv3pt5 → sv03.5).
const EXPECTED_SET_IDS: Array<[string, string]> = [
  ['Base', 'en:base1'],
  ['Jungle', 'en:base2'],
  ['Fossil', 'en:base3'],
  ['Team Rocket', 'en:base5'],
  ['Neo Genesis', 'en:neo1'],
  ['Expedition', 'en:ecard1'],
  ['Ruby & Sapphire', 'en:ex1'],
  ['Diamond & Pearl', 'en:dp1'],
  ['Black & White', 'en:bw1'],
  ['Evolutions', 'en:xy12'],
  ['Sword & Shield', 'en:swsh1'],
  ['Brilliant Stars', 'en:swsh9'],
  ['Scarlet & Violet', 'en:sv01'],
  ['151', 'en:sv03.5'],
]

async function searchWithSet(label: string): Promise<URLSearchParams> {
  mockedApiFetch.mockResolvedValue(response([]))
  render(<FilterPanel />)
  await userEvent.selectOptions(screen.getByLabelText(/set/i), label)
  await userEvent.click(screen.getByRole('button', { name: /search/i }))
  return sentQuery()
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

  it('sends the set as a set_id (display names map to composite catalog ids)', async () => {
    const query = await searchWithSet('Base')

    expect(query.get('set_id')).toBe('en:base1')
    expect(query.get('set')).toBeNull()
  })

  it.each(EXPECTED_SET_IDS)(
    'maps the %s option to the composite catalog set_id %s',
    async (label, expected) => {
      expect((await searchWithSet(label)).get('set_id')).toBe(expected)
    },
  )

  it('offers exactly the curated set labels (no option can be an unmapped dead end)', () => {
    mockedApiFetch.mockResolvedValue(response([]))
    render(<FilterPanel />)

    const options = Array.from(
      screen.getByLabelText(/set/i).querySelectorAll('option'),
    ).map((o) => o.textContent)

    expect(options).toEqual(['Any set', ...EXPECTED_SET_IDS.map(([label]) => label)])
  })

  it('never sends a bare pokemontcg.io set id (the pre-TCGdex shape that matched nothing)', async () => {
    for (const [label] of EXPECTED_SET_IDS) {
      vi.clearAllMocks()
      const sent = (await searchWithSet(label)).get('set_id')
      expect(sent, `${label} sent a non-composite set_id`).toMatch(/^en:/)
      cleanup()
    }
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
    mockedApiFetch.mockResolvedValue({ items: [charizard], total: 1, hidden_no_price: 0 })
    render(<FilterPanel />)
    await userEvent.click(screen.getByRole('button', { name: /search/i }))
    expect(await screen.findByText(/1 result\b/i)).toBeInTheDocument()
  })

  // Phase 12, owner decision 2: a price-bounded search still EXCLUDES items
  // with no resolvable price (a card with no known price cannot honestly be
  // claimed to be under $500), but the backend now reports how many it hid so
  // they are not dropped invisibly.
  it('surfaces the count of cards the price bound hid for having no price', async () => {
    mockedApiFetch.mockResolvedValue(response([charizard], 3))
    render(<FilterPanel />)
    await userEvent.click(screen.getByRole('button', { name: /search/i }))
    expect(await screen.findByText(/3 cards hidden \(no price on file\)/i)).toBeInTheDocument()
  })

  it('surfaces the hidden count even when the price bound hid everything', async () => {
    // The exact shape of the owner's bug report: an empty grid that used to
    // say only "No cards found" must now explain WHY it is empty.
    mockedApiFetch.mockResolvedValue(response([], 12))
    render(<FilterPanel />)
    await userEvent.click(screen.getByRole('button', { name: /search/i }))
    expect(await screen.findByText(/12 cards hidden \(no price on file\)/i)).toBeInTheDocument()
  })

  it('says "card" not "cards" when exactly one was hidden', async () => {
    mockedApiFetch.mockResolvedValue(response([charizard], 1))
    render(<FilterPanel />)
    await userEvent.click(screen.getByRole('button', { name: /search/i }))
    expect(await screen.findByText(/1 card hidden \(no price on file\)/i)).toBeInTheDocument()
  })

  it('renders no hidden-cards notice when nothing was hidden', async () => {
    mockedApiFetch.mockResolvedValue(response([charizard], 0))
    render(<FilterPanel />)
    await userEvent.click(screen.getByRole('button', { name: /search/i }))
    await screen.findByText(/1 result\b/i)
    expect(screen.queryByText(/no price on file/i)).not.toBeInTheDocument()
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
