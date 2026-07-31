'use client'

import { useEffect, useRef, useState } from 'react'
import { useSession } from 'next-auth/react'
import { Search } from 'lucide-react'
import CardGrid from './CardGrid'
import {
  searchInventory,
  getInventoryFacets,
  type InventorySearchResult,
  type InventoryFilters,
  type InventoryFacets,
  type FacetSet,
} from '@/lib/inventory'

type Status = 'idle' | 'loading' | 'success' | 'error'

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

export default function FilterPanel() {
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
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <div className="sm:col-span-2 lg:col-span-3">
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

      <div aria-live="polite">
        <Results status={status} result={result} />
      </div>
    </div>
  )
}

// ---- Set Combobox (type-to-narrow) ----

function SetCombobox({
  sets,
  value,
  onChange,
}: {
  sets: FacetSet[]
  value: string
  onChange: (id: string) => void
}) {
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const wrapperRef = useRef<HTMLDivElement>(null)

  // Resolve the current value to a display name.
  const selected = sets.find((s) => s.id === value)

  const filtered = query
    ? sets.filter((s) => s.name.toLowerCase().includes(query.toLowerCase()))
    : sets

  // Close on outside click.
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  return (
    <div ref={wrapperRef} className="relative">
      <input
        id="flt-set"
        type="text"
        role="combobox"
        aria-expanded={open}
        aria-autocomplete="list"
        aria-controls="set-listbox"
        value={open ? query : selected?.name ?? ''}
        placeholder="Any set"
        className={fieldClass}
        onFocus={() => {
          setOpen(true)
          setQuery('')
        }}
        onChange={(e) => {
          setQuery(e.target.value)
          setOpen(true)
          if (e.target.value === '') {
            onChange('')
          }
        }}
        onKeyDown={(e) => {
          if (e.key === 'Escape') {
            setOpen(false)
          }
        }}
      />
      {open && filtered.length > 0 && (
        <ul
          id="set-listbox"
          role="listbox"
          className="absolute z-50 mt-1 max-h-60 w-full overflow-auto rounded-lg vault-panel border border-pine-700 py-1"
        >
          <li
            role="option"
            aria-selected={value === ''}
            className="cursor-pointer px-3 py-2 text-sm hover:bg-pine-700/40"
            onMouseDown={(e) => {
              e.preventDefault()
              onChange('')
              setOpen(false)
            }}
          >
            Any set
          </li>
          {filtered.map((s) => (
            <li
              key={s.id}
              role="option"
              aria-selected={value === s.id}
              className="cursor-pointer px-3 py-2 text-sm hover:bg-pine-700/40"
              onMouseDown={(e) => {
                e.preventDefault()
                onChange(s.id)
                setOpen(false)
              }}
            >
              {s.name}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// ---- Results display ----

function Results({
  status,
  result,
}: {
  status: Status
  result: InventorySearchResult | null
}) {
  if (status === 'idle') {
    return (
      <p className="py-10 text-center text-sm text-pine-300">
        Set your filters and run a search to browse the collection.
      </p>
    )
  }
  if (status === 'loading') {
    return (
      <p className="py-10 text-center font-mono text-sm text-mint">Searching the vault…</p>
    )
  }
  if (status === 'error') {
    return (
      <p className="py-10 text-center text-sm text-red-300">
        Something went wrong. Check your connection and try again.
      </p>
    )
  }
  if (!result || result.items.length === 0) {
    return (
      <div className="space-y-2 py-10 text-center">
        <p className="text-sm text-pine-300">No cards found. Try widening your filters.</p>
        <HiddenNoPriceNotice count={result?.hidden_no_price} />
      </div>
    )
  }
  return (
    <div className="space-y-4">
      <div className="space-y-1">
        <p className="font-mono text-xs uppercase tracking-[0.12em] text-pine-300">
          {result.total} result{result.total === 1 ? '' : 's'}
        </p>
        <HiddenNoPriceNotice count={result.hidden_no_price} />
      </div>
      <CardGrid items={result.items} />
    </div>
  )
}

/**
 * Tells the customer that the price range dropped cards we hold but have no
 * price for, rather than letting them vanish from the grid unexplained (the
 * owner's "the price filter wipes the inventory" bug report). Renders nothing
 * when the backend hid none — or when an older backend omits the field.
 */
function HiddenNoPriceNotice({ count }: { count?: number }) {
  if (!count) return null
  return (
    <p className="font-mono text-xs uppercase tracking-[0.12em] text-pine-300">
      {count} card{count === 1 ? '' : 's'} hidden (no price on file)
    </p>
  )
}
