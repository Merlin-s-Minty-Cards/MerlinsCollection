'use client'

import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, Link2, Languages, Check } from 'lucide-react'
import { useAdminApi } from '@/lib/admin-api'
import { useCardImages } from '@/lib/use-card-images'
import CardImage, { TABLE_THUMB_SIZE } from '@/components/admin/shared/CardImage'
import CardPickerRow, { type PickerCard } from '@/components/admin/shared/CardPickerRow'
import DataTable, { type Column } from '@/components/admin/shared/DataTable'
import CardDetailModal from '@/components/admin/shared/CardDetailModal'
import {
  REASON_FILTER_OPTIONS,
  REASON_LABELS,
  clearTriageBody,
  effectiveName,
  reasonsFor,
  reviewReasonLabel,
  type TriageItem,
  type TriageReason,
} from '@/lib/triage'
import { CONDITION_OPTIONS, formatCondition, parseCondition } from '@/lib/constants'

/**
 * Triage — one place for everything that might be wrong.
 * docs/plans/rfc-0008/t11-triage-tab.md
 *
 * The premise, in the owner's words: *"get rid of the assumption that all data
 * in the system, as well as future data, is 100% accurate."* Automation
 * produced this data, so there is one obvious place to correct it.
 *
 * The list is ONE list with reason chips, not a tab per reason: items routinely
 * qualify under several reasons at once (a manual buy entry is flagged *and*
 * has no `card_id`), and parallel queues would show the same card repeatedly.
 * The union comes from `GET /admin/inventory/search?triage=true`.
 */

type CatalogCard = PickerCard

/** Which repair tool is open, and on which item. */
type OpenTool = { item: TriageItem; tool: 'repoint' | 'name' } | null

