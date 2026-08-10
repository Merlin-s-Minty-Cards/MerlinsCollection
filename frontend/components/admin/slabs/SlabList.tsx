'use client'

import CardImage, { TABLE_THUMB_SIZE, TABLE_THUMB_COLUMN } from '@/components/admin/shared/CardImage'
import { useCardImages } from '@/lib/use-card-images'

/** One row of `GET /admin/slabs`. Money fields are STRINGS — a Decimal that
 *  survived JSON without being rounded into a float on the way out. */
export interface SlabRow {
  item_id: string
  card_id: string | null
  name: string | null
  cert_number: string
  company: string
  grade: string
  cost_basis: string
  status: string
  market_value: string | null
  value_as_of: string | null
  price_source: string | null
}

/**
 * How old a stored value is, in words.
 *
 * Staleness is a NORMAL state to display here, not an error to hide: T7 rotates
 * refreshes through the shelf a night at a time (the free tier is 50 lookups a
 * day), so most slabs are legitimately a few days behind at any moment. Saying
 * so is what stops an operator reading a stale figure as a live one.
 */
export function valueAge(iso: string | null): string | null {
  if (!iso) return null
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return null
  const days = Math.floor((Date.now() - then) / 86_400_000)
  if (days <= 0) return 'priced today'
  if (days === 1) return 'priced 1 day ago'
  return `priced ${days} days ago`
}

export default function SlabList({ rows }: { rows: SlabRow[] }) {
  // A freshly-mapped array every render, which is what the hook expects — it
  // attempts each id exactly once and will not re-queue a failure, so passing a
  // memoized array would not save a request and re-queueing would cost one per
  // render (CLAUDE.md, the Trade page's request storm).
  const { getImageUrl } = useCardImages(rows.map((r) => r.card_id))

  if (rows.length === 0) {
    return (
      <p className="vault-panel rounded-xl px-4 py-6 text-center text-xs text-pine-500">
        No slabs yet.
      </p>
    )
  }

  return (
    <div className="vault-panel overflow-hidden rounded-xl">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-pine-700/40 text-[11px] uppercase tracking-wider text-pine-400">
            <th className={`px-3 py-2 text-left font-medium ${TABLE_THUMB_COLUMN}`}>
              <span className="sr-only">Art</span>
            </th>
            <th className="px-3 py-2 text-left font-medium">Card</th>
            <th className="px-3 py-2 text-left font-medium">Cert</th>
            <th className="px-3 py-2 text-left font-medium">Company</th>
            <th className="px-3 py-2 text-left font-medium">Grade</th>
            <th className="px-3 py-2 text-left font-medium">Value</th>
            <th className="px-3 py-2 text-left font-medium">Cost</th>
            <th className="px-3 py-2 text-left font-medium">Status</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-pine-700/25">
          {rows.map((row) => {
            const age = valueAge(row.value_as_of)
            return (
              <tr key={row.item_id}>
                <td className={`px-3 py-2 ${TABLE_THUMB_COLUMN}`}>
                  <CardImage
                    imageUrl={getImageUrl(row.card_id)}
                    alt={row.name || row.cert_number}
                    size={TABLE_THUMB_SIZE}
                  />
                </td>
                <td className="px-3 py-2 text-pine-100">
                  {row.name || <span className="text-pine-500">unnamed</span>}
                </td>
                <td className="px-3 py-2 font-mono text-pine-300">{row.cert_number}</td>
                <td className="px-3 py-2 text-pine-300">{row.company}</td>
                <td className="px-3 py-2 font-mono text-pine-200">{row.grade}</td>
                <td className="px-3 py-2">
                  {row.market_value === null ? (
                    // NEVER $0.00. A slab shown at zero drags every total and
                    // misreports position while looking authoritative; "not
                    // priced" is the honest state and, after the verified-join
                    // rule, the ordinary one for a Japanese slab.
                    <span className="rounded border border-amber-500/25 bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-300">
                      not priced
                    </span>
                  ) : (
                    <>
                      <span className="font-mono text-spriggatito-400">${row.market_value}</span>
                      {row.price_source === 'manual' && (
                        <span className="ml-2 rounded bg-pine-800/60 px-1.5 py-0.5 text-[10px] text-pine-300">
                          manual
                        </span>
                      )}
                      {age && <span className="ml-2 text-[10px] text-pine-500">{age}</span>}
                    </>
                  )}
                </td>
                <td className="px-3 py-2 font-mono text-pine-200">${row.cost_basis}</td>
                <td className="px-3 py-2 text-pine-300">{row.status}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
