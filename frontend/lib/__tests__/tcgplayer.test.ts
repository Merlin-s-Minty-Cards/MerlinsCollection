/**
 * Pure logic — no DOM. See lib/__tests__/money.test.ts for why pure-logic
 * files run in `node` rather than the default jsdom.
 *
 * @vitest-environment node
 */
import { describe, it, expect } from 'vitest'
import { tcgplayerSearchUrl, TCGPLAYER_UNSUPPORTED_LANGUAGE_MESSAGE, safeTcgHref } from '../tcgplayer'

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

// RFC 0023 follow-ups #3 — `tcg_url` is admin-typed free text rendered as an
// `<a href>` on three admin surfaces. A `javascript:` value is a stored-XSS
// sink that fires on one click, so only a real http(s) URL may ever back a
// link target. Delegates to `safeHref` (lib/safe-href.ts, already tested
// against the same class of trick) rather than a second implementation.
describe('safeTcgHref', () => {
  it('accepts absolute http and https URLs, unchanged', () => {
    expect(safeTcgHref('https://www.tcgplayer.com/product/12345')).toBe(
      'https://www.tcgplayer.com/product/12345',
    )
    expect(safeTcgHref('http://www.tcgplayer.com/product/12345')).toBe(
      'http://www.tcgplayer.com/product/12345',
    )
  })

  it('rejects a javascript: URI', () => {
    expect(safeTcgHref('javascript:alert(1)')).toBeNull()
  })

  it('rejects a scheme-relative or bare string', () => {
    expect(safeTcgHref('//evil.example.com')).toBeNull()
    expect(safeTcgHref('not a url')).toBeNull()
  })

  it('rejects a mailto/tel URI even though safeHref allows those schemes generally', () => {
    // safeHref is shared with CMS-authored links, where mailto:/tel: are
    // legitimate; neither is ever a TCGplayer product/search link.
    expect(safeTcgHref('mailto:someone@example.com')).toBeNull()
    expect(safeTcgHref('tel:+15555550100')).toBeNull()
  })

  it('rejects null, undefined and non-string values', () => {
    expect(safeTcgHref(null)).toBeNull()
    expect(safeTcgHref(undefined)).toBeNull()
    expect(safeTcgHref(42)).toBeNull()
  })
})
