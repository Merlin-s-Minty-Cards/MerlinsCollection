/**
 * RFC 0024 T5 — leg profit (`amount - cost_basis`), display-only, computed at
 * render, never stored. `SaleDetailModal` and History's per-lineage-hop
 * rendering both need "was this profitable, and might the figure be
 * overstated because the item was consigned" — this is the one place that
 * answers the first half; `ProfitBadge` (`components/admin/shared/`) is the
 * one place that renders the guard both callers share, so there is exactly
 * one implementation of "a $0 cost basis warns" rather than two that could
 * drift.
 */

export interface LegProfit {
  profit: number
  /** True when cost basis is exactly zero — a routine state for a consigned
   *  item, not a genuine zero-cost acquisition, so the raw profit figure may
   *  overstate what was actually made. */
  costBasisZero: boolean
}

function toNumber(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === '') return null
  const n = typeof value === 'string' ? Number(value) : value
  return Number.isFinite(n) ? n : null
}

/** `null` when either figure is absent — never a guessed profit. */
export function computeLegProfit(
  amount: string | number | null | undefined,
  costBasis: string | number | null | undefined,
): LegProfit | null {
  const amt = toNumber(amount)
  const cost = toNumber(costBasis)
  if (amt === null || cost === null) return null
  return { profit: amt - cost, costBasisZero: cost === 0 }
}
