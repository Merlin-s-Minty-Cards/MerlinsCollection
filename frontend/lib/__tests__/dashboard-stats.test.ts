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
import { summarizeHoldings, HELD_STATUSES } from '../dashboard-stats'

/**
 * The dashboard's money numbers.
 *
 * Kept as a pure function rather than inline in the page because the rules
 * here are the easy ones to get quietly wrong — which statuses count as stock
 * on hand, and what a consigned item does to profit.
 */

function item(over: Record<string, unknown> = {}) {
  return {
    item_id: 'i-1',
    status: 'available',
    cost_basis: '10.00',
    current_market_value: '25.00',
    consignment: null,
    ...over,
  }
}

describe('summarizeHoldings', () => {
  it('totals market value and cost basis for stock on hand', () => {
    const s = summarizeHoldings([
      item({ item_id: 'a', cost_basis: '10.00', current_market_value: '25.00' }),
      item({ item_id: 'b', cost_basis: '5.50', current_market_value: '7.25' }),
    ])

    expect(s.marketValue).toBeCloseTo(32.25, 2)
    expect(s.costBasis).toBeCloseTo(15.5, 2)
    expect(s.unrealized).toBeCloseTo(16.75, 2)
  })

  it('excludes sold stock — it is no longer inventory', () => {
    const s = summarizeHoldings([
      item({ item_id: 'a' }),
      item({ item_id: 'sold', status: 'sold', cost_basis: '999', current_market_value: '999' }),
    ])

    expect(s.onHandCount).toBe(1)
    expect(s.marketValue).toBeCloseTo(25, 2)
  })

  it('counts on-hold stock as held — it is still owned', () => {
    // Vault/on-hold items are not for sale today but they ARE capital tied up,
    // so leaving them out would understate the position.
    expect(HELD_STATUSES).toContain('on_hold')
    const s = summarizeHoldings([item({ status: 'on_hold' })])
    expect(s.onHandCount).toBe(1)
  })

  it('drops lost and returned-to-consignor stock', () => {
    const s = summarizeHoldings([
      item({ item_id: 'l', status: 'lost' }),
      item({ item_id: 'r', status: 'returned_to_consignor' }),
    ])
    expect(s.onHandCount).toBe(0)
  })

  it('keeps consigned stock out of profit, because its cost basis is not ours', () => {
    // The documented trap (CLAUDE.md, History profit guard): a consigned item
    // carries a $0 cost basis, so counting it as profit would report the
    // consignor's card as pure margin for the business.
    const s = summarizeHoldings([
      item({ item_id: 'owned', cost_basis: '10.00', current_market_value: '25.00' }),
      item({
        item_id: 'consigned', cost_basis: '0', current_market_value: '500.00',
        consignment: { consignor_id: 'c-1' },
      }),
    ])

    expect(s.unrealized).toBeCloseTo(15, 2)
    expect(s.consignedCount).toBe(1)
  })

  it('still counts consigned stock in the on-hand market value', () => {
    // It is physically in the case and worth something — it just is not the
    // business's margin. Both facts have to survive.
    const s = summarizeHoldings([
      item({ item_id: 'consigned', current_market_value: '500.00',
             consignment: { consignor_id: 'c-1' } }),
    ])
    expect(s.marketValue).toBeCloseTo(500, 2)
    expect(s.unrealized).toBe(0)
  })

  it('treats a missing market value as zero rather than NaN', () => {
    // An unpriced item is common (that is what the coverage stat is for) and
    // must not poison the whole total into NaN.
    const s = summarizeHoldings([item({ current_market_value: null })])
    expect(s.marketValue).toBe(0)
    expect(Number.isNaN(s.unrealized)).toBe(false)
  })

  it('reports margin as a percentage of cost, and null when nothing is owned', () => {
    expect(summarizeHoldings([
      item({ cost_basis: '10.00', current_market_value: '15.00' }),
    ]).marginPct).toBeCloseTo(50, 2)

    expect(summarizeHoldings([]).marginPct).toBeNull()
  })

  it('returns zeros for an empty inventory instead of throwing', () => {
    const s = summarizeHoldings([])
    expect(s).toMatchObject({ onHandCount: 0, marketValue: 0, costBasis: 0, unrealized: 0 })
  })
})
