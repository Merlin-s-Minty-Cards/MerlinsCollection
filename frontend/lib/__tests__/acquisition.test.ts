/**
 * RFC 0024 T1 — the TypeScript mirror of
 * backend/src/merlins_collection/services/acquisition.py's acquisition_ratio.
 *
 * Pure logic — no DOM. Runs in `node` rather than the default jsdom; see
 * lib/__tests__/money.test.ts for why.
 *
 * @vitest-environment node
 */
import { readFileSync } from 'node:fs'
import { describe, it, expect } from 'vitest'
import { acquisitionRatio, formatRatio, ratioTone } from '../acquisition'

describe('acquisitionRatio', () => {
  it('computes the percent ratio of market to cost', () => {
    expect(acquisitionRatio('100.00', '32.00')).toBe(312.5)
  })

  it('accepts numbers as well as strings', () => {
    expect(acquisitionRatio(100, 32)).toBe(312.5)
  })

  it('is null when market value at purchase is absent', () => {
    expect(acquisitionRatio(null, '32.00')).toBeNull()
    expect(acquisitionRatio(undefined, '32.00')).toBeNull()
  })

  it('is null when cost basis is absent', () => {
    expect(acquisitionRatio('100.00', null)).toBeNull()
    expect(acquisitionRatio('100.00', undefined)).toBeNull()
  })

  it('is null when cost basis is zero — a free card is not infinite', () => {
    expect(acquisitionRatio('100.00', 0)).toBeNull()
    expect(acquisitionRatio('100.00', '0')).toBeNull()
  })

  it('is null when both cost and market are zero', () => {
    expect(acquisitionRatio(0, 0)).toBeNull()
  })

  it('rounds a repeating decimal to two places', () => {
    expect(acquisitionRatio('10.00', '3.00')).toBe(333.33)
  })

  it('a large ratio stays exact when it divides evenly', () => {
    expect(acquisitionRatio('123456.78', '0.03')).toBe(411522600)
  })

  it('a below-market price renders as a ratio under 100', () => {
    expect(acquisitionRatio('50.00', '100.00')).toBe(50)
  })
})

describe('formatRatio', () => {
  it('renders the rounded integer percent', () => {
    expect(formatRatio(312.5)).toBe('313%')
  })

  it('is null for a null ratio — no chip at all, not a grey zero', () => {
    expect(formatRatio(null)).toBeNull()
  })
})

describe('ratioTone', () => {
  it('is good at and above 200%', () => {
    expect(ratioTone(200)).toBe('good')
    expect(ratioTone(312.5)).toBe('good')
  })

  it('is neutral from 100% up to (not including) 200%', () => {
    expect(ratioTone(100)).toBe('neutral')
    expect(ratioTone(199.99)).toBe('neutral')
  })

  it('is bad below 100% — paid over market', () => {
    expect(ratioTone(99.99)).toBe('bad')
    expect(ratioTone(50)).toBe('bad')
  })

  it('is null for a null ratio — no chip at all', () => {
    expect(ratioTone(null)).toBeNull()
  })
})

// ---- cross-boundary pin against the Python side -----------------------------
//
// Both this file and backend/tests/test_cross_boundary.py load the SAME fixture
// (shared/test-fixtures/acquisition-ratio-cases.json) and assert their own
// language's implementation against it. See that file's comment for why this
// is a shared-fixture pin rather than a source-parsing one: acquisition_ratio
// is a computed function, not a literal constant a regex could extract.

interface AcquisitionRatioCase {
  name: string
  market: string | null
  cost: string | null
  expected: string | null
}

function loadAcquisitionRatioCases(): AcquisitionRatioCase[] {
  const raw = readFileSync(
    new URL('../../../shared/test-fixtures/acquisition-ratio-cases.json', import.meta.url),
    'utf-8'
  )
  return JSON.parse(raw).cases
}

describe('acquisitionRatio matches the shared cross-boundary fixture', () => {
  const cases = loadAcquisitionRatioCases()

  it('the fixture has not lost cases', () => {
    expect(cases.length).toBeGreaterThanOrEqual(7)
  })

  for (const c of cases) {
    it(`case: ${c.name}`, () => {
      const actual = acquisitionRatio(c.market, c.cost)
      const expected = c.expected === null ? null : Number(c.expected)
      expect(actual).toBe(expected)
    })
  }
})
