'use client'

import { formatMoney } from '@/lib/money'
import type { StagedSlab } from './SlabEntryForm'

export default function StagingTable({ rows, onRemove }: {
  rows: StagedSlab[]
  onRemove: (key: string) => void
}) {
  if (rows.length === 0) {
    return (
      <p className="vault-panel rounded-xl px-4 py-6 text-center text-xs text-pine-500">
        Nothing staged yet.
      </p>
    )
  }
  const total = rows.reduce((sum, r) => sum + r.buy_price, 0)
  return (
    <div className="vault-panel overflow-hidden rounded-xl">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-pine-700/40 text-[11px] uppercase tracking-wider text-pine-400">
            <th className="px-3 py-2 text-left font-medium">Cert</th>
            <th className="px-3 py-2 text-left font-medium">Card</th>
            <th className="px-3 py-2 text-left font-medium">Company</th>
            <th className="px-3 py-2 text-left font-medium">Grade</th>
            <th className="px-3 py-2 text-left font-medium">Cost</th>
            <th className="px-3 py-2" />
          </tr>
        </thead>
        <tbody className="divide-y divide-pine-700/25">
          {rows.map((r) => (
            <tr key={r.key}>
              <td className="px-3 py-2 font-mono text-pine-200">{r.cert_number}</td>
              <td className="px-3 py-2 text-pine-100">
                {r.name}
                {/* Honest up front: an unlinked slab gets no automatic price and
                    lands in Triage. Better said here than discovered later. */}
                {!r.card_id && (
                  <span className="ml-2 rounded border border-amber-500/25 bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-300">
                    no catalog link
                  </span>
                )}
              </td>
              <td className="px-3 py-2 text-pine-300">{r.company}</td>
              <td className="px-3 py-2 font-mono text-pine-200">{r.grade}</td>
              {/* The PARSED amount, not the text that was typed. Rendering the
                  raw string is what let "1,300" show as a correct-looking
                  $1,300 while NaN was on its way to the server. */}
              <td className="px-3 py-2 font-mono text-spriggatito-400">{formatMoney(r.buy_price)}</td>
              <td className="px-3 py-2 text-right">
                <button
                  type="button"
                  onClick={() => onRemove(r.key)}
                  aria-label={`Remove ${r.cert_number}`}
                  className="rounded px-2 py-1 text-pine-500 transition-colors hover:text-red-400"
                >
                  Remove
                </button>
              </td>
            </tr>
          ))}
        </tbody>
        {/* The batch total is the pre-commit signal this table had none of. A
            total is what would have exposed a NaN before anything was written. */}
        <tfoot>
          <tr className="border-t border-pine-700/40">
            <th scope="row" colSpan={4} className="px-3 py-2 text-right text-[11px] uppercase tracking-wider text-pine-400">
              Batch total
            </th>
            <td className="px-3 py-2 font-mono text-spriggatito-400">{formatMoney(total)}</td>
            <td className="px-3 py-2" />
          </tr>
        </tfoot>
      </table>
    </div>
  )
}
