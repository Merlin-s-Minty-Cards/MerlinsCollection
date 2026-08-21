'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Unlink, Search } from 'lucide-react'
import { useAdminApi } from '@/lib/admin-api'
import CardImage, { TABLE_THUMB_SIZE } from '@/components/admin/shared/CardImage'
import CardPickerRow, { type PickerCard } from '@/components/admin/shared/CardPickerRow'
import CardSearchPanel from '@/components/admin/shared/CardSearchPanel'
import DataTable, { type Column } from '@/components/admin/shared/DataTable'
import HandValuedBadge from '@/components/admin/shared/HandValuedBadge'
import MoneyInput from '@/components/admin/shared/MoneyInput'
import { adminItemName } from '@/lib/admin-item-name'
import { formatTimestamp } from '@/lib/dates'
import { formatMoney, parseMoney } from '@/lib/money'
import { formatCondition } from '@/lib/constants'
import { type TriageItem } from '@/lib/triage'

/**
 * Unmatched — the cards TCGdex does not carry.
 * docs/plans/rfc-0011/t8-unmatched-queue-page.md
 *
 * The owner's ask: *"there should be a new tab that is just for cards that do
 * not have a match in TCGdex… this tab would let us move cards out of triage,
 * so triage is specifically for cards that actually have errors."*
 *
 * **This queue is not meant to reach zero, and that is the difference from
 * Triage.** A card sits here until the catalog catches up, which may be never;
 * its value is set by hand and no sync will ever revisit it. Triage's empty
 * state reads as success because an empty Triage IS success. A non-empty
 * Unmatched is the ordinary state of the world, so the header says so — without
 * that line an admin reads a list that never shrinks as a backlog they are
 * failing to clear, and stops opening the tab.
 *
 * **There is no parallel list endpoint.** The list is
 * `GET /admin/inventory/search?no_catalog_match=true` (RFC 0011 T5), the same
 * rule Triage's router docstring states for `?triage=true`. The only endpoint
 * this page adds is T7's ranked suggestions, which cannot be derived from a
 * search result.
 */

/** A card as T7's suggestions endpoint returns it. */
interface Candidate {
  card_id: string
  name: string
  set_id?: string
  set_name?: string
  number?: string
  rarity?: string | null
  image_small?: string | null
  /** NEAR MINT, and NOT condition-adjusted — there is no condition in a catalog row. */
  market_price?: string | number | null
  /** `brief` = never fetched. `full` with no price = no provider covers it. */
  detail?: string | null
  last_synced_at?: string | null
  score: number
  why: string
}

interface SuggestionsResponse {
  items: { item_id: string; candidates: Candidate[] }[]
  items_with_candidates: number
}

/**
 * Project a candidate onto the shared picker's card shape.
 *
 * One rename (`market_price` → `display_price`) and one re-nest
 * (`image_small` → `images.small`). `detail` and `last_synced_at` pass through
 * by name and are load-bearing: they are what let `CardPickerRow` say *"no price
 * yet"* rather than *"not priced"*, and show a stale figure's age. **The price
 * is never recomputed here** — it was chosen server-side by the one shared
 * finish-aware lookup, and a second copy of that walk is how 174 of 213 live
 * items once went unpriced.
 */
function asPickerCard(candidate: Candidate): PickerCard {
  return {
    card_id: candidate.card_id,
    name: candidate.name,
    set_id: candidate.set_id,
    set_name: candidate.set_name,
    number: candidate.number,
    rarity: candidate.rarity ?? undefined,
    images: { small: candidate.image_small },
    display_price: candidate.market_price,
    detail: candidate.detail,
    last_synced_at: candidate.last_synced_at,
  }
}

/** Which dialog is open, and on what. */
type OpenDialog =
  | { kind: 'pair'; item: TriageItem; card: PickerCard }
  | { kind: 'search'; item: TriageItem }
  | null

