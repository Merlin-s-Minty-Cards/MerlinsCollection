/**
 * RFC 0010 T8 — dates stop rendering a day early.
 *
 * Pure logic — no DOM. Runs in `node` rather than the default jsdom; see
 * lib/__tests__/buy-form.test.ts for why.
 *
 * @vitest-environment node
 */
import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from 'vitest'
import {
  BUSINESS_TIME_ZONE,
  formatISODate,
  formatTimestamp,
  parseISODateLocal,
  todayLocal,
} from '@/lib/dates'
import { pinTimeZone, PACIFIC } from './_timezone'

// EVERY test below is pinned to a specific zone, and the ones that matter are
// pinned to a NEGATIVE-offset one. Without that pin these all pass against the
// unfixed code, because `new Date("2026-08-10")` is UTC midnight and only slips
// backwards a day west of Greenwich. A UTC CI box would report green while the
// owner reads Aug 9 on their screen.

describe('formatISODate — a date-only string renders as itself, in every zone', () => {
  let restore: () => void
  afterEach(() => restore?.())

  it("renders 2026-08-10 as Aug 10 in America/Los_Angeles — the owner's bug", () => {
    restore = pinTimeZone(PACIFIC)
    expect(formatISODate('2026-08-10')).toBe('Aug 10, 2026')
  })

  it('renders 2026-08-10 as Aug 10 in America/New_York', () => {
    restore = pinTimeZone('America/New_York')
    expect(formatISODate('2026-08-10')).toBe('Aug 10, 2026')
  })

  it('renders 2026-08-10 as Aug 10 in UTC — no regression for a UTC user', () => {
    restore = pinTimeZone('UTC')
    expect(formatISODate('2026-08-10')).toBe('Aug 10, 2026')
  })

  it('honours a caller-supplied Intl option set', () => {
    restore = pinTimeZone(PACIFIC)
    expect(formatISODate('2026-08-10', { month: 'short', day: 'numeric' })).toBe('Aug 10')
  })
})

describe('formatISODate — defensive about whatever the API sent', () => {
  let restore: () => void
  afterEach(() => restore?.())

  it('renders a full timestamp as its instant, never "Invalid Date"', () => {
    // The documented rule: a value carrying a time and an offset is a real
    // instant, so it is delegated to Date parsing and rendered in the local
    // zone. 22:00Z on Aug 10 is 3pm Pacific the SAME day.
    restore = pinTimeZone(PACIFIC)
    expect(formatISODate('2026-08-10T22:00:00Z')).toBe('Aug 10, 2026')
  })

  it('returns junk unchanged rather than rendering "Invalid Date"', () => {
    restore = pinTimeZone(PACIFIC)
    expect(formatISODate('not-a-date')).toBe('not-a-date')
  })

  it('returns an empty string for an empty string', () => {
    restore = pinTimeZone(PACIFIC)
    expect(formatISODate('')).toBe('')
  })
})

describe('parseISODateLocal', () => {
  let restore: () => void
  afterEach(() => restore?.())

  it('yields LOCAL midnight, not UTC midnight', () => {
    restore = pinTimeZone(PACIFIC)
    const d = parseISODateLocal('2026-08-10')
    expect(d).not.toBeNull()
    expect(d!.getFullYear()).toBe(2026)
    expect(d!.getMonth()).toBe(7)
    expect(d!.getDate()).toBe(10)
    expect(d!.getHours()).toBe(0)
    // The whole bug in one assertion: `new Date("2026-08-10")` is this value.
    expect(d!.getTime()).not.toBe(Date.parse('2026-08-10T00:00:00Z'))
  })

  it('returns null for anything that is not a date-only string', () => {
    restore = pinTimeZone(PACIFIC)
    expect(parseISODateLocal('2026-08-10T22:00:00Z')).toBeNull()
    expect(parseISODateLocal('')).toBeNull()
    expect(parseISODateLocal('nonsense')).toBeNull()
  })
})

describe('todayLocal — the second bug: "today" was computed in UTC', () => {
  let restore: () => void

  beforeAll(() => {
    restore = pinTimeZone(PACIFIC)
  })
  afterAll(() => {
    restore()
    vi.useRealTimers()
  })
  afterEach(() => vi.useRealTimers())

  it('returns 2026-08-10 at 6:30pm Pacific on Aug 10 — not tomorrow', () => {
    // The money bug, as a test. 6:30pm PDT on Aug 10 is 01:30Z on Aug 11, so
    // `new Date().toISOString().split('T')[0]` answers "2026-08-11" and every
    // transaction typed at an evening show is dated to the following day.
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-08-11T01:30:00Z'))
    expect(todayLocal()).toBe('2026-08-10')
  })

  it('returns the same calendar day at 2am Pacific', () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-08-10T09:00:00Z')) // 2am PDT, Aug 10
    expect(todayLocal()).toBe('2026-08-10')
  })

  it('never answers with the UTC date when the two differ', () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-08-11T01:30:00Z'))
    const utcDate = new Date().toISOString().split('T')[0]
    expect(utcDate).toBe('2026-08-11') // the shape of the old code, pinned
    expect(todayLocal()).not.toBe(utcDate)
  })
})

describe('BUSINESS_TIME_ZONE', () => {
  it('is an IANA zone name, never a fixed offset', () => {
    // Pacific is PDT (-7) in August and PST (-8) in January, so a hardcoded
    // -08:00 is wrong for about eight months a year, every summer show included.
    expect(BUSINESS_TIME_ZONE).toBe('America/Los_Angeles')
    expect(BUSINESS_TIME_ZONE).not.toMatch(/[+-]\d{2}:?\d{2}/)
  })
})

describe('formatTimestamp — a real instant, in the local zone', () => {
  let restore: () => void
  afterEach(() => restore?.())

  it('renders an instant in the local zone', () => {
    restore = pinTimeZone(PACIFIC)
    // 01:30Z Aug 11 is 6:30pm Pacific on Aug 10.
    expect(formatTimestamp('2026-08-11T01:30:00Z')).toMatch(/Aug 10, 2026/)
  })

  it('returns junk unchanged rather than "Invalid Date"', () => {
    restore = pinTimeZone(PACIFIC)
    expect(formatTimestamp('nonsense')).toBe('nonsense')
    expect(formatTimestamp('')).toBe('')
  })
})
