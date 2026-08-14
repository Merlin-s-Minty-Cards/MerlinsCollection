/**
 * Pure logic — no DOM. Runs in `node` rather than the default jsdom:
 * constructing a jsdom per file was the single largest cost in this
 * suite (215s cumulative `environment` time against 55s of actual tests).
 * If this file ever renders a component or touches window/document,
 * delete this docblock rather than stubbing the DOM by hand.
 *
 * @vitest-environment node
 */
import { describe, it, expect } from 'vitest'
import { availableModes, canConfirmBasis, type BasisMode } from '../trade-basis'

const CASH_TOOLTIP = 'Unavailable while the trade includes cash — use Manual.'
const SPLIT_TOOLTIP = 'Split needs per-card values — use Transfer or Manual for now.'

describe('availableModes', () => {
  it('enables transfer and manual, but split is always disabled, when hasCash is false', () => {
    const modes = availableModes(false)
    expect(modes).toHaveLength(3)

    const transfer = modes.find((m) => m.mode === 'transfer')!
    expect(transfer.disabled).toBe(false)
    expect(transfer.reason).toBeNull()

    const split = modes.find((m) => m.mode === 'split')!
    expect(split.disabled).toBe(true)
    expect(split.reason).toBe(SPLIT_TOOLTIP)

    const manual = modes.find((m) => m.mode === 'manual')!
    expect(manual.disabled).toBe(false)
    expect(manual.reason).toBeNull()

    expect(modes.map((m) => m.mode)).toEqual(['transfer', 'split', 'manual'])
  })

  it('disables transfer with the cash tooltip, and split stays disabled with its own reason, when hasCash is true', () => {
    const modes = availableModes(true)
    expect(modes).toHaveLength(3)

    const transfer = modes.find((m) => m.mode === 'transfer')!
    expect(transfer.disabled).toBe(true)
    expect(transfer.reason).toBe(CASH_TOOLTIP)

    const split = modes.find((m) => m.mode === 'split')!
    expect(split.disabled).toBe(true)
    expect(split.reason).toBe(SPLIT_TOOLTIP)

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

  it('split without cash still returns false — split is always disabled', () => {
    expect(canConfirmBasis('split', false, '')).toBe(false)
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
})
