'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Keyboard, RefreshCw } from 'lucide-react'
import { useAdminApi, AdminApiError } from '@/lib/admin-api'
import { formatMoney } from '@/lib/money'
import SlabEntryForm, { type StagedSlab } from '@/components/admin/slabs/SlabEntryForm'
import StagingTable from '@/components/admin/slabs/StagingTable'
import SlabList, { type SlabRow } from '@/components/admin/slabs/SlabList'

type PricedFilter = 'all' | 'true' | 'false'

// Owner report: "sold cards are not being automatically removed from our
// slab inventory." GET /admin/slabs deliberately never hides a status by
// default (backend/tests/routers/admin/test_slabs.py,
// test_status_narrows_the_list_and_nothing_is_hidden_by_default) — a sold
// slab is still real purchase history, so the endpoint keeps returning it.
// The gap was purely on this page: it fetches every status already (no
// `status` param is ever sent) but never gave the admin a way to filter one
// out, so "Slabs on the shelf" silently accumulated every slab ever sold.
// Hiding these three by default — with a toggle for the full history — is a
// client-side filter over the same response, matching the "hidden by
// default, visible on request" shape the archiving pattern uses elsewhere
// (CLAUDE.md, "ARCHIVING IS ONE PATTERN"). `on_hold` and `out_for_grading`
// stay visible: the slab is still owned and still physically accounted for.
const GONE_STATUSES = new Set(['sold', 'lost', 'returned_to_consignor'])

