/**
 * Pure logic — no DOM. Runs in `node` rather than the default jsdom:
 * constructing a jsdom per file was the single largest cost in this
 * suite (215s cumulative `environment` time against 55s of actual tests).
 * If this file ever renders a component or touches window/document,
 * delete this docblock rather than stubbing the DOM by hand.
 *
 * @vitest-environment node
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@/lib/api', () => ({ apiFetch: vi.fn() }))

import { apiFetch } from '@/lib/api'
import {
  buildSearchQuery,
  searchInventory,
  getInventorySummary,
  sendChat,
  formatPrice,
  itemTitle,
  itemKey,
  conditionLabel,
  type InventoryItem,
  type InventorySearchResult,
  type InventorySummary,
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
      market_price: null,
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
      market_price: null,
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

  it('sends the language filter using the backend param name', () => {
    expect(new URLSearchParams(buildSearchQuery({ language: 'JP' })).get('language')).toBe('JP')
    expect(new URLSearchParams(buildSearchQuery({ language: 'EN' })).get('language')).toBe('EN')
  })

  it('omits language when it is empty (the "All languages" choice)', () => {
    expect(new URLSearchParams(buildSearchQuery({ language: '' })).get('language')).toBeNull()
  })

  it('URL-encodes special characters', () => {
    expect(buildSearchQuery({ name: "Farfetch'd & Mr. Mime" })).toContain(
      'name=Farfetch%27d+%26+Mr.+Mime',
    )
  })
})

describe('searchInventory', () => {
  const empty: InventorySearchResult = { items: [], total: 0, hidden_no_price: 0 }

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

  it('returns the backend result untouched ({items, total, hidden_no_price})', async () => {
    // hidden_no_price (Phase 12, owner decision 2) is part of the wire
    // contract: a price-bounded search excludes items with no resolvable
    // price and reports how many, so the UI can surface them rather than
    // dropping them invisibly. It must survive the client untouched.
    const result: InventorySearchResult = {
      items: [makeRawItem()],
      total: 1,
      hidden_no_price: 3,
    }
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

describe('getInventorySummary', () => {
  const summary: InventorySummary = { cards_in_vault: 312, est_value: '48231.50', sets_tracked: 27 }

  it('calls GET /inventory/summary and returns the parsed body', async () => {
    mockedApiFetch.mockResolvedValue(summary)
    await expect(getInventorySummary()).resolves.toEqual(summary)
    expect(mockedApiFetch.mock.calls[0][0]).toBe('/inventory/summary')
  })

  it('forwards a bearer token to apiFetch when given', async () => {
    mockedApiFetch.mockResolvedValue(summary)
    await getInventorySummary({ token: 'jwt-123' })
    expect(mockedApiFetch).toHaveBeenCalledWith(
      '/inventory/summary',
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

  it('round-trips panel item IDs without sending client-authored card data', async () => {
    mockedApiFetch.mockResolvedValue({
      reply: 'Panel retained.',
      artifacts: [],
      // Decision 23 removed the tri-state `open`; open/closed is inferred from cards.
      panel: { cards: [], truncated: false },
    })

    await sendChat(
      'What is still open?',
      [],
      ['item-1', 'item-2'],
      { token: 'jwt-123' },
    )

    expect(mockedApiFetch).toHaveBeenCalledWith(
      '/chat/',
      expect.objectContaining({
        body: JSON.stringify({
          message: 'What is still open?',
          history: [],
          panel_item_ids: ['item-1', 'item-2'],
        }),
        token: 'jwt-123',
      }),
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

  it('falls back to the item_id when neither card, card_id, nor display_name is present', () => {
    expect(itemTitle(makeRawItem({ card: null, card_id: undefined }))).toBe(
      '01JRAWCHARIZARDNM0000000001',
    )
  })

  // ---- RFC 0001: notes-derived display_name fallback (RED) ----
  // docs/rfcs/0001-inventory-catalog-relink-and-display-fallback.md, section C.4.
  // New precedence: card?.name ?? display_name ?? card_id ?? item_id. display_name
  // ranks above the card_id and, critically, above the item_id ULID — the bug the
  // owner reported ("chat/filter results show a ULID instead of a card name").

  it('falls back to display_name when card and card_id are null', () => {
    expect(
      itemTitle(
        makeRawItem({ card: null, card_id: null, display_name: 'Dragonair #181' }),
      ),
    ).toBe('Dragonair #181')
  })

  it('prefers display_name over the item_id ULID', () => {
    const title = itemTitle(
      makeRawItem({ card: null, card_id: null, display_name: 'Dragonair #181' }),
    )
    expect(title).not.toBe('01JRAWCHARIZARDNM0000000001')
  })

  it('still prefers the catalog name over a present display_name', () => {
    // A matched item's catalog name is authoritative even if display_name was
    // also set (mirrors the backend/MCP precedence tests for the same rule).
    expect(
      itemTitle(makeRawItem({ display_name: 'Stale #99' })),
    ).toBe('Charizard')
  })

  // ---- T10: admin-authored display_name_override (RED) ----
  // docs/plans/rfc-0008/t10-jp-english-names.md. Precedence becomes
  // display_name_override ?? card?.name ?? display_name ?? card_id ?? item_id.
  // The override is the ONLY thing that outranks the catalog name — it exists
  // because a JP card's catalog row is in Japanese script and the customer
  // cannot read it. Everything below the override is unchanged.

  it('prefers an admin display_name_override over the catalog name', () => {
    expect(
      itemTitle(
        makeRawItem({
          language: 'JP',
          display_name_override: 'Chespin',
          card: { ...(makeRawItem().card!), name: 'ハルクジラ' },
        }),
      ),
    ).toBe('Chespin')
  })

  it('renders the native catalog name for a JP item with no override', () => {
    // Unchanged fallback: without an admin correction the catalog name stands,
    // even in Japanese script. No override is invented for us.
    expect(
      itemTitle(
        makeRawItem({
          language: 'JP',
          card: { ...(makeRawItem().card!), name: 'ハルクジラ' },
        }),
      ),
    ).toBe('ハルクジラ')
  })

  it('keeps using the catalog name for an EN item with no override', () => {
    // The regression guard for the ~249 English items: promoting the messy
    // sheet-derived display_name ahead of the catalog name would downgrade
    // every one of them ("Magnezone first #68" instead of "Magnezone").
    expect(
      itemTitle(makeRawItem({ display_name: 'Charizard first #4' })),
    ).toBe('Charizard')
  })

  it('falls back to display_name for an unmatched item with no override', () => {
    expect(
      itemTitle(
        makeRawItem({
          card: null,
          card_id: null,
          display_name: 'Dragonair #181',
          display_name_override: null,
        }),
      ),
    ).toBe('Dragonair #181')
  })

  it('prefers an override over a sealed product_name', () => {
    // The sealed short-circuit must not swallow the override — correcting a
    // mis-typed product name is the same admin action as correcting a card.
    expect(
      itemTitle(makeSealedItem({ display_name_override: 'Japanese ETB' })),
    ).toBe('Japanese ETB')
  })

  it('ignores a blank or whitespace-only override rather than rendering nothing', () => {
    // `??` only guards null/undefined. An empty string reaching the tile — from
    // an un-normalized row or an in-flight edit — would render a NAMELESS card.
    expect(itemTitle(makeRawItem({ display_name_override: '' }))).toBe('Charizard')
    expect(itemTitle(makeRawItem({ display_name_override: '   ' }))).toBe('Charizard')
  })

  it('trims a padded override before displaying it', () => {
    expect(
      itemTitle(makeRawItem({ display_name_override: '  Chespin  ' })),
    ).toBe('Chespin')
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
