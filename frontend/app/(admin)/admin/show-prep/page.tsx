'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { MapPin, AlertTriangle, ArrowRight, Check, ExternalLink, Tag, TrendingUp, TrendingDown } from 'lucide-react'
import { useAdminApi, AdminApiError } from '@/lib/admin-api'
import { useCardImages } from '@/lib/use-card-images'
import { useLocations } from '@/lib/use-locations'
import { sortRows, type FieldExtractor } from '@/lib/client-table-sort'
import DataTable, { Column } from '@/components/admin/shared/DataTable'
import PriceDisplay from '@/components/admin/shared/PriceDisplay'
import CardImage, { TABLE_THUMB_SIZE, TABLE_THUMB_COLUMN } from '@/components/admin/shared/CardImage'
import ImageToggle from '@/components/admin/shared/ImageToggle'
import CardDetailModal from '@/components/admin/shared/CardDetailModal'
import { patchRow } from '@/lib/item-update'
import InlineEditCell from '@/components/admin/shared/InlineEditCell'
import MoneyInput from '@/components/admin/shared/MoneyInput'
import { parseMoney } from '@/lib/money'

interface MispricedItem {
  item_id: string
  card_id?: string
  name: string
  location?: string
  cost_basis: string
  current_market_value: string
  sticker_price?: string | null
  sticker_notes?: string | null
  tcg_url?: string | null
  delta_pct: string
  delta_dollar?: string
  [key: string]: unknown
}

interface LocationData {
  locations: Record<string, number>
  total: number
}

// Module scope, not inside the component: a fresh object per render would
// give `sortRows`'s `useMemo` below a new `fields` reference every time,
// which is harmless functionally but would defeat memoization entirely.
function numericField(field: keyof MispricedItem): FieldExtractor<MispricedItem> {
  return (item) => {
    const raw = item[field]
    if (raw === undefined || raw === null || raw === '') return null
    const parsed = parseFloat(String(raw))
    return Number.isNaN(parsed) ? null : parsed
  }
}

const MISPRICED_SORT_FIELDS: Record<string, FieldExtractor<MispricedItem>> = {
  delta_pct: numericField('delta_pct'),
  delta_dollar: numericField('delta_dollar'),
  current_market_value: numericField('current_market_value'),
  cost_basis: numericField('cost_basis'),
}

