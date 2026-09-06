'use client'

import { AlertTriangle } from 'lucide-react'
import type { LegProfit } from '@/lib/leg-profit'

/**
 * The ONE rendering of a leg's profit, shared by History's per-lineage-hop
 * rows and the Show Analytics sale-detail popup (RFC 0024 T5). `profit` and
 * `costBasisZero` are already computed by the caller — History derives them
 * from its own `step_profit`/`acquired_cost` fields, `SaleDetailModal` from
 * `lib/leg-profit.ts`'s `computeLegProfit` — so this component owns exactly
 * one thing: the guard that warns when a $0 cost basis (a consigned item,
 * not a genuine zero-cost acquisition) may be overstating the figure.
 */
export default function ProfitBadge({ profit, costBasisZero }: LegProfit) {
  const isPositive = profit >= 0
  return (
    <span className="inline-flex items-center gap-1">
      <span className={isPositive ? 'text-mint' : 'text-red-400'}>
        {isPositive ? '+' : '-'}${Math.abs(profit).toFixed(2)}
      </span>
      {costBasisZero && (
        <span title="Profit may be overstated — cost basis is $0 (consigned)">
          <AlertTriangle size={11} className="text-amber-400" />
        </span>
      )}
    </span>
  )
}
