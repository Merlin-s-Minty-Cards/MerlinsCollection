import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@/lib/api', () => ({ apiFetch: vi.fn() }))

import { apiFetch } from '@/lib/api'
import {
  buildSearchQuery,
  searchInventory,
  sendChat,
  formatPrice,
  itemTitle,
  itemKey,
  conditionLabel,
  type InventoryItem,
  type InventorySearchResult,
} from '@/lib/inventory'

const mockedApiFetch = vi.mocked(apiFetch)

beforeEach(() => {
  vi.clearAllMocks()
})

// Fixtures mirror the backend wire format exactly: Decimal fields are STRINGS
// (pinned by backend test_search_response_serializes_decimals_as_strings).
export function makeRawItem(overrides: Record<string, unknown> = {}): InventoryItem {
  return {
    kind: 'raw',
    card_id: 'base1-4',
    quantity: 1,
    listed_price: '250.00',
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
    ...overrides,
  } as InventoryItem
}

export function makeGradedItem(overrides: Record<string, unknown> = {}): InventoryItem {
  return {
    kind: 'graded',
    card_id: 'base1-4',
    quantity: 1,
    listed_price: '900.00',
    current_market_value: null,
    acquired_at: '2026-04-01',
    company: 'PSA',
    grade: '9.5',
    cert_number: '12345678',
    card: {
      card_id: 'base1-4',
      name: 'Charizard',
      set_id: 'base1',
      set_name: 'Base',
      number: '4',
      rarity: 'Rare Holo',
      image_small: 'https://img/charizard.png',
    },
    ...overrides,
  } as InventoryItem
}

describe('buildSearchQuery', () => {
  it('uses the backend query param names', () => {
    const params = new URLSearchParams(
      buildSearchQuery({
        name: 'Pikachu',
        set_id: 'base1',
        rarity: 'Rare Holo',
        condition: 'NM',
        min_price: '5',
        max_price: '50',
      }),
    )
    expect(params.get('name')).toBe('Pikachu')
    expect(params.get('set_id')).toBe('base1')
    expect(params.get('rarity')).toBe('Rare Holo')
    expect(params.get('condition')).toBe('NM')
    expect(params.get('min_price')).toBe('5')
    expect(params.get('max_price')).toBe('50')
  })

  it('omits empty / undefined fields', () => {
    expect(buildSearchQuery({ name: 'Charizard', set_id: '', rarity: undefined })).toBe(
      'name=Charizard',
    )
  })

  it('URL-encodes special characters', () => {
    expect(buildSearchQuery({ name: "Farfetch'd & Mr. Mime" })).toContain(
      'name=Farfetch%27d+%26+Mr.+Mime',
    )
  })
})

describe('searchInventory', () => {
  const empty: InventorySearchResult = { items: [], total: 0 }

  it('calls GET /inventory/search with the built query string', async () => {
    mockedApiFetch.mockResolvedValue(empty)
    await searchInventory({ name: 'Charizard' })
    expect(mockedApiFetch.mock.calls[0][0]).toBe('/inventory/search?name=Charizard')
  })

  it('hits the bare path when there are no filters', async () => {
    mockedApiFetch.mockResolvedValue(empty)
    await searchInventory({})
    expect(mockedApiFetch.mock.calls[0][0]).toBe('/inventory/search')
  })

  it('returns the backend result untouched ({items, total})', async () => {
    const result: InventorySearchResult = { items: [makeRawItem()], total: 1 }
    mockedApiFetch.mockResolvedValue(result)
    await expect(searchInventory({})).resolves.toEqual(result)
  })

  it('forwards a bearer token to apiFetch when given', async () => {
    mockedApiFetch.mockResolvedValue(empty)
    await searchInventory({}, { token: 'jwt-123' })
    expect(mockedApiFetch).toHaveBeenCalledWith(
      '/inventory/search',
      expect.objectContaining({ token: 'jwt-123' }),
    )
  })
})

describe('sendChat', () => {
  it('POSTs {message, history} to /chat/ (trailing slash — no 307 round-trip)', async () => {
    mockedApiFetch.mockResolvedValue({ reply: 'hi' })
    await sendChat('How much is Charizard?', [
      { role: 'user', content: 'hello' },
      { role: 'assistant', content: 'hi there' },
    ])
    expect(mockedApiFetch).toHaveBeenCalledWith(
      '/chat/',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({
          message: 'How much is Charizard?',
          history: [
            { role: 'user', content: 'hello' },
            { role: 'assistant', content: 'hi there' },
          ],
        }),
      }),
    )
  })

  it('forwards a bearer token to apiFetch when given', async () => {
    mockedApiFetch.mockResolvedValue({ reply: 'hi' })
    await sendChat('hello', [], { token: 'jwt-123' })
    expect(mockedApiFetch).toHaveBeenCalledWith(
      '/chat/',
      expect.objectContaining({ token: 'jwt-123' }),
    )
  })
})

describe('formatPrice', () => {
  it('formats a decimal string from the backend as USD', () => {
    expect(formatPrice('250.40')).toBe('$250.40')
    expect(formatPrice('12.5')).toBe('$12.50')
  })

  it('returns a friendly fallback for null/undefined/garbage', () => {
    expect(formatPrice(null)).toBe('Price N/A')
    expect(formatPrice(undefined)).toBe('Price N/A')
    expect(formatPrice('not-a-number')).toBe('Price N/A')
  })
})

describe('itemTitle', () => {
  it('uses the catalog name when the card summary is present', () => {
    expect(itemTitle(makeRawItem())).toBe('Charizard')
  })

  it('falls back to the card_id when the catalog row is missing', () => {
    expect(itemTitle(makeRawItem({ card: null }))).toBe('base1-4')
  })
})

describe('conditionLabel', () => {
  it('is the condition grade for raw items', () => {
    expect(conditionLabel(makeRawItem())).toBe('NM')
  })

  it('is company + grade for graded items', () => {
    expect(conditionLabel(makeGradedItem())).toBe('PSA 9.5')
  })
})

describe('itemKey', () => {
  it('is unique across variants of the same card', () => {
    const keys = [
      itemKey(makeRawItem({ condition: 'NM' })),
      itemKey(makeRawItem({ condition: 'LP' })),
      itemKey(makeRawItem({ finish: 'reverseHolofoil' })),
      itemKey(makeGradedItem()),
      itemKey(makeGradedItem({ cert_number: '99999999' })),
    ]
    expect(new Set(keys).size).toBe(keys.length)
  })
})