export default function AdminUnmatchedPage() {
  const api = useAdminApi()
  const [items, setItems] = useState<TriageItem[]>([])
  const [suggestions, setSuggestions] = useState<Record<string, Candidate[]>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [dialog, setDialog] = useState<OpenDialog>(null)
  // Raw text per row, so `MoneyInput` can hold a half-typed `1,` without the
  // page trying to parse it. Seeded lazily from the stored value.
  const [valueDrafts, setValueDrafts] = useState<Record<string, string>>({})
  // RFC 0013 T4b. `null` (the default) means "let the candidate-count/park-
  // date ordering below decide" — this page's whole point is surfacing the
  // most actionable row first, and a plain column sort would fight that.
  // Clicking a header opts OUT of that ordering in favor of the requested
  // column, same as any other admin list.
  const [sortKey, setSortKey] = useState<string | null>(null)
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')

  const fetchQueue = useCallback(async () => {
    if (!api.isAuthenticated) return
    setLoading(true)
    try {
      // The list and the suggestions are independent reads, so they go together
      // rather than one after the other. `Promise.all` and not `allSettled`:
      // suggestions failing while the list succeeds would render a queue with
      // every row silently claiming it has no candidates, which is a wrong
      // answer wearing the shape of a right one.
      const listParams: Record<string, string> = { no_catalog_match: 'true' }
      if (sortKey) listParams.sort = `${sortKey}_${sortDir}`
      const [list, ranked] = await Promise.all([
        api.get<{ items: TriageItem[] }>('/inventory/search', listParams),
        api.get<SuggestionsResponse>('/unmatched/suggestions', { limit: '3' }),
      ])
      setItems(list?.items ?? [])
      setSuggestions(
        Object.fromEntries(
          (ranked?.items ?? []).map((row) => [row.item_id, row.candidates ?? []]),
        ),
      )
    } catch {
      setError('Could not load the unmatched queue.')
    } finally {
      setLoading(false)
    }
  }, [api, sortKey, sortDir])

  useEffect(() => { fetchQueue() }, [fetchQueue])

  /**
   * Drop a row the moment it is dealt with, with NO refetch — the same pattern
   * as the Prep Queue's "Priced → removed" and Triage's own repairs. A refetch
   * round-trip makes every action feel like it hung, and the row is gone either
   * way.
   */
  const dropRow = (itemId: string) =>
    setItems((rows) => rows.filter((r) => r.item_id !== itemId))

  /**
   * Pair a parked card with a catalog card.
   *
   * **Sends `card_id` and NOTHING else.** Assigning a `card_id` unparks the row
   * server-side (T5), so adding `no_catalog_match: false` here would be a second
   * client-side copy of a server rule — and sending that flag *without* a
   * `card_id` would hand the row back to Triage, which is the opposite of what
   * this button does.
   */
  const pair = async (item: TriageItem, cardId: string) => {
    setError(null)
    try {
      await api.put(`/inventory/${item.item_id}`, { card_id: cardId })
    } catch {
      // Say so, and keep the row. A silent failure here looks exactly like
      // success: the row vanishes and the admin believes the card was paired.
      setError('Could not pair that card. It is still in this queue.')
      return
    }
    setDialog(null)
    dropRow(item.item_id)
  }

  /**
   * The `unarchive` of this feature. Parking that cannot be undone is just a
   * slower delete — the same reasoning that gives every archivable entity an
   * unarchive route.
   */
  const backToTriage = async (item: TriageItem) => {
    setError(null)
    try {
      await api.put(`/inventory/${item.item_id}`, { no_catalog_match: false })
    } catch {
      setError('Could not move that card back to Triage. It is still in this queue.')
      return
    }
    dropRow(item.item_id)
  }

  /**
   * Commit a hand-typed value.
   *
   * Through `parseMoney`, never `parseFloat`: `parseFloat("1,300")` is **1** and
   * is **not** `NaN`, so it sails through every isNaN guard and books a silent
   * $1,299 loss. The wire format is unchanged — `String(parsed)`, where a string
   * already went.
   */
  const commitValue = async (item: TriageItem, raw: string) => {
    const parsed = parseMoney(raw)
    // `=== null`, never falsiness: `parseMoney('0')` is `0`, and a legitimately
    // free card is a real thing at a buy table.
    if (parsed === null) return
    if (String(parsed) === String(item.current_market_value ?? '')) return
    setError(null)
    try {
      await api.put(`/inventory/${item.item_id}`, {
        current_market_value: String(parsed),
      })
    } catch {
      setError('Could not save that value.')
      return
    }
    setItems((rows) => rows.map((r) =>
      r.item_id === item.item_id ? { ...r, current_market_value: String(parsed) } : r))
  }

  const candidatesFor = useCallback(
    (item: TriageItem) => suggestions[item.item_id] ?? [],
    [suggestions],
  )

  /**
   * Rows that became actionable float to the top — "which card can I pair now"
   * is the question this page answers. Within each group, oldest park first: a
   * card parked in March has waited longer than one parked yesterday.
   *
   * Sorted on a COPY. `Array.prototype.sort` mutates, and sorting the state
   * array in place edits React's own reference.
   *
   * Only applies when no column sort is active — the moment an admin clicks
   * a header, `items` already arrived in the server's requested order (RFC
   * 0013 T4b) and this re-sort would silently override that choice.
   */
  const ordered = useMemo(() => {
    if (sortKey) return items
    return [...items].sort((a, b) => {
      const byCandidates = candidatesFor(b).length - candidatesFor(a).length
      if (byCandidates !== 0) return byCandidates
      return String(a.no_catalog_match_at ?? '')
        .localeCompare(String(b.no_catalog_match_at ?? ''))
    })
  }, [items, candidatesFor, sortKey])

  const handleSort = (key: string) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir('desc')
    }
  }

  const columns: Column<TriageItem>[] = [
    {
      // `name` (not `card`) so it round-trips through inventory_sort.py's
      // `name` -> `display_name` alias when clicked — see the sortKey
      // comment on `ordered` above for why the default stays candidate-first.
      key: 'name',
      label: 'Card',
      sortable: true,
      render: (item) => (
        <div className="flex items-center gap-2.5">
          {/* Always the placeholder, and deliberately NOT `useCardImages`: a
              parked item has no `card_id` by definition, so a lookup could
              never succeed. Firing one per row to render the same placeholder
              is a request that exists only to fail. */}
          <CardImage imageUrl={null} alt={adminItemName(item)} size={TABLE_THUMB_SIZE} />
          <div className="min-w-0">
            <div className="truncate text-xs text-pine-100">{adminItemName(item)}</div>
            <div className="truncate text-[10px] text-pine-400">
              {[
                item.language && item.language !== 'EN' ? String(item.language) : null,
                // Guarded rather than defaulted: a blank condition is a real
                // Triage reason of its own, and rendering "NM" for one would
                // show the most expensive tier for a card nobody has graded.
                item.condition
                  ? formatCondition(item.condition, item.condition_modifier)
                  : null,
              ].filter(Boolean).join(' · ')}
            </div>
          </div>
        </div>
      ),
    },
    {
      // `no_catalog_match_at`, the real SORT_FIELDS key — matches what this
      // column actually renders (the park timestamp).
      key: 'no_catalog_match_at',
      label: 'Parked',
      sortable: true,
      render: (item) => (
        // `formatTimestamp`, because `no_catalog_match_at` is a DATETIME. Never
        // `new Date()` on a date-only string, and never `toISOString()` here.
        <span className="text-[11px] text-pine-400">
          {formatTimestamp(item.no_catalog_match_at) || '—'}
        </span>
      ),
    },
    {
      key: 'value',
      label: 'Hand value',
      render: (item) => (
        <div className="w-32 space-y-1">
          <MoneyInput
            label={`Hand value for ${adminItemName(item)}`}
            value={valueDrafts[item.item_id]
              ?? String(item.current_market_value ?? '')}
            onChange={(raw) =>
              setValueDrafts((d) => ({ ...d, [item.item_id]: raw }))}
            onBlur={() => commitValue(
              item,
              valueDrafts[item.item_id] ?? String(item.current_market_value ?? ''),
            )}
            className="vault-field w-full rounded-lg px-2 py-1 font-mono text-xs"
            placeholder="0.00"
          />
          <HandValuedBadge />
        </div>
      ),
    },
    {
      key: 'suggestions',
      // The label carries the price's meaning, once, rather than repeating a
      // caption on every row: a catalog figure is NEAR MINT and is not adjusted
      // for this card's condition. Unlabelled beside a DMG card it reads as that
      // card's sale price.
      label: 'Suggestions · Market (NM)',
      render: (item) => {
        const candidates = candidatesFor(item)
        if (candidates.length === 0) {
          return (
            <span className="text-[11px] text-pine-500">
              No candidates — search the catalog
            </span>
          )
        }
        return (
          <div className="min-w-[22rem] divide-y divide-pine-700/25">
            {candidates.map((candidate) => (
              <div key={candidate.card_id}>
                <CardPickerRow
                  card={asPickerCard(candidate)}
                  action={
                    <button
                      type="button"
                      onClick={() => setDialog({
                        kind: 'pair', item, card: asPickerCard(candidate),
                      })}
                      className="px-2.5 py-1 rounded-md text-[11px] font-medium
                                 bg-mint/15 text-mint border border-mint/30
                                 hover:bg-mint/25 transition-colors"
                    >
                      Pair
                    </button>
                  }
                />
                {/* The REASON, not the score. A bare 0.7 tells the person
                    holding the card nothing; "name matches, number differs"
                    tells them exactly what to check against the card in hand. */}
                <div className="px-3 pb-1.5 text-[10px] text-pine-500">
                  {candidate.why}
                </div>
              </div>
            ))}
          </div>
        )
      },
    },
    {
      key: '_actions',
      label: '',
      render: (item) => (
        <div className="flex flex-col items-end gap-1.5">
          {/* ALWAYS present, including on a row that already has three strong
              candidates. Owner constraint, verbatim: "you must also have the
              option for the user to search the whole catalog if none of those
              candidates match." An escape hatch reachable only when the primary
              path fails cannot be reached in the case where the primary path
              succeeds and is WRONG — which is the more expensive failure,
              because nothing signals it. */}
          <button
            type="button"
            onClick={() => setDialog({ kind: 'search', item })}
            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px]
                       text-pine-300 border border-pine-700/60 hover:text-mint
                       hover:border-mint/40 transition-colors whitespace-nowrap"
          >
            <Search size={11} /> Search catalog
          </button>
          <button
            type="button"
            onClick={() => backToTriage(item)}
            className="px-2.5 py-1 rounded-md text-[11px] text-pine-400
                       hover:text-pine-200 transition-colors whitespace-nowrap"
          >
            Back to Triage
          </button>
        </div>
      ),
    },
  ]

  const isEmpty = !loading && ordered.length === 0

  return (
    <div className="p-6 lg:p-8">
      <header className="mb-6">
        <span className="font-mono text-[11px] uppercase tracking-[0.22em] text-mint/70">
          Unmatched
        </span>
        <h1 className="text-xl font-semibold text-pine-100">
          Waiting on the catalog
          <span className="ml-2 text-sm font-normal text-pine-400">
            ({ordered.length})
          </span>
        </h1>
        <p className="mt-1 text-xs text-pine-400">
          Cards TCGdex does not carry yet. They are priced by hand and will stay here
          until the catalog catches up — this list is not meant to reach zero.
        </p>
      </header>

      {error && (
        <div className="mb-4 text-xs text-red-400 bg-red-400/10 border border-red-400/20
                        rounded px-3 py-2">
          {error}
        </div>
      )}

      {isEmpty ? (
        // Neutral, not celebratory and not alarming. The queue SHIPS empty —
        // nothing was backfilled — so a correct install lands here on day one
        // and must not read as breakage.
        <div className="vault-panel rounded-xl border border-pine-700/40 px-6 py-10
                        text-center">
          <Unlink size={20} className="mx-auto mb-2 text-pine-400" />
          <p className="text-sm text-pine-100">Nothing is waiting on the catalog</p>
          <p className="mt-1 text-xs text-pine-400">
            Cards get here from Triage, when you confirm TCGdex does not carry them.
          </p>
        </div>
      ) : (
        <DataTable
          columns={columns}
          data={ordered}
          keyField="item_id"
          loading={loading}
          emptyMessage="Nothing is waiting on the catalog"
          sortKey={sortKey}
          sortDir={sortDir}
          onSort={handleSort}
        />
      )}

      {dialog?.kind === 'pair' && (
        <PairDialog
          item={dialog.item}
          card={dialog.card}
          onClose={() => setDialog(null)}
          onConfirm={() => pair(dialog.item, dialog.card.card_id)}
        />
      )}

      {dialog?.kind === 'search' && (
        <CatalogSearchDialog
          item={dialog.item}
          onClose={() => setDialog(null)}
          onPick={(card) => setDialog({ kind: 'pair', item: dialog.item, card })}
        />
      )}
    </div>
  )
}