export default function SlabsPage() {
  const api = useAdminApi()
  const [rows, setRows] = useState<StagedSlab[]>([])
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [slabs, setSlabs] = useState<SlabRow[]>([])
  const [priced, setPriced] = useState<PricedFilter>('all')
  const [showGone, setShowGone] = useState(false)
  const [listError, setListError] = useState<string | null>(null)
  // Client-side only — the backend already returns every status unfiltered
  // (see GONE_STATUSES above), so toggling this needs no refetch.
  const visibleSlabs = useMemo(
    () => (showGone ? slabs : slabs.filter((s) => !GONE_STATUSES.has(s.status))),
    [slabs, showGone],
  )
  // RFC 0013 T4d — server-side sort via services/slabs_sort.py, same contract
  // as every other admin list. `null` keeps the endpoint's existing
  // newest-first default untouched.
  const [sortKey, setSortKey] = useState<string | null>(null)
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')

  // Intake affordances. The form is put away by default, matching the other
  // admin tabs — the page's resting state is the shelf, not a blank form.
  //
  // Manual entry is the ONLY toggle now. RFC 0010 T12 removed the "Scan cert"
  // button along with the two PSA-blocked ones: the owner's point is that a
  // wedge scanner just types the number, so the ordinary cert field already IS
  // the scanner target. `CertInput` keeps the two things that make that true —
  // Enter advances rather than submits, and a trailing \r\n is stripped.
  const [entryOpen, setEntryOpen] = useState(false)
  // Bumping this pulls focus to the cert field without remounting the form.
  const [focusToken, setFocusToken] = useState(0)

  // The pricing run that follows a commit. A SECOND, separate status line: the
  // commit's success message lands first and unconditionally, because a vendor
  // 500 or a spent quota must degrade to "committed, not yet priced" — a state
  // the product already models, at /admin/slabs?priced=false.
  const [pricing, setPricing] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => () => { if (pollRef.current) clearTimeout(pollRef.current) }, [])

  const loadSlabs = useCallback(async () => {
    try {
      // `get(path, params?)` takes the params RECORD positionally — it is not a
      // FetchOptions wrapper (lib/admin-api.ts:84-88). Wrapping it in
      // `{ params: … }` made the request builder iterate the outer object and
      // emit `?params=[object Object]`, so `priced` never reached the backend
      // and the worklist returned every slab. Caught by `next build`, not by
      // the suite — vitest does not typecheck.
      const params: Record<string, string> = {}
      if (priced !== 'all') params.priced = priced
      if (sortKey) params.sort = `${sortKey}_${sortDir}`
      const body = await api.get<{ items: SlabRow[]; total: number }>(
        '/slabs',
        Object.keys(params).length > 0 ? params : undefined,
      )
      setSlabs(body?.items ?? [])
      setListError(null)
    } catch (e) {
      // The list failing must never take the ENTRY form down with it — intake
      // is the job this page exists for, and it does not depend on the list.
      setListError(`Could not load the slab list: ${(e as Error).message}`)
    }
  }, [api, priced, sortKey, sortDir])

  useEffect(() => {
    loadSlabs()
  }, [loadSlabs])

  const handleSort = (key: string) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir('desc')
    }
  }

  /**
   * Price the batch that was just committed — AFTER the commit, never inside
   * its write loop.
   *
   * T0 exists because a money write blew up mid-loop; putting a metered
   * third-party HTTP call inside the same loop would rebuild that failure with
   * a worse trigger. So this runs on its own, reports on its own line, and
   * cannot fail, obscure or roll back the commit.
   *
   * It reuses `POST /slabs/refresh-prices` scoped to the ids the confirm just
   * created. Not a second pricing path: `refresh_graded_prices` already orders
   * never-priced slabs first, so a slab committed a second ago is already at
   * the head of its queue — what was missing was the scope, without which a
   * 3-slab intake spends the whole day's 50-lookup budget on the shelf.
   */
  const priceBatch = useCallback(async (itemIds: string[], attempt = 0) => {
    if (itemIds.length === 0) return
    if (attempt === 0) {
      setPricing('Pricing the batch…')
      try {
        await api.post('/slabs/refresh-prices', { item_ids: itemIds })
      } catch (e) {
        const conflict = e instanceof AdminApiError && e.status === 409
        setPricing(
          conflict
            ? 'Committed, not yet priced — a price refresh is already running. '
              + 'These slabs are first in line tonight.'
            : `Committed, not yet priced — ${(e as Error).message}. `
              + 'They are listed under "Not priced".',
        )
        return
      }
    }

    try {
      const status = await api.get<{
        state: string; priced?: number | null; failures?: number | null
        credits_remaining?: number | null; error?: string | null
      }>('/slabs/refresh-prices/status')

      if (status.state === 'running' && attempt < 20) {
        pollRef.current = setTimeout(() => priceBatch(itemIds, attempt + 1), 1500)
        return
      }
      if (status.state === 'completed') {
        // The credit figure is on screen because the ceiling is FIFTY lookups a
        // day, shared with the nightly job — a 30-slab intake day eats 60% of
        // it, and that is not something to discover from a log.
        const credits = status.credits_remaining
        setPricing(
          `Priced ${status.priced ?? 0} of ${itemIds.length}`
          + (credits == null ? '' : ` · ${credits} credits left today`),
        )
        loadSlabs()
        return
      }
      setPricing(
        `Committed, not yet priced — ${status.error ?? 'the pricing run did not finish'}. `
        + 'They are listed under "Not priced".',
      )
    } catch (e) {
      setPricing(`Committed, not yet priced — ${(e as Error).message}.`)
    }
  }, [api, loadSlabs])

  const commit = async () => {
    if (rows.length === 0) return
    setBusy(true); setError(null); setResult(null); setPricing(null)
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

      const confirmed = await api.post<{ item_ids?: string[] }>(
        `/purchases/${buyId}/confirm`, {},
      )
      const spend = rows.reduce((sum, r) => sum + r.buy_price, 0)
      // FIRST and UNCONDITIONALLY. Whatever pricing does next, the money write
      // landed and the operator must be told so without qualification.
      setResult(`Committed ${rows.length} slab(s), ${formatMoney(spend)}`)
      setRows([])
      // Return focus to the cert field so the next slab can go straight in --
      // with a stack of slabs in hand, that is the interaction this page lives
      // on. Closes the "refocus the cert field" T4 follow-up.
      setFocusToken((n) => n + 1)
      // The batch is now real inventory, so the list below is stale.
      loadSlabs()
      // Deliberately NOT awaited inside the commit's try: a pricing failure is
      // not a commit failure and must never reach the catch below.
      priceBatch(confirmed?.item_ids ?? [])
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
          ONE route, and it is the only one there will be. PSA's cert API became
          a PAID feature and the owner declined it on 2026-08-10, so camera
          capture and cert auto-fill moved from deferred to WITHDRAWN (RFC 0009
          T2/T5) and their disabled buttons are gone — a disabled button implies
          a roadmap, and there is none.

          The "Scan cert" button is gone for a different reason: a wedge scanner
          is just a keyboard that types fast and ends with Enter, so the plain
          cert field below already IS the scan target. `CertInput` keeps the two
          things that make that true — Enter advances rather than submits, and a
          trailing 
 is stripped. */}
      <section className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setEntryOpen((open) => !open)}
            aria-expanded={entryOpen}
            className="inline-flex items-center gap-1.5 rounded-lg border border-mint/30 bg-mint/15 px-3.5 py-2 text-xs font-medium text-mint transition-colors hover:bg-mint/25"
          >
            <Keyboard size={14} />
            Manual entry
          </button>
        </div>

        {entryOpen && (
          <div className="vault-panel rounded-xl p-4">
            <SlabEntryForm
              onAdd={(row) => setRows((rs) => [...rs, row])}
              focusToken={focusToken}
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
        {/* A SECOND, separate line. Pricing is not part of the commit and must
            never look like it: "committed, not yet priced" is a real, modelled
            state, not a failure. */}
        {pricing && (
          <p role="status" className="rounded-lg border border-pine-700/40 bg-pine-800/30 px-3 py-2 text-xs text-pine-300">
            {pricing}
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
          <h2 className="text-sm font-semibold text-pine-100">
            Slabs on the shelf ({visibleSlabs.length})
          </h2>
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
          <label className="flex items-center gap-1.5 text-[11px] uppercase tracking-wider text-pine-400">
            <input
              type="checkbox"
              checked={showGone}
              onChange={(e) => setShowGone(e.target.checked)}
            />
            Show sold / gone
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
        <SlabList rows={visibleSlabs} sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
      </section>
    </div>
  )
}
