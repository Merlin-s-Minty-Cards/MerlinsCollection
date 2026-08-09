'use client'

import type { StagedSlab } from './SlabEntryForm'

export default function StagingTable({ rows, onRemove }: {
  rows: StagedSlab[]
  onRemove: (key: string) => void
}) {
  if (rows.length === 0) {
    return <p className="text-sm text-gray-600">Nothing staged yet.</p>
  }
  return (
    <table className="w-full text-sm">
      <thead>
        <tr>
          <th className="text-left">Cert</th><th className="text-left">Card</th>
          <th className="text-left">Company</th><th className="text-left">Grade</th>
          <th className="text-left">Cost</th><th />
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.key}>
            <td>{r.cert_number}</td>
            <td>
              {r.name}
              {/* Honest up front: an unlinked slab gets no automatic price and
                  lands in Triage. Better said here than discovered later. */}
              {!r.card_id && <span className="ml-2 text-amber-700">no catalog link</span>}
            </td>
            <td>{r.company}</td>
            <td>{r.grade}</td>
            <td>${r.buy_price}</td>
            <td>
              <button type="button" onClick={() => onRemove(r.key)} aria-label={`Remove ${r.cert_number}`}>
                Remove
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
