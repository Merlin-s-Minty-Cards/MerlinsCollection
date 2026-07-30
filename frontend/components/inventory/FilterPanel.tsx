'use client'

import { useRef, useState } from 'react'
import { useSession } from 'next-auth/react'
import { Search } from 'lucide-react'
import CardGrid from './CardGrid'
import {
  searchInventory,
  type InventorySearchResult,
  type InventoryFilters,
} from '@/lib/inventory'

type Status = 'idle' | 'loading' | 'success' | 'error'

// Curated sets, mapped to their TCGdex composite set ids — the backend filters
// by set_id, looking the value up verbatim via repo.list_cards_by_set. A
// catalog row's set_id is build_card_id(language, tcgdex_set_id), so the id is
// LANGUAGE-PREFIXED ("en:base1"); a bare pokemontcg.io id matches zero rows and
// the dropdown silently returns "no cards". Two ids also differ from the old
// pokemontcg.io spelling (sv1 → sv01, sv3pt5 → sv03.5). Verified against a live
// scan of the DynamoDB catalog table (matched on exact set_name) and pinned by
// the FilterPanel tests.
const SETS: Array<{ label: string; id: string }> = [
  { label: 'Base', id: 'en:base1' },
  { label: 'Jungle', id: 'en:base2' },
  { label: 'Fossil', id: 'en:base3' },
  { label: 'Team Rocket', id: 'en:base5' },
  { label: 'Neo Genesis', id: 'en:neo1' },
  { label: 'Expedition', id: 'en:ecard1' },
  { label: 'Ruby & Sapphire', id: 'en:ex1' },
  { label: 'Diamond & Pearl', id: 'en:dp1' },
  { label: 'Black & White', id: 'en:bw1' },
  { label: 'Evolutions', id: 'en:xy12' },
  { label: 'Sword & Shield', id: 'en:swsh1' },
  { label: 'Brilliant Stars', id: 'en:swsh9' },
  { label: 'Scarlet & Violet', id: 'en:sv01' },
  { label: '151', id: 'en:sv03.5' },
]
const SET_IDS = new Map(SETS.map((s) => [s.label, s.id]))

// NOTE: this filter is a no-op in production today — every catalog card still
// has rarity: null. The Tier-2 depth pass (refresh_held_prices, RFC 0003 §7)
// that populates rarity has landed and is wired into the daily job (Phase 9),
// but has not yet been run against live data; this starts matching once it has.
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

// Print language. The empty value ("All languages") sends no param; the backend
// treats a JP print as a distinct, differently-priced card (Language enum EN/JP).
const LANGUAGES: Array<{ value: string; label: string }> = [
  { value: '', label: 'All languages' },
  { value: 'EN', label: 'English' },
  { value: 'JP', label: 'Japanese' },
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
  const { data: session } = useSession()
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
            <label htmlFor="flt-language" className={labelClass}>
              Language
            </label>
            <select
              id="flt-language"
              value={filters.language ?? ''}
              onChange={(e) => update('language', e.target.value)}
              className={fieldClass}
            >
              {LANGUAGES.map((l) => (
                <option key={l.value} value={l.value}>
                  {l.label}
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
