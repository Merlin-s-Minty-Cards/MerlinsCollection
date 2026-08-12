'use client'

import { useMemo, useState } from 'react'
import { ChevronRight, ChevronDown } from 'lucide-react'
import { formatISODate } from '@/lib/dates'
import SignedAmount from './SignedAmount'
import StatusBadge from './StatusBadge'

/**
 * The transaction archive, grouped so one real transaction reads as one line.
 * docs/plans/rfc-0010/t10-transaction-batch-id.md
 *
 * Owner report: *"single transactions can be grouped together with details
 * regarding the transaction. For example one line on that could say purchase
 * -$200 and contain multiple cards which were purchased in a singular
 * transaction."*
 *
 * **Grouping is a CLIENT concern.** `GET /admin/transactions` keeps returning
 * rows exactly as it always has — it is deliberately a raw archive (*"nothing
 * is filtered out, trade cash legs included, because the point is to see what
 * was actually written"*), and nesting it server-side would break that contract
 * for every other reader to serve one view's layout.
 *
 * **A row with no `batch_id` is its own group**, keyed on its `txn_id`. There is
 * no legacy branch in the render path: a one-item group is a truthful rendering
 * of what is known about a row written before the field existed, and no
 * heuristic is allowed to guess otherwise.
 */

export interface ArchiveTransaction {
  txn_id: string
  type: string
  item_id: string
  date: string
  amount: string
  payment_method: string
  trade_id?: string | null
  batch_id?: string | null
  [key: string]: unknown
}

interface TransactionGroup {
  key: string
  rows: ArchiveTransaction[]
  date: string
  paymentMethod: string
  /** The one type every leg shares, or `null` when the group mixes them. */
  uniformType: string | null
  /** Signed net when the group mixes directions; magnitude otherwise. */
  total: number
  tradeId: string | null
}

function magnitude(row: ArchiveTransaction): number {
  const n = parseFloat(row.amount)
  return Number.isNaN(n) ? 0 : Math.abs(n)
}

/** Sale is money in, purchase money out. Anything else contributes unsigned. */
function directionOf(type: string): number {
  if (type === 'sale') return 1
  if (type === 'purchase') return -1
  return 1
}

/**
 * Groups in FIRST-SEEN order, which preserves the endpoint's own sort
 * (`(date, txn_id)` descending). Grouping must not reorder the archive.
 */
export function groupTransactions(rows: ArchiveTransaction[]): TransactionGroup[] {
  const byKey = new Map<string, ArchiveTransaction[]>()
  for (const row of rows) {
    const key = row.batch_id || row.txn_id
    const bucket = byKey.get(key)
    if (bucket) bucket.push(row)
    else byKey.set(key, [row])
  }

  return Array.from(byKey.entries()).map(([key, group]) => {
    const types = new Set(group.map((r) => r.type))
    const uniformType = types.size === 1 ? group[0].type : null
    const tradeIds = new Set(group.map((r) => r.trade_id ?? null))
    return {
      key,
      rows: group,
      date: group[0].date,
      paymentMethod: group[0].payment_method,
      uniformType,
      // A trade's legs are a SALE and a PURCHASE under one batch_id, so a
      // mixed group's honest total is the net. A uniform group's total is a
      // magnitude, and `SignedAmount` puts the direction on it from the type.
      total: uniformType
        ? group.reduce((sum, r) => sum + magnitude(r), 0)
        : group.reduce((sum, r) => sum + directionOf(r.type) * magnitude(r), 0),
      tradeId: tradeIds.size === 1 ? (group[0].trade_id ?? null) : null,
    }
  })
}

