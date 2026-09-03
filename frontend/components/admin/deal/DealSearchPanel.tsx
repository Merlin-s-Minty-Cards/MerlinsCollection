'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useAdminApi } from '@/lib/admin-api'
import { useCardImages } from '@/lib/use-card-images'
import { adminItemName, type AdminNamedItem } from '@/lib/admin-item-name'
import { formatCondition } from '@/lib/constants'
import CardSearchPanel from '@/components/admin/shared/CardSearchPanel'
import type { PickerCard } from '@/components/admin/shared/CardPickerRow'
import DealCardRow from './DealCardRow'

/**
 * One search panel for Buy, Sell and Trade (RFC 0011 T14, §J).
 *
 * The catalog source DELEGATES to T11's `CardSearchPanel` — a sixth local
 * catalog search is exactly what that shared component exists to prevent. The
 * inventory source is the picker that has no image at all today
 * (`trade/page.tsx:713`), and fixing it is half the owner's complaint; it
 * renders the same `DealCardRow` the catalog side and the staged legs use.
 */

export type DealMode = 'buy' | 'sell' | 'trade'
export type SearchSource = 'catalog' | 'inventory'

/**
 * Buy acquires (catalog), Sell disposes (inventory), Trade does both.
 *
 * `'both'` is what makes the toggle render. In Buy and Sell the toggle is
 * ABSENT, not disabled: a control that can be set exactly one way is noise,
 * and this codebase deletes rather than disables (`/admin/slabs`' three
 * removed buttons).
 */
export function sourceForMode(mode: DealMode): SearchSource | 'both' {
  if (mode === 'buy') return 'catalog'
  if (mode === 'sell') return 'inventory'
  return 'both'
}

/** The inventory-item fields this panel reads. Deliberately narrow. */
export interface DealInventoryItem extends AdminNamedItem {
  item_id: string
  card_id?: string | null
  set_name?: string | null
  card_number?: string | null
  condition?: string | null
  condition_modifier?: string | null
  location?: string | null
  current_market_value?: string | number | null
  sticker_price?: string | number | null
  /** Already in `/admin/inventory/search`'s response — RFC 0024 T2 just reads it. */
  cost_basis?: string | number | null
  market_value_at_purchase?: string | number | null
}

const DEBOUNCE_MS = 300

export interface DealSearchPanelProps {
  mode: DealMode
  source: SearchSource
  /** Ignored unless `mode === 'trade'` — nothing else can change the source. */
  onSourceChange: (s: SearchSource) => void
  onPickCatalog: (card: PickerCard) => void
  onPickInventory: (item: DealInventoryItem) => void
  /**
   * A PERMANENT control, present before any search runs. It does not open a
   * form here; `IncomingCardForm` decides what manual entry looks like. See
   * CLAUDE.md, "AN ESCAPE HATCH IS NEVER GATED ON THE FAILURE OF THE PATH IT
   * ESCAPES".
   */
  onManualEntry: () => void
  /**
   * Whether this mode's session even has an incoming leg to add a manual
   * entry to. `false` in Sell — a sale disposes of stock you already own
   * (catalog-matched or not), so "manual entry" (an off-catalog NEW item) is
   * meaningless there and previously threw `'A sell session has no incoming
   * leg'`, surfaced as a raw `alert` (final-review Important 5). This is
   * NOT the escape-hatch rule (manual entry isn't a fallback for a failed
   * catalog search here — it's a control for a leg kind Sell doesn't have).
   */
  manualEntryAllowed: boolean
  /** RFC 0024 T2 — same prop, same name, threaded from `/admin/trade`. Hides
   *  price-paid and the acquisition ratio on inventory rows; market stays. */
  customerView?: boolean
}

