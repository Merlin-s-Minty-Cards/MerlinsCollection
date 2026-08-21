/**
 * Pure logic — no DOM. Runs in `node` rather than the default jsdom; see
 * lib/__tests__/buy-form.test.ts for why.
 *
 * @vitest-environment node
 */
import { describe, it, expect } from 'vitest'
import { parseMoney, formatMoneyInput, formatMoney } from '../money'

describe('parseMoney', () => {
  // ---- THE trap this module exists for -----------------------------------
  // parseFloat("1,300") is 1 — not NaN — so it slips past every isNaN guard in
  // this codebase and turns a loud 500 into a silent $1,299 loss. If you are
  // reading this because a test went red, the fix is NEVER to reach for
  // parseFloat. See docs/plans/rfc-0010/t0-money-input-and-partial-write.md.
  it('does not use parseFloat: "1,300" is 1300, never 1', () => {
    expect(parseMoney('1,300')).toBe(1300)
    expect(parseMoney('1,300')).not.toBe(1)
  })

  it('parses a plain integer', () => {
    expect(parseMoney('1300')).toBe(1300)
  })

  it('parses a plain decimal', () => {
    expect(parseMoney('1300.50')).toBe(1300.5)
  })

  it('parses a leading-point decimal', () => {
    expect(parseMoney('.5')).toBe(0.5)
  })

  it('parses zero — a free card is a real cost, and 0 is not null', () => {
    expect(parseMoney('0')).toBe(0)
    expect(parseMoney('0.00')).toBe(0)
  })

  it('strips thousands separators, including several of them', () => {
    expect(parseMoney('1,300.50')).toBe(1300.5)
    expect(parseMoney('12,345,678')).toBe(12345678)
  })

  it('strips a currency symbol and surrounding whitespace', () => {
    expect(parseMoney('$40')).toBe(40)
    expect(parseMoney('$ 1,300')).toBe(1300)
    expect(parseMoney('  40  ')).toBe(40)
  })

  it('accepts a trailing point, which is unambiguous', () => {
    expect(parseMoney('40.')).toBe(40)
    expect(parseMoney('40.0')).toBe(40)
  })

  it('rejects a bad grouping rather than guessing: "1,30" is null', () => {
    expect(parseMoney('1,30')).toBeNull()
    expect(parseMoney('1,5')).toBeNull()
  })

  it('rejects ambiguous multi-separator input', () => {
    expect(parseMoney('1.2.3')).toBeNull()
    expect(parseMoney('1,2,3')).toBeNull()
  })

  it('rejects a negative amount at the parser, not at each caller', () => {
    expect(parseMoney('-5')).toBeNull()
    expect(parseMoney('-1,300.00')).toBeNull()
  })

  it('rejects anything that is not a number', () => {
    expect(parseMoney('abc')).toBeNull()
    expect(parseMoney('')).toBeNull()
    expect(parseMoney('   ')).toBeNull()
    expect(parseMoney('$')).toBeNull()
  })

  it('rejects exponent notation — nobody types 1e3 into a price field', () => {
    expect(parseMoney('1e3')).toBeNull()
  })
})

describe('formatMoneyInput', () => {
  it('returns the canonical two-decimal string for the input field', () => {
    expect(formatMoneyInput(1300.5)).toBe('1300.50')
    expect(formatMoneyInput(1300)).toBe('1300.00')
    expect(formatMoneyInput(0)).toBe('0.00')
  })

  it('does not group — the field has to round-trip through parseMoney', () => {
    expect(formatMoneyInput(12345678)).toBe('12345678.00')
    expect(parseMoney(formatMoneyInput(12345678))).toBe(12345678)
  })
})

describe('formatMoney', () => {
  it('renders a grouped, prefixed display string', () => {
    expect(formatMoney(1300)).toBe('$1,300.00')
    expect(formatMoney(1300.5)).toBe('$1,300.50')
    expect(formatMoney(40)).toBe('$40.00')
  })
})