function TypeCell({ type }: { type: string }) {
  const style = type === 'sale'
    ? 'bg-mint/15 text-mint border-mint/30'
    : type === 'purchase'
      ? 'bg-blue-400/15 text-blue-300 border-blue-400/30'
      : undefined
  if (!style) return <StatusBadge status={type} />
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-medium uppercase tracking-wider border ${style}`}>
      {type}
    </span>
  )
}

export default function TransactionGroups({
  transactions,
  loading,
  emptyMessage = 'No transactions for this date',
}: {
  transactions: ArchiveTransaction[]
  loading?: boolean
  emptyMessage?: string
}) {
  const groups = useMemo(() => groupTransactions(transactions), [transactions])
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const toggle = (key: string) =>
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })

  return (
    <div className="overflow-x-auto vault-scroll rounded-xl border border-pine-700/40">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-pine-700/40 bg-pine-800/30">
            {['', 'Date', 'Type', 'Amount', 'Cards', 'Payment Method', 'Trade'].map((label, i) => (
              <th
                key={label || `spacer-${i}`}
                className={`px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-pine-400 ${label === 'Amount' ? 'text-right' : ''}`}
              >
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-pine-700/25">
          {loading ? (
            <tr>
              <td colSpan={7} className="px-3 py-8 text-center text-pine-400 text-xs">Loading…</td>
            </tr>
          ) : groups.length === 0 ? (
            <tr>
              <td colSpan={7} className="px-3 py-8 text-center text-pine-500 text-xs">{emptyMessage}</td>
            </tr>
          ) : (
            groups.flatMap((group) => {
              const isOpen = expanded.has(group.key)
              const multi = group.rows.length > 1
              const rows = [
                <tr key={group.key} data-testid="txn-group" className="hover:bg-pine-800/40 transition-colors">
                  <td className="w-8 px-3 py-2">
                    {/* A twisty that reveals the same row is noise, so a group
                        of one renders no disclosure control at all. */}
                    {multi && (
                      <button
                        type="button"
                        onClick={() => toggle(group.key)}
                        aria-expanded={isOpen}
                        aria-label={`${isOpen ? 'Hide' : 'Show'} the ${group.rows.length} cards in this transaction`}
                        className="p-0.5 rounded text-pine-400 hover:text-mint transition-colors"
                      >
                        {isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                      </button>
                    )}
                  </td>
                  <td className="px-3 py-2 text-[13px] text-pine-200">
                    <span className="font-mono text-xs">{formatISODate(group.date)}</span>
                  </td>
                  <td className="px-3 py-2">
                    {group.uniformType ? (
                      <TypeCell type={group.uniformType} />
                    ) : (
                      <TypeCell type={group.tradeId ? 'trade' : 'mixed'} />
                    )}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {group.uniformType ? (
                      <SignedAmount value={group.total} type={group.uniformType} className="text-xs" />
                    ) : (
                      <SignedAmount value={group.total} fromValue className="text-xs" />
                    )}
                  </td>
                  <td className="px-3 py-2 text-xs text-pine-300">
                    {group.rows.length} {group.rows.length === 1 ? 'card' : 'cards'}
                  </td>
                  <td className="px-3 py-2 text-xs text-pine-300">{group.paymentMethod}</td>
                  <td className="px-3 py-2">
                    {group.tradeId && (
                      <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-mono bg-purple-500/15 text-purple-300 border border-purple-500/30">
                        {group.tradeId.slice(0, 8)}
                      </span>
                    )}
                  </td>
                </tr>,
              ]

              if (isOpen) {
                for (const leg of group.rows) {
                  rows.push(
                    <tr key={leg.txn_id} data-testid="txn-leg" className="bg-pine-900/30">
                      <td className="px-3 py-1.5" />
                      <td className="px-3 py-1.5 font-mono text-[11px] text-pine-500" colSpan={2}>
                        {leg.item_id}
                      </td>
                      <td className="px-3 py-1.5 text-right">
                        <SignedAmount value={leg.amount} type={leg.type} className="text-xs" />
                      </td>
                      <td className="px-3 py-1.5 text-[11px] text-pine-500" colSpan={3}>
                        {leg.payment_method}
                      </td>
                    </tr>,
                  )
                }
              }
              return rows
            })
          )}
        </tbody>
      </table>
    </div>
  )
}
