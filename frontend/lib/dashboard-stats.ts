/**
 * Aggregations behind the admin dashboard's at-a-glance numbers.
 *
 * Pure functions, deliberately out of the page component: the rules that are
 * easy to get quietly wrong live here where they can be tested directly —
 * which statuses count as stock on hand, and what a consigned item does to
 * profit.
 */

/** An inventory row as `GET /admin/inventory/search` returns it. */
export interface HoldingItem {
  status?: string
  cost_basis?: string | number | null
  current_market_value?: string | number | null
  /** Present and non-null when the card belongs to a consignor, not to us. */
  consignment?: unknown
  [key: string]: unknown
}

/**
 * Statuses that still represent owned, unsold stock.
 *
 * `on_hold` counts: a vaulted card is not for sale today but it is capital
 * tied up, and omitting it would understate the position. `sold` is gone,
 * `lost` and `returned_to_consignor` are gone, and `out_for_grading` is still
 * ours — it is just at PSA.
 */
export const HELD_STATUSES = ['available', 'on_hold', 'out_for_grading'] as const

export interface HoldingsSummary {
  onHandCount: number
  /** Every held card, consigned included — it is physically in the case. */
  marketValue: number
  /** Owned stock only; a consigned card's basis is not the business's money. */
  costBasis: number
  /** marketValue-minus-costBasis over OWNED stock only. */
  unrealized: number
  /** Unrealized as a percentage of cost, or null when nothing is owned. */
  marginPct: number | null
  consignedCount: number
}

/** Parses a Decimal-as-string; a missing or unparseable value is 0, not NaN. */
function num(value: unknown): number {
  if (value === null || value === undefined) return 0
  const parsed = typeof value === 'number' ? value : parseFloat(String(value))
  return Number.isFinite(parsed) ? parsed : 0
}

function isConsigned(item: HoldingItem): boolean {
  return item.consignment !== null && item.consignment !== undefined
}

export function summarizeHoldings(items: HoldingItem[]): HoldingsSummary {
  const held = items.filter((i) =>
    (HELD_STATUSES as readonly string[]).includes(String(i.status ?? '')),
  )

  let marketValue = 0
  let costBasis = 0
  let ownedMarketValue = 0
  let consignedCount = 0

  for (const item of held) {
    const market = num(item.current_market_value)
    marketValue += market

    // A consigned card contributes its value to what is on hand but nothing to
    // cost or profit: its basis is $0 because the money was never ours, and
    // counting that as margin would report the consignor's card as pure gain.
    if (isConsigned(item)) {
      consignedCount += 1
      continue
    }
    costBasis += num(item.cost_basis)
    ownedMarketValue += market
  }

  const unrealized = ownedMarketValue - costBasis

  return {
    onHandCount: held.length,
    marketValue,
    costBasis,
    unrealized,
    marginPct: costBasis > 0 ? (unrealized / costBasis) * 100 : null,
    consignedCount,
  }
}
