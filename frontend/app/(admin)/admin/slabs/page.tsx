'use client'

import { useState } from 'react'
import { useAdminApi } from '@/lib/admin-api'
import SlabEntryForm, { type StagedSlab } from '@/components/admin/slabs/SlabEntryForm'
import StagingTable from '@/components/admin/slabs/StagingTable'

export default function SlabsPage() {
  const api = useAdminApi()
  const [rows, setRows] = useState<StagedSlab[]>([])
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const commit = async () => {
    if (rows.length === 0) return
    setBusy(true); setError(null); setResult(null)
    try {
      const session = await api.post<{ buy_id: string }>('/purchases', {})
      const buyId = session.buy_id

      for (const r of rows) {
        // Numbers, not strings: the backend coerces through str() to an exact
        // Decimal, and sending strings here is what let the float bug hide.
        // `manual_entry` is deliberately ABSENT -- every slab here is typed by
        // hand, so sending it would flag the whole shelf into Triage.
        await api.post(`/purchases/${buyId}/items`, {
          kind: 'graded',
          name: r.name,
          card_id: r.card_id,
          company: r.company,
          grade: Number(r.grade),
          cert_number: r.cert_number,
          grade_label: r.grade_label || null,
          buy_price: Number(r.buy_price),
          location: r.location,
        })
      }

      await api.post(`/purchases/${buyId}/confirm`, {})
      const total = rows.reduce((sum, r) => sum + Number(r.buy_price), 0)
      setResult(`Committed ${rows.length} slab(s), $${total.toFixed(2)}`)
      setRows([])
    } catch (e) {
      // Stop where we are. An unconfirmed draft creates no inventory, so
      // "do nothing" is the safe state -- never half-commit a batch.
      setError(`Commit failed before confirming: ${(e as Error).message}. Nothing was created; the batch is intact.`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-6 p-6">
      <h1 className="text-2xl font-semibold">Slabs</h1>
      <SlabEntryForm onAdd={(row) => setRows((rs) => [...rs, row])} />
      <StagingTable rows={rows} onRemove={(key) => setRows((rs) => rs.filter((r) => r.key !== key))} />
      {error && <p role="alert" className="text-red-700">{error}</p>}
      {result && <p role="status" className="text-green-700">{result}</p>}
      <button type="button" onClick={commit} disabled={busy || rows.length === 0}
              className="self-start rounded bg-green-700 px-4 py-2 text-white disabled:opacity-50">
        Commit batch
      </button>
    </div>
  )
}
