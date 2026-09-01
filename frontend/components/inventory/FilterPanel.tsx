'use client'

import { useEffect, useRef, useState } from 'react'
import { useSession } from 'next-auth/react'
import { Search } from 'lucide-react'
import type { ResultsView } from './ResultsPane'
import SetCombobox from '@/components/shared/SetCombobox'
import {
  searchInventory,
  getInventoryFacets,
  toPresentedCard,
  type InventorySearchResult,
  type InventoryFilters,
  type InventoryFacets,
} from '@/lib/inventory'

type Status = 'idle' | 'loading' | 'success' | 'error'

const SORT_OPTIONS = [
  { value: 'newest', label: 'Newest first' },
  { value: 'oldest', label: 'Oldest first' },
  { value: 'price_desc', label: 'Price: high to low' },
  { value: 'price_asc', label: 'Price: low to high' },
  { value: 'name_asc', label: 'Name: A–Z' },
  { value: 'name_desc', label: 'Name: Z–A' },
]

// Guard against an inverted price range reaching the API — swap if min > max
// (the backend rejects an inverted range with 422).
function normalizePriceRange(filters: InventoryFilters): InventoryFilters {
  const out: InventoryFilters = { ...filters }
  const min = parseFloat(out.min_price ?? '')
  const max = parseFloat(out.max_price ?? '')
  if (!Number.isNaN(min) && !Number.isNaN(max) && min > max) {
    out.min_price = String(max)
    out.max_price = String(min)
  }
  return out
}

const fieldClass = 'vault-field w-full rounded-lg px-3 py-2.5 text-sm'
const labelClass =
  'mb-1.5 block font-mono text-[11px] uppercase tracking-[0.12em] text-pine-300'

export interface FilterPanelProps {
  /**
   * RFC 0019: FilterPanel no longer renders its own results grid — filter and
   * chat mode share one ResultsPane in the split workspace's right column.
   * This fires whenever the search status or result changes, carrying a
   * normalized view for that shared pane.
   */
  onResultsChange?: (view: ResultsView) => void
}

const IDLE_MESSAGE = 'Set your filters and run a search to browse the collection.'
const NO_RESULTS_MESSAGE = 'No cards found. Try widening your filters.'
const ERROR_MESSAGE = 'Something went wrong. Check your connection and try again.'

function hiddenNoPriceNotice(count: number | undefined): string | undefined {
  if (!count) return undefined
  return `${count} card${count === 1 ? '' : 's'} hidden (no price on file)`
}

