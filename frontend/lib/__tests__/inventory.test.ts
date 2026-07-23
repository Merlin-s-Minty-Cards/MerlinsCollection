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
// Wire format after the Database-Redesign: each item has its own `item_id`
// (the stable identity), `card_id` is OPTIONAL (absent for sealed/bulk and for
// unmatched cards), and `quantity` is GONE (one record = one physical unit).
export function makeRawItem(overrides: Record<string, unknown> = {}): InventoryItem {
  return {
    kind: 'raw',
    item_id: '01JRAWCHARIZARDNM0000000001',
    card_id: 'base1-4',
    listed_price: '250.00',
    current_market_value: '300.00',
    acquired_at: '2026-04-01',
    finish: 'holofoil',
    condition: 'NM',
    condition_modifier: null,
    factory_sealed: false,
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
    item_id: '01JGRADEDCHARIZARDPSA000001',
    card_id: 'base1-4',
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

// Sealed products are customer-visible (backend `_CUSTOMER_KINDS`) but have NO
// catalog card, no `card_id`, and no condition — the redesign added this kind.
export function makeSealedItem(overrides: Record<string, unknown> = {}): InventoryItem {
  return {
    kind: 'sealed',
    item_id: '01JSEALEDBOOSTERBOX00000001',
    listed_price: '120.00',
    current_market_value: '140.00',
    acquired_at: '2026-04-01',
    product_name: 'Scarlet & Violet Booster Box',
    product_type: 'booster_box',
    card: null,
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

  it('uses the product_name for a sealed product (no card, no card_id)', () => {
    expect(itemTitle(makeSealedItem())).toBe('Scarlet & Violet Booster Box')
  })

  it('falls back to the item_id when neither card nor card_id is present', () => {
    expect(itemTitle(makeRawItem({ card: null, card_id: undefined }))).toBe(
      '01JRAWCHARIZARDNM0000000001',
    )
  })
})

describe('conditionLabel', () => {
  it('is the condition grade for raw items', () => {
    expect(conditionLabel(makeRawItem())).toBe('NM')
  })

  it('appends the +/- modifier for raw items that carry one', () => {
    expect(conditionLabel(makeRawItem({ condition: 'LP', condition_modifier: '+' }))).toBe('LP+')
    expect(conditionLabel(makeRawItem({ condition: 'NM', condition_modifier: '-' }))).toBe('NM-')
  })

  it('is company + grade for graded items', () => {
    expect(conditionLabel(makeGradedItem())).toBe('PSA 9.5')
  })

  it('is a human-readable product type for sealed products', () => {
    expect(conditionLabel(makeSealedItem())).toBe('Booster Box')
    expect(conditionLabel(makeSealedItem({ product_type: 'etb' }))).toBe('Elite Trainer Box')
  })
})

describe('itemKey', () => {
  it('is the item_id (the stable per-unit identity)', () => {
    expect(itemKey(makeRawItem())).toBe('01JRAWCHARIZARDNM0000000001')
  })

  it('is unique across items — even the same card in different physical units', () => {
    const keys = [
      itemKey(makeRawItem({ item_id: 'itm-1' })),
      itemKey(makeRawItem({ item_id: 'itm-2' })),
      itemKey(makeGradedItem({ item_id: 'itm-3' })),
      itemKey(makeSealedItem({ item_id: 'itm-4' })),
    ]
    expect(new Set(keys).size).toBe(keys.length)
  })
})
