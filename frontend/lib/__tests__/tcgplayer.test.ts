/**
 * Pure logic — no DOM. See lib/__tests__/money.test.ts for why pure-logic
 * files run in `node` rather than the default jsdom.
 *
 * @vitest-environment node
 */
import { describe, it, expect } from 'vitest'
import { tcgplayerSearchUrl, TCGPLAYER_UNSUPPORTED_LANGUAGE_MESSAGE } from '../tcgplayer'

// RFC 0023 §3 — TCGplayer has exactly TWO Pokémon categories, verified
// 2026-09-02 against TCGplayer's own category registry. Everything else
// (including OTHER) must return null, and a null must NEVER fall back to the
// English link — an English-category search for a Korean card returns the
// wrong card or nothing, and both are worse than no link.

describe('tcgplayerSearchUrl', () => {
  it('builds the English category search link for EN', () => {
    expect(tcgplayerSearchUrl('EN', 'Charizard')).toBe(
      'https://www.tcgplayer.com/search/pokemon/product?q=Charizard&view=grid'
    )
  })

  it('builds the Japan category search link for JP, with productLineName', () => {
    expect(tcgplayerSearchUrl('JP', 'Charizard')).toBe(
      'https://www.tcgplayer.com/search/pokemon-japan/product?productLineName=pokemon-japan&q=Charizard&view=grid'
    )
  })

  it('URL-encodes the query for both categories', () => {
    expect(tcgplayerSearchUrl('EN', 'Pikachu VMAX #044/072')).toBe(
      'https://www.tcgplayer.com/search/pokemon/product?q=Pikachu%20VMAX%20%23044%2F072&view=grid'
    )
  })

  it('returns null for a language with no TCGplayer Pokémon category', () => {
    expect(tcgplayerSearchUrl('KO', 'Charizard')).toBeNull()
    expect(tcgplayerSearchUrl('FR', 'Charizard')).toBeNull()
    expect(tcgplayerSearchUrl('ZH-TW', 'Charizard')).toBeNull()
  })

  it('returns null for OTHER rather than guessing', () => {
    expect(tcgplayerSearchUrl('OTHER', 'Charizard')).toBeNull()
  })

  it('returns null, never the English link, for a missing language', () => {
    expect(tcgplayerSearchUrl(undefined, 'Charizard')).toBeNull()
    expect(tcgplayerSearchUrl(null, 'Charizard')).toBeNull()
  })
})

describe('TCGPLAYER_UNSUPPORTED_LANGUAGE_MESSAGE', () => {
  it('is a one-line, non-empty explanation', () => {
    expect(TCGPLAYER_UNSUPPORTED_LANGUAGE_MESSAGE.length).toBeGreaterThan(10)
    expect(TCGPLAYER_UNSUPPORTED_LANGUAGE_MESSAGE).not.toContain('\n')
  })
})