/**
 * The pairing confirm — a before/after, the same discipline as `RepointDialog`.
 *
 * It is the same write on the same load-bearing field: `card_id` drives pricing,
 * images, set and rarity. The copy NAMES the hand-set figure it is about to hand
 * back to the nightly sync, because a dialog that silently discards $40.00 an
 * admin typed is exactly the surprise this codebase writes confirmation copy to
 * prevent.
 */
function PairDialog({
  item,
  card,
  onClose,
  onConfirm,
}: {
  item: TriageItem
  card: PickerCard
  onClose: () => void
  onConfirm: () => void
}) {
  const handValue = parseMoney(String(item.current_market_value ?? ''))
  const label = [card.name, card.number && `#${card.number}`].filter(Boolean).join(' ')

  return (
    <Dialog label={`Pair with ${label}`} onClose={onClose}>
      <CardPickerRow card={card} />
      <p className="mt-3 text-[12px] text-pine-300">
        <span className="text-pine-100">{adminItemName(item)}</span> will be linked to{' '}
        <span className="font-mono text-[11px] text-pine-400">{card.card_id}</span> and
        will leave this queue.
      </p>
      <p className="mt-2 text-[11px] text-pine-400">
        {handValue === null ? (
          <>Its value will be maintained by the nightly sync from then on.</>
        ) : (
          <>
            Its value will be maintained by the nightly sync from then on, replacing
            the <span className="text-amber-300">{formatMoney(handValue)}</span> you set
            by hand.
          </>
        )}
      </p>

      <div className="mt-4 flex justify-end gap-2">
        <button
          type="button"
          onClick={onClose}
          className="px-3 py-1.5 rounded-md text-[11px] text-pine-400 hover:text-pine-200"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={onConfirm}
          className="px-3 py-1.5 rounded-md text-[11px] font-medium bg-mint/15 text-mint
                     border border-mint/30 hover:bg-mint/25"
        >
          Pair with {label}
        </button>
      </div>
    </Dialog>
  )
}

/**
 * Full-catalog search, the door that is always open.
 *
 * There is deliberately **no `onManualEntry`** here: a parked card is being
 * *paired* with a catalog row that already exists, so there is nothing to
 * create. That is the one shape of escape hatch this page does not need.
 */
function CatalogSearchDialog({
  item,
  onClose,
  onPick,
}: {
  item: TriageItem
  onClose: () => void
  onPick: (card: PickerCard) => void
}) {
  return (
    <Dialog label={`Search the catalog for ${adminItemName(item)}`} onClose={onClose}>
      <CardSearchPanel onSelect={onPick} autoFocus />
    </Dialog>
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
        // dialog squeezes the name until it truncates to nothing.
        className="vault-panel rounded-xl p-5 w-full max-w-2xl shadow-2xl
                   border border-pine-700/50"
      >
        <h2 className="text-sm font-semibold text-pine-100 mb-3">{label}</h2>
        {children}
      </div>
    </div>
  )
}