export default function AdminShowPrepPage() {
  const api = useAdminApi()
  const { options: locationOptions } = useLocations()

  // Per-row inline edits (sticker price, TCG link)
  const [savingItemId, setSavingItemId] = useState<string | null>(null)
  const [itemEditError, setItemEditError] = useState<string | null>(null)

  // Mispriced
  const [threshold, setThreshold] = useState(20)
  const [thresholdMode, setThresholdMode] = useState<'percent' | 'dollar'>('percent')
  const [mispriced, setMispriced] = useState<MispricedItem[]>([])
  const [loadingMispriced, setLoadingMispriced] = useState(true)

  // Locations
  const [locations, setLocations] = useState<LocationData | null>(null)

  // Bulk move
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [moveTarget, setMoveTarget] = useState('')
  const [moving, setMoving] = useState(false)
  const [moveResult, setMoveResult] = useState<string | null>(null)

  // Mass sticker update
  const [stickerValue, setStickerValue] = useState('')
  const [updatingStickers, setUpdatingStickers] = useState(false)

  // Image toggle and detail modal
  const [showImages, setShowImages] = useState(false)
  const [detailItem, setDetailItem] = useState<MispricedItem | null>(null)
  const cardIds = mispriced.map((i) => i.card_id)
  const { getImageUrl } = useCardImages(showImages ? cardIds : [])

  // Sort
  const [sortKey, setSortKey] = useState<string | null>(null)
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')

  const fetchMispriced = useCallback(async () => {
    if (!api.isAuthenticated) return
    setLoadingMispriced(true)
    try {
      const res = await api.get<{ items: MispricedItem[]; total_flagged: number }>('/show-prep/mispriced', { threshold, threshold_mode: thresholdMode })
      setMispriced(res.items)
    } catch { setMispriced([]) }
    finally { setLoadingMispriced(false) }
  }, [api, threshold, thresholdMode])

  const fetchLocations = useCallback(async () => {
    if (!api.isAuthenticated) return
    try {
      const res = await api.get<LocationData>('/show-prep/location-summary')
      setLocations(res)
    } catch { /* ignore */ }
  }, [api])

  useEffect(() => { fetchMispriced() }, [fetchMispriced])
  useEffect(() => { fetchLocations() }, [fetchLocations])

  const handleSelect = (id: string, checked: boolean) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (checked) next.add(id)
      else next.delete(id)
      return next
    })
  }

  const handleSelectAll = (checked: boolean) => {
    if (checked) setSelectedIds(new Set(mispriced.map((i) => i.item_id)))
    else setSelectedIds(new Set())
  }

  const handleBulkMove = async () => {
    if (selectedIds.size === 0 || !moveTarget.trim()) return
    setMoving(true)
    setMoveResult(null)
    try {
      const res = await api.post<{ moved: number; errors: unknown[] }>('/show-prep/bulk-move', {
        item_ids: Array.from(selectedIds),
        new_location: moveTarget.trim(),
      })
      setMoveResult(`Moved ${res.moved} item${res.moved !== 1 ? 's' : ''} to "${moveTarget.trim()}"`)
      setSelectedIds(new Set())
      setMoveTarget('')
      fetchMispriced()
      fetchLocations()
    } catch (err) {
      setMoveResult(err instanceof AdminApiError ? (err.detail || 'Move failed') : 'Move failed')
    } finally {
      setMoving(false)
    }
  }

  const handleBulkStickerUpdate = async () => {
    if (selectedIds.size === 0 || !stickerValue.trim()) return
    setUpdatingStickers(true)
    setMoveResult(null)
    let updated = 0
    // parseMoney, not parseFloat: `parseFloat('1,300')` is 1 and never NaN, so
    // it slips past an isNaN guard as a plausible wrong number. A negative is
    // rejected by the parser itself, which is why `price < 0` is gone.
    const price = parseMoney(stickerValue)
    if (price === null) { setUpdatingStickers(false); return }

    for (const id of selectedIds) {
      try {
        // The PARSED value, not the raw text the admin typed (RFC 0010 T1).
        await api.put(`/inventory/${id}`, { sticker_price: String(price) })
        updated++
      } catch { /* continue on error */ }
    }
    setMoveResult(`Updated sticker price to $${price.toFixed(2)} on ${updated} item${updated !== 1 ? 's' : ''}`)
    setStickerValue('')
    setSelectedIds(new Set())
    setUpdatingStickers(false)
    fetchMispriced()
  }

  // Row-level inline edit save/error path. InlineEditCell keeps the editor
  // open on rejection, so these handlers throw on both validation and API
  // failure — the thrown error reaches the column's onError, which surfaces
  // it in `itemEditError` (see banner in the JSX below).
  const saveItemStickerPrice = async (itemId: string, rawValue: string) => {
    const trimmed = rawValue.trim()
    setSavingItemId(itemId)
    try {
      if (trimmed === '') {
        await api.put(`/inventory/${itemId}`, { sticker_price: null })
      } else {
        // InlineEditCell type="money" has already parsed this, so `trimmed` is
        // a clean numeric string by the time it arrives. Re-checking is cheap
        // and keeps the handler correct if it is ever called from elsewhere.
        const price = parseMoney(trimmed)
        if (price === null) {
          throw new Error('Enter a valid, non-negative sticker price')
        }
        // Send the parsed number, not the raw typed string.
        await api.put(`/inventory/${itemId}`, { sticker_price: String(price) })
      }
      setItemEditError(null)
      fetchMispriced()
    } catch (err) {
      throw err instanceof AdminApiError ? err : err instanceof Error ? err : new Error('Failed to save sticker price')
    } finally {
      setSavingItemId(null)
    }
  }

  const saveItemTcgUrl = async (itemId: string, rawValue: string) => {
    const trimmed = rawValue.trim()
    setSavingItemId(itemId)
    try {
      await api.put(`/inventory/${itemId}`, { tcg_url: trimmed || null })
      setItemEditError(null)
      fetchMispriced()
    } catch (err) {
      throw err instanceof AdminApiError ? err : new Error('Failed to save TCG link')
    } finally {
      setSavingItemId(null)
    }
  }

  const handleItemEditError = (err: unknown) => {
    setItemEditError(err instanceof AdminApiError ? (err.detail || 'Save failed') : err instanceof Error ? err.message : 'Save failed')
  }

  const handleSort = (key: string) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir('desc')
    }
  }

  // Client-side sort — deliberately, not a RFC 0013 T4c regression. This
  // list is `/show-prep/mispriced`, which (like `/vault`) returns its FULL
  // match set with no `limit`/pagination, so there is no page-boundary for a
  // server sort to protect the way there is on Inventory/Prep Queue (where a
  // `limit` truncates BEFORE sort and a client-side sort would silently sort
  // the wrong, already-cut page). Client vs. server produces an IDENTICAL
  // result here, so this stays client-side rather than inventing a new
  // backend sort registry for a bespoke, computed response shape
  // (`delta_pct`/`delta_dollar`) that is not one of the RFC's five named
  // tables (`services/table_sort.py`'s docstring). See CLAUDE.md/RFC 0013
  // sync-docs notes for this deviation, mirroring the Locations `item_count`
  // one.
  //
  // Missing-last in BOTH directions, same invariant every backend registry
  // enforces (`services/table_sort.py`) and `lib/vault-sort.ts` already
  // matches — the previous version here used `|| 0`, which sorted an absent
  // value into the middle of the range instead of to the end. Routed through
  // the shared `sortRows` helper (`lib/client-table-sort.ts`) rather than a
  // fourth hand-rolled copy of the same partition.
  const sortedMispriced = useMemo(
    () => sortRows(mispriced, MISPRICED_SORT_FIELDS, sortKey, sortDir),
    [mispriced, sortKey, sortDir],
  )

  const columns: Column<MispricedItem>[] = [
    ...(showImages
      ? [
          {
            key: '_image',
            label: '',
            className: TABLE_THUMB_COLUMN,
            render: (item: MispricedItem) => (
              <CardImage
                imageUrl={getImageUrl(item.card_id)}
                alt={item.name || 'card'}
                size={TABLE_THUMB_SIZE}
              />
            ),
          },
        ]
      : []),
    {
      key: 'name',
      label: 'Name',
      className: 'min-w-[160px]',
      render: (item) => <span className="text-pine-100 text-xs font-medium truncate block max-w-[200px]">{item.name || '(unnamed)'}</span>,
    },
    {
      key: 'location',
      label: 'Location',
      render: (item) => <span className="text-xs text-pine-300 capitalize">{item.location || '—'}</span>,
    },
    {
      key: 'cost_basis',
      label: 'Price Paid',
      sortable: true,
      className: 'text-right',
      render: (item) => <PriceDisplay value={item.cost_basis} className="text-xs text-pine-300" />,
    },
    {
      key: 'current_market_value',
      label: 'Market',
      sortable: true,
      className: 'text-right',
      render: (item) => <PriceDisplay value={item.current_market_value} className="text-xs text-mint" />,
    },
    {
      key: 'sticker_price',
      label: 'Sticker',
      className: 'text-right w-28',
      render: (item) => (
        <InlineEditCell
          value={item.sticker_price ? String(item.sticker_price) : ''}
          type="money"
          prefix="$"
          placeholder="0.00"
          saving={savingItemId === item.item_id}
          aria-label={`Edit sticker price for ${item.name || 'item'}`}
          onSave={(v) => saveItemStickerPrice(item.item_id, v)}
          onError={handleItemEditError}
          displayValue={
            <div className="flex items-center justify-end gap-1">
              {item.sticker_price ? <PriceDisplay value={item.sticker_price} className="text-xs text-amber-400" /> : <span className="text-xs text-pine-600">—</span>}
              {item.sticker_notes && (
                <span className="text-[9px] text-pine-500 italic truncate max-w-[60px]" title={item.sticker_notes}>
                  ({item.sticker_notes})
                </span>
              )}
            </div>
          }
        />
      ),
    },
    {
      key: 'delta_pct',
      label: 'Delta',
      sortable: true,
      className: 'text-right',
      render: (item) => {
        const pctVal = parseFloat(item.delta_pct)
        const dollarVal = item.delta_dollar ? parseFloat(item.delta_dollar) : null
        const color = pctVal > 0 ? 'text-mint' : 'text-red-400'
        if (thresholdMode === 'dollar' && dollarVal !== null) {
          return <span className={`text-xs font-mono ${color}`}>{dollarVal > 0 ? '+' : ''}${dollarVal.toFixed(2)} ({pctVal > 0 ? '+' : ''}{pctVal.toFixed(1)}%)</span>
        }
        return <span className={`text-xs font-mono ${color}`}>{pctVal > 0 ? '+' : ''}{pctVal.toFixed(1)}%{dollarVal !== null ? ` ($${dollarVal > 0 ? '+' : ''}${dollarVal.toFixed(2)})` : ''}</span>
      },
    },
    {
      key: '_tcg_url',
      label: 'TCG Price',
      className: 'w-32',
      render: (item) => {
        // Fall back to a generated TCGplayer search URL when no link is stored.
        const searchQuery = encodeURIComponent(item.name || '')
        const tcgSearchUrl = `https://www.tcgplayer.com/search/pokemon/product?q=${searchQuery}&view=grid`
        const linkHref = item.tcg_url || tcgSearchUrl

        return (
          <InlineEditCell
            value={item.tcg_url ?? ''}
            type="url"
            placeholder="https://tcgplayer.com/…"
            saving={savingItemId === item.item_id}
            aria-label={`Edit stored TCG link for ${item.name || 'item'}`}
            onSave={(v) => saveItemTcgUrl(item.item_id, v)}
            onError={handleItemEditError}
            displayValue={
              <a
                href={linkHref}
                target="_blank"
                rel="noopener noreferrer"
                onClick={(e) => e.stopPropagation()}
                className="inline-flex items-center gap-1 text-[10px] text-blue-400 hover:text-blue-300 transition-colors"
                title={item.tcg_url ? item.tcg_url : `Search TCGplayer for "${item.name}"`}
              >
                <ExternalLink size={11} />
                Check Price
              </a>
            }
          />
        )
      },
    },
  ]

  return (
    <div className="p-6 lg:p-8">
      <header className="mb-6">
        <span className="font-mono text-[11px] uppercase tracking-[0.22em] text-mint/70">Show Prep</span>
        <h1 className="text-xl font-semibold text-pine-100">Prepare for Shows</h1>
      </header>

      {/* Location summary */}
      {locations && (
        <section className="vault-panel rounded-xl p-4 mb-6">
          <div className="flex items-center gap-2 mb-3">
            <MapPin size={15} className="text-mint" />
            <h2 className="text-xs font-semibold text-pine-200 uppercase tracking-wider">Locations ({locations.total} items)</h2>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2">
            {Object.entries(locations.locations)
              .sort(([, a], [, b]) => b - a)
              .map(([loc, count]) => (
                <div key={loc} className="flex items-center justify-between px-3 py-2 rounded-lg bg-pine-800/50 border border-pine-700/30">
                  <span className="text-xs text-pine-300 capitalize truncate">{loc}</span>
                  <span className="text-xs font-mono text-mint ml-2">{count}</span>
                </div>
              ))}
          </div>
        </section>
      )}

      {/* Mispriced cards */}
      <section className="space-y-4">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div className="flex items-center gap-2">
            <AlertTriangle size={15} className="text-amber-400" />
            <h2 className="text-xs font-semibold text-pine-200 uppercase tracking-wider">
              Mispriced Cards
            </h2>
          </div>
          <div className="flex items-center gap-3 flex-wrap">
            {/* Image toggle — moved to top */}
            <ImageToggle showImages={showImages} onToggle={() => setShowImages(!showImages)} label="Images" />

            {/* Mode toggle */}
            <div className="flex rounded-lg border border-pine-700/40 overflow-hidden">
              <button
                type="button"
                onClick={() => { setThresholdMode('percent'); setThreshold(20) }}
                className={`px-2.5 py-1 text-[10px] font-medium transition-colors ${thresholdMode === 'percent' ? 'bg-mint/15 text-mint' : 'text-pine-400 hover:text-pine-200'}`}
              >
                %
              </button>
              <button
                type="button"
                onClick={() => { setThresholdMode('dollar'); setThreshold(5) }}
                className={`px-2.5 py-1 text-[10px] font-medium border-l border-pine-700/40 transition-colors ${thresholdMode === 'dollar' ? 'bg-mint/15 text-mint' : 'text-pine-400 hover:text-pine-200'}`}
              >
                $
              </button>
            </div>
            {/* Slider */}
            <label className="text-[10px] text-pine-400">Threshold:</label>
            <input
              type="range"
              min={thresholdMode === 'percent' ? 5 : 1}
              max={thresholdMode === 'percent' ? 80 : 50}
              value={threshold}
              onChange={(e) => setThreshold(Number(e.target.value))}
              className="w-24 accent-mint"
            />
            {/* Manual input */}
            <div className="relative">
              <input
                type="number"
                min={1}
                value={threshold}
                onChange={(e) => setThreshold(Number(e.target.value) || 1)}
                className="vault-field w-16 px-2 py-0.5 rounded text-xs text-right font-mono pr-5"
              />
              <span className="absolute right-1.5 top-1/2 -translate-y-1/2 text-[10px] text-pine-500">
                {thresholdMode === 'percent' ? '%' : '$'}
              </span>
            </div>
          </div>
        </div>

        {/* Trend sort buttons */}
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-pine-400 font-medium">Sort by trend:</span>
          <button
            type="button"
            onClick={() => { setSortKey('delta_pct'); setSortDir('desc') }}
            className={`inline-flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium transition-colors ${sortKey === 'delta_pct' && sortDir === 'desc' ? 'bg-mint/15 text-mint border border-mint/30' : 'text-pine-400 hover:text-pine-200 border border-pine-700/40'}`}
          >
            <TrendingUp size={11} />
            Gainers
          </button>
          <button
            type="button"
            onClick={() => { setSortKey('delta_pct'); setSortDir('asc') }}
            className={`inline-flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium transition-colors ${sortKey === 'delta_pct' && sortDir === 'asc' ? 'bg-red-500/15 text-red-400 border border-red-500/30' : 'text-pine-400 hover:text-pine-200 border border-pine-700/40'}`}
          >
            <TrendingDown size={11} />
            Losers
          </button>
          <button
            type="button"
            onClick={() => { setSortKey('current_market_value'); setSortDir('desc') }}
            className={`inline-flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium transition-colors ${sortKey === 'current_market_value' ? 'bg-mint/15 text-mint border border-mint/30' : 'text-pine-400 hover:text-pine-200 border border-pine-700/40'}`}
          >
            Highest Value
          </button>
          {sortKey && (
            <button
              type="button"
              onClick={() => setSortKey(null)}
              className="text-[10px] text-pine-500 hover:text-pine-300 transition-colors"
            >
              Clear
            </button>
          )}
        </div>

        {/* Bulk actions bar */}
        {selectedIds.size > 0 && (
          <div className="vault-panel rounded-lg px-4 py-2.5 flex items-center gap-3 flex-wrap">
            <span className="text-xs text-pine-200">
              <span className="font-mono text-mint">{selectedIds.size}</span> selected
            </span>

            {/* Bulk move */}
            <ArrowRight size={14} className="text-pine-500" />
            <select
              value={moveTarget}
              onChange={(e) => setMoveTarget(e.target.value)}
              className="vault-field px-2.5 py-1 rounded-lg text-xs max-w-48"
            >
              <option value="">Move to…</option>
              {locationOptions.map((loc) => (
                <option key={loc.value} value={loc.value}>
                  {loc.label}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={handleBulkMove}
              disabled={!moveTarget.trim() || moving}
              className="px-3 py-1.5 rounded-lg text-[11px] font-medium bg-mint/15 text-mint border border-mint/30 hover:bg-mint/25 disabled:opacity-40 transition-colors"
            >
              {moving ? 'Moving…' : 'Move'}
            </button>

            {/* Bulk sticker update */}
            <div className="border-l border-pine-700/40 pl-3 flex items-center gap-2">
              <Tag size={13} className="text-amber-400" />
              <div className="relative flex flex-col">
                <span className="absolute left-1.5 top-2 -translate-y-1/2 text-[10px] text-pine-500">$</span>
                <MoneyInput
                  label="Bulk sticker price"
                  value={stickerValue}
                  onChange={(raw) => setStickerValue(raw)}
                  placeholder="0.00"
                  className="vault-field w-20 pl-4 pr-1.5 py-1 rounded-lg text-xs font-mono"
                />
              </div>
              <button
                type="button"
                onClick={handleBulkStickerUpdate}
                disabled={!stickerValue.trim() || updatingStickers}
                className="px-3 py-1.5 rounded-lg text-[11px] font-medium bg-amber-500/15 text-amber-400 border border-amber-500/30 hover:bg-amber-500/25 disabled:opacity-40 transition-colors"
              >
                {updatingStickers ? 'Updating…' : 'Set Sticker'}
              </button>
            </div>
          </div>
        )}

        {moveResult && (
          <div className="flex items-center gap-2 text-xs text-mint bg-mint/5 border border-mint/20 rounded-lg px-3 py-2">
            <Check size={14} />
            {moveResult}
          </div>
        )}

        {itemEditError && (
          <div className="flex items-center gap-2 text-xs text-red-400 bg-red-500/5 border border-red-500/20 rounded-lg px-3 py-2">
            <AlertTriangle size={14} />
            {itemEditError}
            <button
              type="button"
              onClick={() => setItemEditError(null)}
              className="ml-auto text-red-500/70 hover:text-red-400"
              aria-label="Dismiss error"
            >
              ×
            </button>
          </div>
        )}

        <DataTable
          columns={columns}
          data={sortedMispriced}
          keyField="item_id"
          loading={loadingMispriced}
          emptyMessage="No mispriced items found at this threshold"
          selectedIds={selectedIds}
          onSelect={handleSelect}
          onSelectAll={handleSelectAll}
          onRowClick={(item) => setDetailItem(item)}
          sortKey={sortKey}
          sortDir={sortDir}
          onSort={handleSort}
        />
      </section>

      <CardDetailModal
        item={detailItem as Record<string, unknown> | null}
        onClose={() => setDetailItem(null)}
        // Patch, do not refetch (RFC 0010 T5). The bulk-move selection is a Set
        // of ids, not of copies, so there is no staged duplicate to keep in
        // step — patching the list is the whole job here.
        onUpdated={(updated) => {
          if (!updated) { fetchMispriced(); return }
          setMispriced((rows) => patchRow(rows, updated))
        }}
      />
    </div>
  )
}