export default function FilterPanel({ onResultsChange }: FilterPanelProps = {}) {
  const { data: session } = useSession()
  const [filters, setFilters] = useState<InventoryFilters>({})
  const [status, setStatus] = useState<Status>('idle')
  const [result, setResult] = useState<InventorySearchResult | null>(null)
  const [facets, setFacets] = useState<InventoryFacets | null>(null)
  // Monotonic id so a slow earlier request can't overwrite a newer one.
  const requestId = useRef(0)

  // Load facets once on mount (requires auth token).
  useEffect(() => {
    if (!session?.accessToken) return
    getInventoryFacets({ token: session.accessToken })
      .then(setFacets)
      .catch(() => {}) // Facets load failure is non-fatal; dropdowns stay empty.
  }, [session?.accessToken])

  // Push a normalized view to the shared ResultsPane whenever the search
  // status or result changes — this is the ONLY place FilterPanel's results
  // reach the DOM now; the panel itself never renders a card grid.
  useEffect(() => {
    if (status === 'idle') {
      onResultsChange?.({ headerLabel: '', cards: [], status: 'idle', emptyMessage: IDLE_MESSAGE })
      return
    }
    if (status === 'loading') {
      onResultsChange?.({ headerLabel: '', cards: [], status: 'loading', emptyMessage: '' })
      return
    }
    if (status === 'error') {
      onResultsChange?.({ headerLabel: '', cards: [], status: 'error', emptyMessage: ERROR_MESSAGE })
      return
    }
    // success
    const total = result?.total ?? 0
    onResultsChange?.({
      headerLabel: `${total} result${total === 1 ? '' : 's'}`,
      cards: (result?.items ?? []).map(toPresentedCard),
      status: 'success',
      emptyMessage: NO_RESULTS_MESSAGE,
      truncatedNotice: hiddenNoPriceNotice(result?.hidden_no_price),
    })
    // onResultsChange is intentionally omitted: it's expected to be a stable
    // callback (or the caller's own useCallback), and including it would
    // refire this effect on every parent render even when nothing changed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, result])

  function update<K extends keyof InventoryFilters>(key: K, value: string) {
    setFilters((prev) => ({ ...prev, [key]: value }))
  }

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault()
    const id = ++requestId.current
    setStatus('loading')
    try {
      const res = await searchInventory(normalizePriceRange(filters), {
        token: session?.accessToken,
      })
      if (id !== requestId.current) return
      setResult(res)
      setStatus('success')
    } catch {
      if (id !== requestId.current) return
      setStatus('error')
    }
  }

  return (
    <div className="space-y-6">
      <form
        onSubmit={onSubmit}
        className="rounded-2xl vault-panel p-4 sm:p-5"
        aria-label="Filter the inventory"
      >
        {/* auto-fit, NOT sm:/lg: breakpoints. Tailwind's breakpoints are
            VIEWPORT-scoped, and RFC-0019 moved this panel into a 320-720px
            resizable pane — so on a 1440px window `lg:grid-cols-3` gave three
            ~120px columns inside a 420px pane and every select clipped its own
            text ("Any condit", "All languag", "Newest firs", measured live
            2026-08-27). auto-fit tracks the pane, which is the thing that
            actually varies here. */}
        <div className="grid grid-cols-[repeat(auto-fit,minmax(9.5rem,1fr))] gap-4">
          <div className="col-span-full">
            <label htmlFor="flt-name" className={labelClass}>
              Card name
            </label>
            <input
              id="flt-name"
              type="text"
              value={filters.name ?? ''}
              onChange={(e) => update('name', e.target.value)}
              placeholder="e.g. Charizard"
              className={fieldClass}
            />
          </div>

          <div>
            <label htmlFor="flt-set" className={labelClass}>
              Set
            </label>
            <SetCombobox
              sets={facets?.sets ?? []}
              value={filters.set_id ?? ''}
              onChange={(id) => update('set_id', id)}
              inputId="flt-set"
              className={fieldClass}
            />
          </div>

          <div>
            <label htmlFor="flt-rarity" className={labelClass}>
              Rarity
            </label>
            <select
              id="flt-rarity"
              value={filters.rarity ?? ''}
              onChange={(e) => update('rarity', e.target.value)}
              className={fieldClass}
            >
              <option value="">Any rarity</option>
              {(facets?.rarities ?? []).map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="flt-condition" className={labelClass}>
              Condition (raw cards)
            </label>
            <select
              id="flt-condition"
              value={filters.condition ?? ''}
              onChange={(e) => update('condition', e.target.value)}
              className={fieldClass}
            >
              <option value="">Any condition</option>
              {(facets?.conditions ?? []).map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="flt-language" className={labelClass}>
              Language
            </label>
            <select
              id="flt-language"
              value={filters.language ?? ''}
              onChange={(e) => update('language', e.target.value)}
              className={fieldClass}
            >
              <option value="">All languages</option>
              {(facets?.languages ?? []).map((l) => (
                <option key={l} value={l}>
                  {l}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="flt-sort" className={labelClass}>
              Sort by
            </label>
            <select
              id="flt-sort"
              value={filters.sort ?? 'newest'}
              onChange={(e) => update('sort', e.target.value)}
              className={fieldClass}
            >
              {SORT_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="flt-min" className={labelClass}>
              Min price ($)
            </label>
            <input
              id="flt-min"
              type="number"
              min={0}
              value={filters.min_price ?? ''}
              onChange={(e) => update('min_price', e.target.value)}
              placeholder="0"
              className={fieldClass}
            />
          </div>

          <div>
            <label htmlFor="flt-max" className={labelClass}>
              Max price ($)
            </label>
            <input
              id="flt-max"
              type="number"
              min={0}
              value={filters.max_price ?? ''}
              onChange={(e) => update('max_price', e.target.value)}
              placeholder="Any"
              className={fieldClass}
            />
          </div>

          <div className="flex items-end">
            <button
              type="submit"
              aria-busy={status === 'loading'}
              className="flex w-full items-center justify-center gap-2 rounded-lg bg-mint px-5 py-2.5 text-sm font-semibold text-pine-950 transition-colors hover:bg-mint-soft"
            >
              <Search size={16} aria-hidden />
              {status === 'loading' ? 'Searching…' : 'Search'}
            </button>
          </div>
        </div>
      </form>
    </div>
  )
}
