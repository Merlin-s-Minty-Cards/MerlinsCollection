'use client'

import { useCallback, useEffect, useState } from 'react'
import { Camera, Keyboard, RefreshCw, ScanLine, Wand2 } from 'lucide-react'
import { useAdminApi } from '@/lib/admin-api'
import { formatMoney } from '@/lib/money'
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

  // Intake affordances. The form is put away by default, matching the other
  // admin tabs — the page's resting state is the shelf, not a blank form.
  const [entryOpen, setEntryOpen] = useState(false)
  const [scanArmed, setScanArmed] = useState(false)
  // Bumping this pulls focus to the cert field without remounting the form.
  const [focusToken, setFocusToken] = useState(0)

  const armScan = () => {
    setEntryOpen(true)
    setScanArmed(true)
    setFocusToken((n) => n + 1)
  }

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
          // Already a number: SlabEntryForm parses at staging time, so the
          // staging table and this body carry the same value. `Number(...)`
          // here would be a second, weaker parse of a string that no longer
          // exists.
          buy_price: r.buy_price,
          location: r.location,
        })
      }

      await api.post(`/purchases/${buyId}/confirm`, {})
      const spend = rows.reduce((sum, r) => sum + r.buy_price, 0)
      setResult(`Committed ${rows.length} slab(s), ${formatMoney(spend)}`)
      setRows([])
      // Return focus to the cert field so the next slab can go straight in --
      // with a stack of slabs in hand, that is the interaction this page lives
      // on. Closes the "refocus the cert field" T4 follow-up.
      setFocusToken((n) => n + 1)
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
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold text-pine-100">Slabs</h1>
      </header>

      {/* ---- Intake: how a slab gets in ------------------------------------
          Three routes are shown, two of them deliberately dead. PSA's cert API
          403s at the ACCOUNT ("limited to approved customers") — re-confirmed
          2026-08-10 against their Swagger with both bearer spellings — so
          camera capture and cert auto-fill cannot work no matter what we ship.
          They are rendered disabled, naming the blocker, rather than omitted,
          so the gap is visible instead of looking like an oversight. */}
      <section className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => {
              setEntryOpen((open) => !open)
              setScanArmed(false)
            }}
            aria-expanded={entryOpen}
            className="inline-flex items-center gap-1.5 rounded-lg border border-mint/30 bg-mint/15 px-3.5 py-2 text-xs font-medium text-mint transition-colors hover:bg-mint/25"
          >
            <Keyboard size={14} />
            Manual entry
          </button>

          <button
            type="button"
            onClick={armScan}
            className="inline-flex items-center gap-1.5 rounded-lg border border-pine-700/40 px-3.5 py-2 text-xs font-medium text-pine-300 transition-colors hover:border-pine-600 hover:text-pine-100"
          >
            <ScanLine size={14} />
            Scan cert
          </button>

          <span className="mx-1 h-5 w-px bg-pine-700/40" aria-hidden="true" />

          <button
            type="button"
            disabled
            aria-describedby="psa-blocked"
            className="inline-flex cursor-not-allowed items-center gap-1.5 rounded-lg border border-pine-700/30 px-3.5 py-2 text-xs font-medium text-pine-500 opacity-60"
          >
            <Camera size={14} />
            Camera scan
          </button>

          <button
            type="button"
            disabled
            aria-describedby="psa-blocked"
            className="inline-flex cursor-not-allowed items-center gap-1.5 rounded-lg border border-pine-700/30 px-3.5 py-2 text-xs font-medium text-pine-500 opacity-60"
          >
            <Wand2 size={14} />
            Auto-fill from cert
          </button>
        </div>

        <p id="psa-blocked" className="text-[11px] text-pine-500">
          Camera scan and cert auto-fill need PSA API approval — every call returns
          HTTP 403 at the account, not in our code. Re-checked 2026-08-10. Until
          then, scan the barcode into the cert field or type it: both are fully
          supported and nothing else about intake depends on PSA.
        </p>

        {entryOpen && (
          <div className="vault-panel rounded-xl p-4">
            <SlabEntryForm
              onAdd={(row) => setRows((rs) => [...rs, row])}
              focusToken={focusToken}
              armed={scanArmed}
            />
          </div>
        )}
      </section>

      {/* ---- Staged batch ---- */}
      <section className="flex flex-col gap-3">
        <StagingTable rows={rows} onRemove={(key) => setRows((rs) => rs.filter((r) => r.key !== key))} />
        {error && (
          <p role="alert" className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">
            {error}
          </p>
        )}
        {result && (
          <p role="status" className="rounded-lg border border-spriggatito-400/30 bg-spriggatito-400/10 px-3 py-2 text-xs text-spriggatito-400">
            {result}
          </p>
        )}
        <button
          type="button"
          onClick={commit}
          disabled={busy || rows.length === 0}
          className="inline-flex items-center gap-1.5 self-start rounded-lg border border-mint/30 bg-mint/15 px-4 py-2 text-xs font-medium text-mint transition-colors hover:bg-mint/25 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {busy ? 'Committing…' : 'Commit batch'}
        </button>
      </section>

      {/* ---- The shelf ---- */}
      <section className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-sm font-semibold text-pine-100">Slabs on the shelf ({total})</h2>
          <label className="flex items-center gap-1.5 text-[11px] uppercase tracking-wider text-pine-400">
            Show
            <select
              aria-label="Filter slabs by pricing"
              value={priced}
              onChange={(e) => setPriced(e.target.value as PricedFilter)}
              className="vault-field rounded-lg px-2.5 py-1.5 text-xs normal-case tracking-normal"
            >
              <option value="all">All</option>
              {/* The worklist. An unpriced slab is not Triage-flagged (owner's
                  decision, 2026-08-08), so this filter is where it surfaces. */}
              <option value="false">Not priced</option>
              <option value="true">Priced</option>
            </select>
          </label>
          <button
            type="button"
            onClick={loadSlabs}
            className="inline-flex items-center gap-1.5 rounded-lg border border-pine-700/40 px-2.5 py-1.5 text-xs font-medium text-pine-300 transition-colors hover:border-pine-600 hover:text-pine-100"
          >
            <RefreshCw size={13} />
            Refresh
          </button>
        </div>
        {listError && (
          <p role="alert" className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">
            {listError}
          </p>
        )}
        <SlabList rows={slabs} />
      </section>
    </div>
  )
}