function InventorySearch({
  onPick,
  customerView,
}: {
  onPick: (item: DealInventoryItem) => void
  customerView: boolean
}) {
  const api = useAdminApi()
  const [name, setName] = useState('')
  const [results, setResults] = useState<DealInventoryItem[]>([])

  // Responses do not resolve in send order — without this guard a slow reply
  // for an earlier keystroke overwrites a faster one for a later one.
  const seqRef = useRef(0)

  const search = useCallback(
    async (q: string) => {
      if (!q.trim()) {
        setResults([])
        return
      }
      const seq = ++seqRef.current
      try {
        const res = await api.get<{ items: DealInventoryItem[] }>('/inventory/search', {
          name: q.trim(),
          status: 'available',
        })
        if (seq !== seqRef.current) return
        setResults(res.items.slice(0, 12))
      } catch {
        // A failed request is not evidence the stock lacks the card.
        if (seq === seqRef.current) setResults([])
      }
    },
    [api],
  )

  useEffect(() => {
    const t = setTimeout(() => search(name), DEBOUNCE_MS)
    return () => clearTimeout(t)
  }, [name, search])

  // Batched, one POST for the whole page of results — never one per row.
  const cardIds = useMemo(() => results.map((i) => i.card_id), [results])
  const { getImageUrl } = useCardImages(cardIds)

  return (
    <div className="flex flex-col gap-2.5">
      <input
        aria-label="Card name"
        value={name}
        placeholder="Search available stock…"
        className="vault-field w-full rounded-lg px-2.5 py-1.5 text-xs sm:max-w-md"
        onChange={(e) => setName(e.target.value)}
      />

      {results.length > 0 && (
        <ul className="vault-panel max-h-[28rem] divide-y divide-pine-700/25 overflow-y-auto vault-scroll rounded-lg">
          {results.map((item) => (
            <li key={item.item_id}>
              <DealCardRow
                card={{
                  card_id: item.card_id,
                  name: adminItemName(item),
                  meta: [
                    item.set_name,
                    item.card_number && `#${item.card_number}`,
                    item.condition && formatCondition(item.condition, item.condition_modifier),
                    item.location,
                  ]
                    .filter(Boolean)
                    .join(' · '),
                  imageUrl: getImageUrl(item.card_id),
                  // The stored value already carries the condition multiplier
                  // (the nightly denormalizer bakes it in) — adjusting it here
                  // would apply it twice.
                  price: item.sticker_price ?? item.current_market_value,
                  priceLabel: item.sticker_price ? 'sticker' : 'market',
                  // RFC 0024 T2 — context for the deal, not the headline. Paid
                  // is our cost basis, so it (and the ratio it feeds) is
                  // omitted entirely under customer view rather than hidden.
                  marketValue: item.market_value_at_purchase,
                  ...(customerView ? {} : { pricePaid: item.cost_basis }),
                  showRatio: !customerView,
                }}
                onAdd={() => onPick(item)}
              />
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export default function DealSearchPanel({
  mode,
  source,
  onSourceChange,
  onPickCatalog,
  onPickInventory,
  onManualEntry,
  manualEntryAllowed,
  customerView = false,
}: DealSearchPanelProps) {
  const showToggle = sourceForMode(mode) === 'both'
  // Outside trade, the caller's `source` cannot be wrong — but the mode is the
  // authority, so a stale prop cannot show Sell a catalog search.
  const active: SearchSource = showToggle ? source : (sourceForMode(mode) as SearchSource)

  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        {showToggle ? (
          <div role="radiogroup" aria-label="Search source" className="flex items-center gap-3">
            {(['catalog', 'inventory'] as const).map((s) => (
              <label key={s} className="flex items-center gap-1.5 text-xs text-pine-200">
                <input
                  type="radio"
                  name="deal-search-source"
                  value={s}
                  checked={active === s}
                  onChange={() => onSourceChange(s)}
                  className="accent-mint"
                />
                {s === 'catalog' ? 'Catalog' : 'Inventory'}
              </label>
            ))}
          </div>
        ) : (
          <span />
        )}

        {manualEntryAllowed && (
          <button
            type="button"
            onClick={onManualEntry}
            className="rounded-lg border border-pine-700/40 px-2.5 py-1 text-[11px] text-pine-300 transition-colors hover:border-mint/40 hover:text-mint"
          >
            + Manual entry
          </button>
        )}
      </div>

      {active === 'catalog' ? (
        // Composed, not forked. `onManualEntry` is deliberately NOT passed
        // down: this panel already owns the one permanent manual control, and
        // two of them is a second thing to explain, not a second chance.
        <CardSearchPanel onSelect={onPickCatalog} />
      ) : (
        <InventorySearch onPick={onPickInventory} customerView={customerView} />
      )}
    </div>
  )
}