export default function AdminTriagePage() {
  const api = useAdminApi()
  const [items, setItems] = useState<TriageItem[]>([])
  const [loading, setLoading] = useState(true)
  const [reasonFilter, setReasonFilter] = useState<'' | TriageReason>('')
  // Sold, lost and returned-to-consignor cards will never be corrected — the
  // card is gone — so they are out of the queue unless the admin asks. Leaving
  // them in is what stopped the list ever reaching zero.
  const [includeTerminal, setIncludeTerminal] = useState(false)
  const [openTool, setOpenTool] = useState<OpenTool>(null)
  const [detailItem, setDetailItem] = useState<TriageItem | null>(null)
  const [confirmingBulkClear, setConfirmingBulkClear] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Art is always on here, unlike the toggle the big inventory tables carry:
  // this queue is short by construction, and recognising the card IS the task
  // on a row whose name cannot be read.
  const { getImageUrl } = useCardImages(items.map((i) => i.card_id))

  const fetchItems = useCallback(async () => {
    if (!api.isAuthenticated) return
    setLoading(true)
    try {
      const params: Record<string, string> = { triage: 'true' }
      // ONE parameter, narrowing WITHIN the union by the same predicate that
      // produced the chip. It used to be three — `needs_review`,
      // `missing_card_id`, `missing_english_name` — which meant `flagged`
      // filtered on the stored boolean rather than on the reason, and a new
      // reason had no parameter at all.
      if (reasonFilter) params.triage_reason = reasonFilter
      if (includeTerminal) params.include_terminal = 'true'
      const data = await api.get<{ items: TriageItem[] }>('/inventory/search', params)
      setItems(data?.items ?? [])
    } catch {
      setError('Could not load the triage queue.')
    } finally {
      setLoading(false)
    }
  }, [api, reasonFilter, includeTerminal])

  useEffect(() => { fetchItems() }, [fetchItems])

  /**
   * Drop a row the moment its problem is fixed, with no refetch — matching the
   * Prep Queue's "Priced → removed" pattern. A refetch round-trip here makes
   * every fix feel like it hung, and the row is gone either way.
   */
  const dropRow = (itemId: string) =>
    setItems((rows) => rows.filter((r) => r.item_id !== itemId))

  const clearReview = async (item: TriageItem) => {
    setError(null)
    try {
      await api.put(`/inventory/${item.item_id}`, clearTriageBody())
    } catch {
      // Say so. A silent failure here looks identical to success — the admin
      // moves on believing an item is cleared when it is still in the queue.
      setError('Could not clear that item. It is still in the queue.')
      return
    }
    // Only leaves the list if the flag was its ONLY reason — an unlinked card
    // stays put, still carrying its remaining chip. `reasonsFor` is a PREDICTION
    // here, not the authority: there is no server answer yet, and the row is
    // gone either way.
    const remaining = reasonsFor({ ...item, needs_review: false })
    if (remaining.length === 0) dropRow(item.item_id)
    else setItems((rows) => rows.map((r) =>
      r.item_id === item.item_id
        ? { ...r, needs_review: false, review_reason: null, triage_reasons: remaining }
        : r,
    ))
  }

  /**
   * The third repair tool. A `blank_condition` row's fix is neither a name nor a
   * re-point — it is a condition, and the admin is holding the card.
   *
   * Writes the tier and the modifier as SEPARATE fields. Never a combined
   * `"LP+"`: storage is always two fields, and sending the combined form is the
   * Round 1 enum-validation bug (CLAUDE.md, "Condition vocabulary").
   *
   * Deliberately does NOT clear `needs_review` — the flag and the data are
   * separate facts, so the row keeps its chip until an admin clears it.
   */
  const setCondition = async (item: TriageItem, value: string) => {
    setError(null)
    const { condition, condition_modifier } = parseCondition(value)
    try {
      await api.put(`/inventory/${item.item_id}`, { condition, condition_modifier })
    } catch {
      // Say so, and leave the old value on screen. A silent failure here is a
      // customer-facing price left wrong — every price scales from this field.
      setError('Could not update that condition. The card is unchanged.')
      return
    }
    setItems((rows) => rows.map((r) =>
      r.item_id === item.item_id ? { ...r, condition, condition_modifier } : r,
    ))
  }

  // Counted off the server's own answer, not re-derived here — the confirm
  // dialog names this number, so it has to be the number the endpoint will act
  // on. Zero means no button at all: one promising to clear nothing is worse
  // than none.
  const clearableCount = items.filter((i) => i.bulk_clearable).length

  const bulkClear = async () => {
    setConfirmingBulkClear(false)
    setError(null)
    try {
      await api.post('/inventory/bulk-clear-review', {
        triage_reason: reasonFilter || null,
        include_terminal: includeTerminal,
      })
    } catch {
      setError('Could not clear those flags. Nothing was changed.')
      return
    }
    // Refetched rather than predicted: this one write touches many rows, and
    // the server is the only thing that knows which of them it actually took.
    fetchItems()
  }

  const columns: Column<TriageItem>[] = [
    {
      key: 'name',
      label: 'Card',
      render: (item) => (
        // Art and name are ONE identity unit, so they share a cell instead of
        // sitting in two columns. On a `missing_english_name` row the name is
        // precisely what the admin cannot read — the art is what tells them
        // which card they are looking at, so it leads.
        <div className="flex items-center gap-2.5 min-w-0">
          <CardImage
            imageUrl={getImageUrl(item.card_id)}
            alt={effectiveName(item)}
            size={TABLE_THUMB_SIZE}
          />
          <div className="min-w-0">
            {/* The EFFECTIVE name — what the customer sees, resolved through
                T10's precedence. Showing the raw stored name here would have the
                admin editing blind against the field that outranks theirs. */}
            <div className="text-[13px] text-pine-100 truncate">{effectiveName(item)}</div>
            {/* The catalog id, or an em-dash — the reason chip already says
                "No catalog link", and repeating the phrase here would be noise. */}
            <div className="text-[10px] text-pine-500 font-mono truncate">
              {item.card_id ?? '—'}
            </div>
          </div>
        </div>
      ),
    },
    {
      key: 'reasons',
      label: 'Why',
      // The SERVER's answer, not a local recompute. The rules live in
      // `services/triage.py`; this page renders what they returned, so a row can
      // never appear here with an empty WHY column — which was the report.
      render: (item) => (
        <div className="flex flex-wrap gap-1">
          {(item.triage_reasons ?? []).map((reason) => (
            <span
              key={reason}
              className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px]
                         bg-amber-400/10 text-amber-300 border border-amber-400/25"
            >
              {reason === 'flagged' && <AlertTriangle size={9} />}
              {reason === 'missing_card_id' && <Link2 size={9} />}
              {reason === 'missing_english_name' && <Languages size={9} />}
              {/* A stored flag shows WHY it was flagged when it can: an admin's
                  own note verbatim, a machine key turned into a sentence, and
                  the generic label only when the row carries neither. */}
              {(reason === 'flagged' && reviewReasonLabel(item.review_reason)) ||
                REASON_LABELS[reason]}
            </span>
          ))}
        </div>
      ),
    },
    {
      key: 'condition',
      label: 'Condition',
      className: 'w-28',
      // The third repair tool, inline: a card whose condition the import never
      // recorded is priced to customers as NM — the most expensive tier — and
      // only someone holding the card can say otherwise.
      render: (item) =>
        item.kind !== 'raw' ? (
          <span className="text-[11px] text-pine-600">—</span>
        ) : (
          <select
            aria-label={`Condition for ${effectiveName(item)}`}
            value={formatCondition(
              String(item.condition ?? 'NM'),
              item.condition_modifier,
            )}
            onChange={(e) => setCondition(item, e.target.value)}
            onClick={(e) => e.stopPropagation()}
            className="vault-field px-2 py-1 rounded-md text-[11px] appearance-none cursor-pointer"
          >
            {CONDITION_OPTIONS.map((value) => (
              <option key={value} value={value}>{value}</option>
            ))}
          </select>
        ),
    },
    {
      key: '_tools',
      label: '',
      className: 'text-right w-64',
      render: (item) => (
        <div
          className="flex items-center gap-1.5 justify-end"
          onClick={(e) => e.stopPropagation()}
        >
          <button
            type="button"
            onClick={() => setOpenTool({ item, tool: 'name' })}
            className="px-2 py-1 rounded-md text-[11px] text-pine-300 border border-pine-700/60
                       hover:text-mint hover:border-mint/40 transition-colors"
          >
            Assign English name
          </button>
          <button
            type="button"
            onClick={() => setOpenTool({ item, tool: 'repoint' })}
            className="px-2 py-1 rounded-md text-[11px] text-pine-300 border border-pine-700/60
                       hover:text-amber-300 hover:border-amber-400/40 transition-colors"
          >
            Re-point
          </button>
          {item.needs_review && (
            <button
              type="button"
              onClick={() => clearReview(item)}
              className="px-2 py-1 rounded-md text-[11px] text-mint border border-mint/30
                         hover:bg-mint/10 transition-colors"
            >
              Clear review
            </button>
          )}
        </div>
      ),
    },
  ]

  return (
    <div className="p-6 lg:p-8 max-w-7xl">
      <header className="mb-6">
        <span className="font-mono text-[11px] uppercase tracking-[0.22em] text-mint/70">
          Triage
        </span>
        <h1 className="text-xl font-semibold text-pine-100">
          Needs a look
          <span className="ml-2 text-sm font-normal text-pine-400">({items.length})</span>
        </h1>
        <p className="mt-1 text-xs text-pine-400">
          Cards the system is unsure about. This list is meant to reach zero.
        </p>
      </header>

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <select
          aria-label="Reason"
          value={reasonFilter}
          onChange={(e) => setReasonFilter(e.target.value as '' | TriageReason)}
          className="vault-field px-2.5 py-1.5 rounded-lg text-xs appearance-none cursor-pointer"
        >
          {REASON_FILTER_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>

        <label
          htmlFor="include-terminal"
          className="inline-flex items-center gap-2 text-xs text-pine-300 cursor-pointer"
        >
          <input
            id="include-terminal"
            type="checkbox"
            checked={includeTerminal}
            onChange={(e) => setIncludeTerminal(e.target.checked)}
            className="accent-mint"
          />
          Include sold and closed
        </label>

        {/* Only when there is something to clear. The count is the server's,
            and it is in the button because a bare "Clear all" on a queue this
            destructive tells the admin nothing about what is about to happen. */}
        {clearableCount > 0 && (
          <button
            type="button"
            onClick={() => setConfirmingBulkClear(true)}
            className="ml-auto px-2.5 py-1.5 rounded-lg text-xs text-pine-300
                       border border-pine-700/60 hover:text-mint hover:border-mint/40
                       transition-colors"
          >
            Clear machine flags ({clearableCount})
          </button>
        )}
      </div>

      {error && (
        <div className="mb-4 text-xs text-red-400 bg-red-400/10 border border-red-400/20 rounded px-3 py-2">
          {error}
        </div>
      )}

      {!loading && items.length === 0 ? (
        // Reads as success, not emptiness — an empty queue is the goal state.
        <div className="vault-panel rounded-xl border border-mint/20 px-6 py-10 text-center">
          <Check size={20} className="mx-auto mb-2 text-mint" />
          <p className="text-sm text-pine-100">Nothing needs review</p>
          <p className="mt-1 text-xs text-pine-400">
            Every card is linked, named, and unflagged.
          </p>
        </div>
      ) : (
        <DataTable
          columns={columns}
          data={items}
          keyField="item_id"
          loading={loading}
          emptyMessage="Nothing needs review"
          onRowClick={(item) => setDetailItem(item)}
        />
      )}

      {confirmingBulkClear && (
        <Dialog label="Clear machine flags" onClose={() => setConfirmingBulkClear(false)}>
          <p className="text-[11px] text-pine-300">
            This drops the review flag on the cards below, which were flagged by
            automation and have no other problem. They leave the queue.
          </p>
          {/* Says what it will NOT touch, because that is the part an admin has
              to trust. `blank_condition` is excluded server-side: those cards are
              priced to customers as NM until a human grades them. */}
          <p className="mt-2 text-[11px] text-pine-400">
            A note you typed yourself is left alone, and so is any card flagged
            for having no recorded condition — those are still listed at NM
            prices until someone checks them.
          </p>
          <div className="mt-4 flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setConfirmingBulkClear(false)}
              className="px-3 py-1.5 rounded-md text-[11px] text-pine-400 hover:text-pine-200"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={bulkClear}
              className="px-3 py-1.5 rounded-md text-[11px] font-medium bg-mint/15
                         text-mint border border-mint/30 hover:bg-mint/25"
            >
              Clear {clearableCount} flags
            </button>
          </div>
        </Dialog>
      )}

      {openTool?.tool === 'repoint' && (
        <RepointDialog
          item={openTool.item}
          onClose={() => setOpenTool(null)}
          onRepointed={(cardId) => {
            setOpenTool(null)
            // Predicted, not authoritative — see `reasonsFor`'s docstring.
            const predicted = reasonsFor({ ...openTool.item, card_id: cardId })
            setItems((rows) => rows.map((r) =>
              r.item_id === openTool.item.item_id
                ? { ...r, card_id: cardId, triage_reasons: predicted }
                : r,
            ))
            if (predicted.length === 0) dropRow(openTool.item.item_id)
          }}
        />
      )}

      {openTool?.tool === 'name' && (
        <NameDialog
          item={openTool.item}
          onClose={() => setOpenTool(null)}
          onNamed={(name) => {
            setOpenTool(null)
            const next = { ...openTool.item, display_name_override: name }
            const predicted = reasonsFor(next)
            setItems((rows) => rows.map((r) =>
              r.item_id === openTool.item.item_id
                ? { ...next, triage_reasons: predicted }
                : r,
            ))
            if (predicted.length === 0) dropRow(openTool.item.item_id)
          }}
        />
      )}

      <CardDetailModal
        item={detailItem as Record<string, unknown> | null}
        onClose={() => setDetailItem(null)}
        onUpdated={fetchItems}
      />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Shared catalog search box — the lookup both repair tools are built on
// ---------------------------------------------------------------------------

function useCatalogSearch(query: string) {
  const api = useAdminApi()
  const [results, setResults] = useState<CatalogCard[]>([])

  useEffect(() => {
    const term = query.trim()
    if (term.length < 2) {
      setResults([])
      return
    }
    // Debounced: the endpoint filters a cached full-catalog read (T9), so a
    // request per keystroke is affordable but wasteful.
    let cancelled = false
    const timer = setTimeout(() => {
      api
        .get<{ items: CatalogCard[] }>('/market/search', { name: term })
        .then((data) => { if (!cancelled) setResults(data?.items ?? []) })
        .catch(() => { if (!cancelled) setResults([]) })
    }, 200)
    return () => { cancelled = true; clearTimeout(timer) }
  }, [api, query])

  return results
}

/** The item's expected catalog-id prefix, from its print language. */
function languagePrefix(language?: string | null): string {
  return language === 'JP' ? 'ja' : 'en'
}

// ---------------------------------------------------------------------------
// Repair tool 1 — re-point a mismatched card
// ---------------------------------------------------------------------------

/**
 * The dangerous write in this feature: `card_id` drives pricing, images, set
 * and rarity. Two stages in one dialog — pick a candidate, then confirm against
 * a side-by-side of what is changing.
 */
function RepointDialog({
  item,
  onClose,
  onRepointed,
}: {
  item: TriageItem
  onClose: () => void
  onRepointed: (cardId: string) => void
}) {
  const api = useAdminApi()
  const [query, setQuery] = useState('')
  const [candidate, setCandidate] = useState<CatalogCard | null>(null)
  const [saving, setSaving] = useState(false)
  const [failed, setFailed] = useState(false)
  const results = useCatalogSearch(query)

  const hasHistory = Boolean(item.lineage_id || item.predecessor_item_id)
  const crossLanguage =
    candidate != null && !candidate.card_id.startsWith(`${languagePrefix(item.language)}:`)

  const confirm = async () => {
    if (!candidate) return
    setSaving(true)
    setFailed(false)
    try {
      await api.put(`/inventory/${item.item_id}`, { card_id: candidate.card_id })
      onRepointed(candidate.card_id)
    } catch {
      // Stay open and say so. Closing on a failed write would leave the admin
      // believing the most dangerous edit in this feature had landed.
      setFailed(true)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog
      label={candidate ? 'Confirm re-point' : 'Re-point card'}
      onClose={onClose}
    >
      {candidate ? (
        <>
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-lg border border-pine-700/40 p-3">
              <div className="text-[10px] uppercase tracking-wider text-pine-500 mb-1">Now</div>
              <div className="text-sm text-pine-100">{effectiveName(item)}</div>
              <div className="text-[11px] text-pine-400">{item.card?.set_name ?? '—'}</div>
              <div className="text-[10px] font-mono text-pine-500">{item.card_id ?? 'unlinked'}</div>
            </div>
            <div className="rounded-lg border border-mint/30 p-3">
              <div className="text-[10px] uppercase tracking-wider text-mint mb-1">After</div>
              <div className="text-sm text-pine-100">{candidate.name}</div>
              <div className="text-[11px] text-pine-400">{candidate.set_name ?? '—'}</div>
              <div className="text-[10px] font-mono text-pine-500">{candidate.card_id}</div>
            </div>
          </div>

          {/* Said plainly rather than silently re-resolved: a hidden write here
              would be a second surprise on top of the one being confirmed. */}
          <p className="mt-3 text-[11px] text-pine-400">
            The stored market price still belongs to the old card until the next sync runs.
          </p>

          {hasHistory && (
            <p className="mt-2 text-[11px] text-amber-300">
              This item has trade lineage. Re-pointing rewrites what its history appears
              to refer to — allowed, but check it is really a mistake being fixed.
            </p>
          )}

          {crossLanguage && (
            <p className="mt-2 text-[11px] text-red-300">
              That card is in a different language from this item. A {item.language ?? 'EN'} item
              resolves to a {item.language ?? 'EN'} catalog row by design, so this is almost
              certainly the wrong card.
            </p>
          )}

          {failed && (
            <p className="mt-2 text-[11px] text-red-400">
              That did not save. The item is still linked to its original card.
            </p>
          )}

          <div className="mt-4 flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setCandidate(null)}
              className="px-3 py-1.5 rounded-md text-[11px] text-pine-400 hover:text-pine-200"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={confirm}
              disabled={saving}
              className="px-3 py-1.5 rounded-md text-[11px] font-medium bg-amber-500/15
                         text-amber-300 border border-amber-500/30 hover:bg-amber-500/25
                         disabled:opacity-50"
            >
              Confirm re-point
            </button>
          </div>
        </>
      ) : (
        <CatalogPicker
          query={query}
          onQueryChange={setQuery}
          results={results}
          renderAction={(card) => (
            <CardPickerRow card={card} onSelect={setCandidate} />
          )}
        />
      )}
    </Dialog>
  )
}

// ---------------------------------------------------------------------------
// Repair tool 2 — assign an English display name
// ---------------------------------------------------------------------------

/**
 * Writes `display_name_override` and NOTHING else.
 *
 * The owner's core requirement is that choosing a name never re-links the card,
 * and that the UI designs that confusion out rather than merely avoiding it —
 * hence the standing explanation above the search box.
 */
function NameDialog({
  item,
  onClose,
  onNamed,
}: {
  item: TriageItem
  onClose: () => void
  onNamed: (name: string | null) => void
}) {
  const api = useAdminApi()
  const [query, setQuery] = useState('')
  const [manual, setManual] = useState(item.display_name_override ?? '')
  const [saving, setSaving] = useState(false)
  const [failed, setFailed] = useState(false)
  const results = useCatalogSearch(query)

  const save = async (name: string | null) => {
    setSaving(true)
    setFailed(false)
    try {
      // One field. `card_id` is not in this body and must never be.
      await api.put(`/inventory/${item.item_id}`, { display_name_override: name })
      onNamed(name)
    } catch {
      setFailed(true)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog label="Assign English name" onClose={onClose}>
      <p className="text-[11px] text-mint">
        Choosing a name does not change which card this item is linked to.
      </p>
      <p className="mt-1 text-[11px] text-pine-400">
        Currently showing: <span className="text-pine-200">{effectiveName(item)}</span>
      </p>

      {failed && (
        <p className="mt-2 text-[11px] text-red-400">
          That name did not save. The card is still showing its previous name.
        </p>
      )}

      <div className="mt-3">
        <CatalogPicker
          query={query}
          onQueryChange={setQuery}
          results={results}
          renderAction={(card) => (
            // No `onSelect`: on this dialog the ONLY thing a row can do is
            // lend its name. A clickable row here would be a row that looks
            // like it re-links the item.
            <CardPickerRow
              card={card}
              action={
                <button
                  type="button"
                  disabled={saving}
                  onClick={() => save(card.name)}
                  className="px-2 py-1 rounded-md text-[11px] text-mint
                             border border-mint/30 hover:bg-mint/10 disabled:opacity-50"
                >
                  Use this name
                </button>
              }
            />
          )}
        />
      </div>

      {/* A large and permanent share of the Japanese catalog has no English
          print at all (T10's research), so the search path alone cannot cover
          every item — typing a name has to be a first-class option. */}
      <div className="mt-4">
        <label
          htmlFor="triage-manual-name"
          className="block text-[10px] uppercase tracking-wider text-pine-500 mb-1"
        >
          Or type a name
        </label>
        <div className="flex gap-2">
          <input
            id="triage-manual-name"
            type="text"
            value={manual}
            onChange={(e) => setManual(e.target.value)}
            maxLength={200}
            placeholder="e.g. Chespin (Mega Brave promo)"
            className="flex-1 min-w-0 bg-pine-900 border border-mint/30 rounded px-2 py-1
                       text-xs text-pine-100 focus:outline-none focus:border-mint/60"
            disabled={saving}
          />
          <button
            type="button"
            onClick={() => save(manual.trim() || null)}
            disabled={saving}
            className="px-3 py-1 rounded-md text-[11px] text-mint border border-mint/30
                       hover:bg-mint/10 disabled:opacity-50"
          >
            Save name
          </button>
        </div>
      </div>

      {item.display_name_override && (
        <div className="mt-3 flex justify-end">
          <button
            type="button"
            onClick={() => save(null)}
            disabled={saving}
            className="px-2.5 py-1 rounded-md text-[11px] text-pine-400 hover:text-pine-200
                       disabled:opacity-50"
          >
            Clear name override
          </button>
        </div>
      )}
    </Dialog>
  )
}

// ---------------------------------------------------------------------------
// Small shared pieces
// ---------------------------------------------------------------------------

/**
 * The candidate list both repair dialogs search through.
 *
 * `renderAction` survives because the two dialogs need DIFFERENT actions on
 * the same row shape — "Use this name" versus select-as-candidate — and the
 * distinction between them is the one rule in this feature that must not
 * break. Each caller renders a `CardPickerRow`, which is what puts the art and
 * the price on the row: this page is where the owner's report came from, and
 * on the `missing_english_name` queue the name is in Japanese, so a name-only
 * list asks the admin to choose between rows they cannot read.
 */
function CatalogPicker({
  query,
  onQueryChange,
  results,
  renderAction,
}: {
  query: string
  onQueryChange: (value: string) => void
  results: CatalogCard[]
  renderAction: (card: CatalogCard) => React.ReactNode
}) {
  return (
    <div>
      <label
        htmlFor="triage-catalog-search"
        className="block text-[10px] uppercase tracking-wider text-pine-500 mb-1"
      >
        Search the catalog
      </label>
      <input
        id="triage-catalog-search"
        type="text"
        value={query}
        onChange={(e) => onQueryChange(e.target.value)}
        placeholder="Card name"
        className="w-full bg-pine-900 border border-mint/30 rounded px-2 py-1 text-xs
                   text-pine-100 focus:outline-none focus:border-mint/60"
        autoFocus
      />
      {/* Tall enough for ~5 candidates with art: scanning five cards at a
          glance is the whole point of putting the art there. */}
      <div className="mt-2 max-h-[28rem] overflow-y-auto vault-scroll divide-y divide-pine-700/25">
        {results.map((card) => (
          <div key={card.card_id}>{renderAction(card)}</div>
        ))}
      </div>
    </div>
  )
}

function Dialog({
  label,
  onClose,
  children,
}: {
  label: string
  onClose: () => void
  children: React.ReactNode
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={label}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        // max-w-2xl, not max-w-lg: with art in the candidate rows the narrower
        // dialog squeezes the name until it truncates to nothing, which is
        // worse than the name-only list it replaced.
        className="vault-panel rounded-xl p-5 w-full max-w-2xl shadow-2xl border border-pine-700/50"
      >
        <h2 className="text-sm font-semibold text-pine-100 mb-3">{label}</h2>
        {children}
      </div>
    </div>
  )
}
