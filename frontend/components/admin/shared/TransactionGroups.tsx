'use client'

import { useMemo, useState } from 'react'
import { ChevronRight, ChevronDown, Undo2, RotateCcw } from 'lucide-react'
import { formatISODate, formatTimestamp } from '@/lib/dates'
import SignedAmount from './SignedAmount'
import StatusBadge from './StatusBadge'
import VoidDialog from './VoidDialog'

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
  /** RFC 0010 T11. Present and non-null means this row counts toward nothing. */
  voided_at?: string | null
  voided_by?: string | null
  void_reason?: string | null
  [key: string]: unknown
}

/** What a void/restore acts on: one leg, or the whole real transaction. */
export interface VoidTarget {
  scope: 'batch' | 'row'
  id: string
  count: number
}

interface TransactionGroup {
  key: string
  rows: ArchiveTransaction[]
  /** The legs that still count. */
  liveRows: ArchiveTransaction[]
  voidedRows: ArchiveTransaction[]
  date: string
  paymentMethod: string
  /** The one type every leg shares, or `null` when the group mixes them. */
  uniformType: string | null
  /** Signed net when the group mixes directions; magnitude otherwise. */
  total: number
  /** The same figure over the VOIDED legs — what a dead line withdrew. */
  voidedTotal: number
  tradeId: string | null
  batchId: string | null
}

/**
 * The frontend's reading of `services/ledger.is_countable`. It is a RENDERING
 * rule only — every figure the operator makes a decision on is computed by the
 * server, which applies its own predicate. This one decides which legs a
 * client-side archive line adds up, nothing more.
 */
export function isCountable(row: ArchiveTransaction): boolean {
  return row.voided_at == null
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
    // A trade's legs are a SALE and a PURCHASE under one batch_id, so a
    // mixed group's honest total is the net. A uniform group's total is a
    // magnitude, and `SignedAmount` puts the direction on it from the type.
    const sum = (rows: ArchiveTransaction[]) =>
      uniformType
        ? rows.reduce((acc, r) => acc + magnitude(r), 0)
        : rows.reduce((acc, r) => acc + directionOf(r.type) * magnitude(r), 0)
    const liveRows = group.filter(isCountable)
    const voidedRows = group.filter((r) => !isCountable(r))
    return {
      key,
      rows: group,
      liveRows,
      voidedRows,
      date: group[0].date,
      paymentMethod: group[0].payment_method,
      uniformType,
      // A voided leg contributes nothing, so the line adds up what it still
      // contributes — the same answer the day's totals give.
      total: sum(liveRows),
      voidedTotal: sum(voidedRows),
      tradeId: tradeIds.size === 1 ? (group[0].trade_id ?? null) : null,
      batchId: group[0].batch_id ?? null,
    }
  })
}

