'use client'

import { useRef, useState } from 'react'
import { Search } from 'lucide-react'
import CardGrid from './CardGrid'
import {
  searchInventory,
  type InventorySearchResult,
  type InventoryFilters,
} from '@/lib/inventory'

type Status = 'idle' | 'loading' | 'success' | 'error'

// Curated sets, mapped to their pokemontcg.io ids — the backend filters by
// set_id. A wrong id here silently returns "no cards", so ids are pinned by
// the FilterPanel tests.
const SETS: Array<{ label: string; id: string }> = [
  { label: 'Base', id: 'base1' },
  { label: 'Jungle', id: 'base2' },
  { label: 'Fossil', id: 'base3' },
  { label: 'Team Rocket', id: 'base5' },
  { label: 'Neo Genesis', id: 'neo1' },
  { label: 'Expedition', id: 'ecard1' },
  { label: 'Ruby & Sapphire', id: 'ex1' },
  { label: 'Diamond & Pearl', id: 'dp1' },
  { label: 'Black & White', id: 'bw1' },
  { label: 'Evolutions', id: 'xy12' },
  { label: 'Sword & Shield', id: 'swsh1' },
  { label: 'Brilliant Stars', id: 'swsh9' },
  { label: 'Scarlet & Violet', id: 'sv1' },
  { label: '151', id: 'sv3pt5' },
]
const SET_IDS = new Map(SETS.map((s) => [s.label, s.id]))

const RARITIES = [
  'Common',
  'Uncommon',
  'Rare',
  'Rare Holo',
  'Rare Holo EX',
  'Rare Holo GX',
  'Rare Holo V',
  'Rare Holo VMAX',
  'Rare Ultra',
  'Rare Secret',
  'Rare Rainbow',
  'Promo',
]

// Raw-card grades the backend accepts. Filtering by condition intentionally
// excludes graded slabs (backend behavior) — hence the label note.
const CONDITIONS: Array<{ value: string; label: string }> = [
  { value: 'NM', label: 'NM — Near Mint' },
  { value: 'LP', label: 'LP — Lightly Played' },
  { value: 'MP', label: 'MP — Moderately Played' },
  { value: 'HP', label: 'HP — Heavily Played' },
  { value: 'DMG', label: 'DMG — Damaged' },
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

export default function FilterPanel() {
  const [filters, setFilters] = useState<InventoryFilters>({})
  // The select shows the display label; the query sends the mapped set_id.
  const [setLabel, setSetLabel] = useState('')
  const [status, setStatus] = useState<Status>('idle')
  const [result, setResult] = useState<InventorySearchResult | null>(null)
  // Monotonic id so a slow earlier request can't overwrite a newer one.
  const requestId = useRef(0)

  function update<K extends keyof InventoryFilters>(key: K, value: string) {
    setFilters((prev) => ({ ...prev, [key]: value }))
  }

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault()
    const id = ++requestId.current
    setStatus('loading')
    try {
      const res = await searchInventory(normalizePriceRange(filters))
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
            <select
              id="flt-set"
              value={setLabel}
              onChange={(e) => {
                setSetLabel(e.target.value)
                update('set_id', SET_IDS.get(e.target.value) ?? '')
              }}
              className={fieldClass}
            >
              <option value="">Any set</option>
              {SETS.map((s) => (
                <option key={s.id} value={s.label}>
                  {s.label}
                </option>
              ))}
            </select>
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
              {RARITIES.map((r) => (
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
              {CONDITIONS.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
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
      <p className="py-10 text-center text-sm text-pine-300">
        No cards found. Try widening your filters.
      </p>
    )
  }
  return (
    <div className="space-y-4">
      <p className="font-mono text-xs uppercase tracking-[0.12em] text-pine-300">
        {result.total} result{result.total === 1 ? '' : 's'}
      </p>
      <CardGrid items={result.items} />
    </div>
  )
}
