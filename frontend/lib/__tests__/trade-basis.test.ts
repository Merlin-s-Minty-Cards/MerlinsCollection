import { describe, it, expect } from 'vitest'
import { availableModes, canConfirmBasis, type BasisMode } from '../trade-basis'

const CASH_TOOLTIP = 'Unavailable while the trade includes cash — use Manual.'

describe('availableModes', () => {
  it('returns all three modes enabled when hasCash is false', () => {
    const modes = availableModes(false)
    expect(modes).toHaveLength(3)
    for (const m of modes) {
      expect(m.disabled).toBe(false)
      expect(m.reason).toBeNull()
    }
    expect(modes.map((m) => m.mode)).toEqual(['transfer', 'split', 'manual'])
  })

  it('disables transfer and split with tooltip when hasCash is true', () => {
    const modes = availableModes(true)
    expect(modes).toHaveLength(3)

    const transfer = modes.find((m) => m.mode === 'transfer')!
    expect(transfer.disabled).toBe(true)
    expect(transfer.reason).toBe(CASH_TOOLTIP)

    const split = modes.find((m) => m.mode === 'split')!
    expect(split.disabled).toBe(true)
    expect(split.reason).toBe(CASH_TOOLTIP)

    const manual = modes.find((m) => m.mode === 'manual')!
    expect(manual.disabled).toBe(false)
    expect(manual.reason).toBeNull()
  })
})

describe('canConfirmBasis', () => {
  it('transfer without cash and empty manual basis returns true', () => {
    expect(canConfirmBasis('transfer', false, '')).toBe(true)
  })

  it('transfer with cash returns false', () => {
    expect(canConfirmBasis('transfer', true, '')).toBe(false)
  })

  it('split with cash returns false even with an amount', () => {
    expect(canConfirmBasis('split', true, '25')).toBe(false)
  })

  it('manual with cash but no amount returns false', () => {
    expect(canConfirmBasis('manual', true, '')).toBe(false)
  })

  it('manual with cash and a valid amount returns true', () => {
    expect(canConfirmBasis('manual', true, '25')).toBe(true)
  })

  it('manual with zero basis is legitimate (worthless bulk trade)', () => {
    // This is the critical zero-basis case: a card-only trade of worthless
    // bulk can have a zero pool. '0' is NOT empty.
    expect(canConfirmBasis('manual', false, '0')).toBe(true)
  })

  it('manual with non-numeric input returns false', () => {
    expect(canConfirmBasis('manual', false, 'abc')).toBe(false)
  })

  it('manual without cash and a valid amount returns true', () => {
    expect(canConfirmBasis('manual', false, '10.50')).toBe(true)
  })

  it('split without cash returns true', () => {
    expect(canConfirmBasis('split', false, '')).toBe(true)
  })
})