/** `voided Aug 11, 2026, 11:30 AM · "reason" · merlin`, from the first dead leg. */
function VoidedNote({ row }: { row: ArchiveTransaction }) {
  return (
    <span data-testid="voided-note" className="text-[10px] text-red-300/80">
      voided {formatTimestamp(row.voided_at)}
      {row.void_reason ? ` · “${row.void_reason}”` : ''}
      {row.voided_by ? ` · ${row.voided_by}` : ''}
    </span>
  )
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
  onVoid,
  onRestore,
}: {
  transactions: ArchiveTransaction[]
  loading?: boolean
  emptyMessage?: string
  /** Withdraw a transaction. Rejecting keeps the row as it was. */
  onVoid?: (target: VoidTarget, reason: string) => Promise<unknown>
  onRestore?: (target: VoidTarget) => Promise<unknown>
}) {
  const groups = useMemo(() => groupTransactions(transactions), [transactions])
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [pending, setPending] = useState<{ target: VoidTarget; label: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const toggle = (key: string) =>
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })

  const message = (err: unknown) =>
    err instanceof Error ? err.message : 'Void failed'

  const confirmVoid = async (reason: string) => {
    if (!pending || !onVoid) return
    setBusy(true)
    setError(null)
    try {
      await onVoid(pending.target, reason)
      setPending(null)
    } catch (err) {
      // The dialog stays open carrying the server's message: a void that
      // silently did not happen is the worst of the three outcomes.
      setError(message(err))
    } finally {
      setBusy(false)
    }
  }

  const restore = async (target: VoidTarget) => {
    if (!onRestore) return
    setError(null)
    try {
      await onRestore(target)
    } catch (err) {
      setError(message(err))
    }
  }

  const columns = ['', 'Date', 'Type', 'Amount', 'Cards', 'Payment Method', 'Trade', '']

  return (
    <div className="overflow-x-auto vault-scroll rounded-xl border border-pine-700/40">
      {error && !pending && (
        <p role="alert" className="px-3 py-2 text-xs text-red-400">{error}</p>
      )}
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-pine-700/40 bg-pine-800/30">
            {columns.map((label, i) => (
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
              <td colSpan={8} className="px-3 py-8 text-center text-pine-400 text-xs">Loading…</td>
            </tr>
          ) : groups.length === 0 ? (
            <tr>
              <td colSpan={8} className="px-3 py-8 text-center text-pine-500 text-xs">{emptyMessage}</td>
            </tr>
          ) : (
            groups.flatMap((group) => {
              const isOpen = expanded.has(group.key)
              const multi = group.rows.length > 1
              const allVoided = group.liveRows.length === 0
              const target: VoidTarget = group.batchId
                ? { scope: 'batch', id: group.batchId, count: group.rows.length }
                : { scope: 'row', id: group.rows[0].txn_id, count: 1 }
              const rows = [
                <tr
                  key={group.key}
                  data-testid="txn-group"
                  className={`hover:bg-pine-800/40 transition-colors ${
                    allVoided ? 'line-through opacity-60' : ''
                  }`}
                >
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
                    {(() => {
                      // A dead line shows what it WITHDREW, crossed out; a live
                      // one shows what it still contributes.
                      const value = allVoided ? group.voidedTotal : group.total
                      return group.uniformType ? (
                        <SignedAmount value={value} type={group.uniformType} className="text-xs" />
                      ) : (
                        <SignedAmount value={value} fromValue className="text-xs" />
                      )
                    })()}
                  </td>
                  <td className="px-3 py-2 text-xs text-pine-300">
                    {group.rows.length} {group.rows.length === 1 ? 'card' : 'cards'}
                    {allVoided && group.voidedRows[0] && (
                      <div className="no-underline">
                        <VoidedNote row={group.voidedRows[0]} />
                      </div>
                    )}
                    {!allVoided && group.voidedRows.length > 0 && (
                      <div className="text-[10px] text-amber-400">
                        {group.voidedRows.length} of {group.rows.length} voided
                      </div>
                    )}
                  </td>
                  <td className="px-3 py-2 text-xs text-pine-300">{group.paymentMethod}</td>
                  <td className="px-3 py-2">
                    {group.tradeId && (
                      <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-mono bg-purple-500/15 text-purple-300 border border-purple-500/30">
                        {group.tradeId.slice(0, 8)}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right whitespace-nowrap no-underline">
                    {allVoided && onRestore && (
                      <button
                        type="button"
                        onClick={() => restore(target)}
                        className="inline-flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium text-mint hover:bg-mint/10 transition-colors"
                      >
                        <RotateCcw size={11} /> Restore
                      </button>
                    )}
                    {/* Sales only, matching the backend: voiding a PURCHASE
                        should arguably remove an item that may since have been
                        sold or traded, so it returns a clear 400 rather than
                        half-happening. An affordance that always fails is worse
                        than none. */}
                    {group.uniformType === 'sale' && group.voidedRows.length === 0 && onVoid && (
                      <button
                        type="button"
                        aria-label="Void this transaction"
                        onClick={() => {
                          setError(null)
                          setPending({
                            target,
                            // Voiding five sales when you meant one is exactly
                            // the mistake this feature exists to fix, so the
                            // count is in the confirm, not just the row.
                            label: multi
                              ? `Void this whole transaction (${group.rows.length} cards)?`
                              : 'Void this transaction?',
                          })
                        }}
                        className="inline-flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium text-red-400 hover:bg-red-500/10 transition-colors"
                      >
                        <Undo2 size={11} /> Void
                      </button>
                    )}
                  </td>
                </tr>,
              ]

              if (isOpen) {
                for (const leg of group.rows) {
                  const legVoided = !isCountable(leg)
                  const legTarget: VoidTarget = {
                    scope: 'row', id: leg.txn_id, count: 1,
                  }
                  rows.push(
                    <tr
                      key={leg.txn_id}
                      data-testid="txn-leg"
                      className={`bg-pine-900/30 ${legVoided ? 'line-through opacity-60' : ''}`}
                    >
                      <td className="px-3 py-1.5" />
                      <td className="px-3 py-1.5 font-mono text-[11px] text-pine-500" colSpan={2}>
                        {leg.item_id}
                        {legVoided && (
                          <div className="no-underline"><VoidedNote row={leg} /></div>
                        )}
                      </td>
                      <td className="px-3 py-1.5 text-right">
                        <SignedAmount value={leg.amount} type={leg.type} className="text-xs" />
                      </td>
                      <td className="px-3 py-1.5 text-[11px] text-pine-500" colSpan={2}>
                        {leg.payment_method}
                      </td>
                      <td className="px-3 py-1.5 text-right whitespace-nowrap no-underline">
                        {legVoided
                          ? onRestore && (
                            <button
                              type="button"
                              aria-label={`Restore this card (${leg.item_id})`}
                              onClick={() => restore(legTarget)}
                              className="px-2 py-0.5 rounded text-[10px] text-mint hover:bg-mint/10 transition-colors"
                            >
                              Restore
                            </button>
                          )
                          : leg.type === 'sale' && onVoid && (
                            <button
                              type="button"
                              aria-label={`Void this card (${leg.item_id})`}
                              onClick={() => {
                                setError(null)
                                setPending({
                                  target: legTarget,
                                  label: 'Void this one card?',
                                })
                              }}
                              className="px-2 py-0.5 rounded text-[10px] text-red-400 hover:bg-red-500/10 transition-colors"
                            >
                              Void
                            </button>
                          )}
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

      <VoidDialog
        open={pending !== null}
        title={pending?.label ?? 'Void this transaction?'}
        description={
          'The transaction stays in the archive marked voided, stops counting '
          + 'toward every total, and the cards go back into inventory. It can be '
          + 'restored.'
        }
        loading={busy}
        error={error}
        onConfirm={confirmVoid}
        onCancel={() => { setPending(null); setError(null) }}
      />
    </div>
  )
}
