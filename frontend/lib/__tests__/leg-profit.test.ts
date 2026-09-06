/**
 * RFC 0024 T5 — leg profit (`amount - cost_basis`), display-only, computed at
 * render. Shared by `SaleDetailModal` and (via `ProfitBadge`'s render-side
 * guard) the History page's lineage rows — one guard, not two.
 *
 * @vitest-environment node
 */
import { describe, it, expect } from 'vitest'
import { computeLegProfit } from '../leg-profit'

describe('computeLegProfit', () => {
  it('computes amount minus cost basis', () => {
    expect(computeLegProfit('40.00', '10.00')).toEqual({ profit: 30, costBasisZero: false })
  })

  it('flags a zero cost basis — profit may be overstated on a consigned item', () => {
    expect(computeLegProfit('40.00', '0.00')).toEqual({ profit: 40, costBasisZero: true })
  })

  it('is null when either figure is absent', () => {
    expect(computeLegProfit(null, '10.00')).toBeNull()
    expect(computeLegProfit('40.00', null)).toBeNull()
    expect(computeLegProfit(undefined, undefined)).toBeNull()
  })

  it('accepts numbers as well as strings', () => {
    expect(computeLegProfit(40, 10)).toEqual({ profit: 30, costBasisZero: false })
  })

  it('a negative profit (sold under cost) is a real, valid result', () => {
    expect(computeLegProfit('8.00', '10.00')).toEqual({ profit: -2, costBasisZero: false })
  })
})
