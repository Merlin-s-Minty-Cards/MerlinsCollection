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
  getPublicShows,
  getFeaturedCards,
  showBadge,
  formatShowDate,
  isSafeImageUrl,
  type PublicShowsResponse,
  type FeaturedCardsResponse,
} from '@/lib/public'

const mockedApiFetch = vi.mocked(apiFetch)

beforeEach(() => {
  vi.clearAllMocks()
})

describe('getPublicShows', () => {
  it('requests /public/shows and returns the parsed body', async () => {
    const body: PublicShowsResponse = {
      upcoming: [{ name: 'Seattle Trading Card Con', date: '2026-08-14', venue: 'Convention Center', city: 'Seattle, WA' }],
      past: [{ name: 'Lloyd Center Show', date: '2026-07-18', venue: null, city: null }],
    }
    mockedApiFetch.mockResolvedValue(body)

    await expect(getPublicShows()).resolves.toEqual(body)
    expect(mockedApiFetch.mock.calls[0][0]).toBe('/public/shows')
  })
})

describe('getFeaturedCards', () => {
  it('requests /public/featured-cards and returns the parsed body', async () => {
    const body: FeaturedCardsResponse = {
      cards: [{ name: 'Lugia', image_url: 'https://images.pokemontcg.io/neo3/9.png' }],
    }
    mockedApiFetch.mockResolvedValue(body)

    await expect(getFeaturedCards()).resolves.toEqual(body)
    expect(mockedApiFetch.mock.calls[0][0]).toBe('/public/featured-cards')
  })
})

describe('showBadge', () => {
  it('derives an uppercase month + zero-padded day from an ISO date', () => {
    expect(showBadge('2026-08-14')).toEqual({ month: 'AUG', day: '14' })
    expect(showBadge('2026-01-04')).toEqual({ month: 'JAN', day: '04' })
  })

  it('does not drift across a timezone boundary (parses the date parts directly)', () => {
    // new Date("2026-01-01") is UTC midnight and would render Dec 31 in the US;
    // showBadge must parse the string parts so the badge shows JAN 01.
    expect(showBadge('2026-01-01')).toEqual({ month: 'JAN', day: '01' })
  })
})

describe('formatShowDate', () => {
  it('formats a human-readable date label', () => {
    expect(formatShowDate('2026-08-14')).toBe('Aug 14, 2026')
    expect(formatShowDate('2026-01-04')).toBe('Jan 4, 2026')
  })

  it('does not render "NaN" for a malformed/empty date', () => {
    expect(formatShowDate('')).not.toContain('NaN')
    expect(showBadge('')).toEqual({ month: '', day: '' })
  })
})

describe('isSafeImageUrl', () => {
  it('accepts https on the allowlisted pokemontcg host', () => {
    expect(isSafeImageUrl('https://images.pokemontcg.io/neo3/9.png')).toBe(true)
  })

  it('accepts https on the allowlisted tcgdex host', () => {
    expect(isSafeImageUrl('https://assets.tcgdex.net/en/swsh/swsh1/1/high.webp')).toBe(true)
  })

  it('rejects non-allowlisted hosts, non-https, and malformed URLs', () => {
    expect(isSafeImageUrl('https://evil.example.com/x.png')).toBe(false)
    expect(isSafeImageUrl('http://images.pokemontcg.io/x.png')).toBe(false)
    expect(isSafeImageUrl('/images/x.png')).toBe(false)
    expect(isSafeImageUrl('not a url')).toBe(false)
    expect(isSafeImageUrl('')).toBe(false)
  })
})
