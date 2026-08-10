'use client'

import { useCallback, useEffect, useState } from 'react'
import { useAdminApi } from '@/lib/admin-api'
import SlabEntryForm, { type StagedSlab } from '@/components/admin/slabs/SlabEntryForm'
import StagingTable from '@/components/admin/slabs/StagingTable'
import SlabList, { type SlabRow } from '@/components/admin/slabs/SlabList'

type PricedFilter = 'all' | 'true' | 'false'

export default function SlabsPage() {
  const api = useAdminApi()
  const [rows, setRows] = useState<StagedSlab[]>([])
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [slabs, setSlabs] = useState<SlabRow[]>([])
  const [total, setTotal] = useState(0)
  const [priced, setPriced] = useState<PricedFilter>('all')
  const [listError, setListError] = useState<string | null>(null)

  const loadSlabs = useCallback(async () => {
    try {
      // `get(path, params?)` takes the params RECORD positionally — it is not a
      // FetchOptions wrapper (lib/admin-api.ts:84-88). Wrapping it in
      // `{ params: … }` made the request builder iterate the outer object and
      // emit `?params=[object Object]`, so `priced` never reached the backend
      // and the worklist returned every slab. Caught by `next build`, not by
      // the suite — vitest does not typecheck.
      const body = await api.get<{ items: SlabRow[]; total: number }>(
        '/slabs',
        priced === 'all' ? undefined : { priced },
      )
      setSlabs(body?.items ?? [])
      setTotal(body?.total ?? 0)
      setListError(null)
    } catch (e) {
      // The list failing must never take the ENTRY form down with it — intake
      // is the job this page exists for, and it does not depend on the list.
      setListError(`Could not load the slab list: ${(e as Error).message}`)
    }
  }, [api, priced])

  useEffect(() => {
    loadSlabs()
  }, [loadSlabs])

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
      const spend = rows.reduce((sum, r) => sum + Number(r.buy_price), 0)
      setResult(`Committed ${rows.length} slab(s), $${spend.toFixed(2)}`)
      setRows([])
      // The batch is now real inventory, so the list below is stale.
      loadSlabs()
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

      <section className="flex flex-col gap-3">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-semibold">Slabs on the shelf ({total})</h2>
          <label className="text-sm">
            Show{' '}
            <select
              aria-label="Filter slabs by pricing"
              value={priced}
              onChange={(e) => setPriced(e.target.value as PricedFilter)}
              className="rounded border px-2 py-1"
            >
              <option value="all">All</option>
              {/* The worklist. An unpriced slab is not Triage-flagged (owner's
                  decision, 2026-08-08), so this filter is where it surfaces. */}
              <option value="false">Not priced</option>
              <option value="true">Priced</option>
            </select>
          </label>
          <button type="button" onClick={loadSlabs} className="rounded border px-3 py-1 text-sm">
            Refresh
          </button>
        </div>
        {listError && <p role="alert" className="text-red-700">{listError}</p>}
        <SlabList rows={slabs} />
      </section>
    </div>
  )
}
