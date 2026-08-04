'use client'

import { useCallback, useEffect, useState } from 'react'
import { MapPin, AlertTriangle, ArrowRight, Check, ExternalLink, Tag, TrendingUp, TrendingDown } from 'lucide-react'
import { useAdminApi, AdminApiError } from '@/lib/admin-api'
import { useCardImages } from '@/lib/use-card-images'
import { LOCATION_OPTIONS } from '@/lib/constants'
import DataTable, { Column } from '@/components/admin/shared/DataTable'
import PriceDisplay from '@/components/admin/shared/PriceDisplay'
import CardImage from '@/components/admin/shared/CardImage'
import ImageToggle from '@/components/admin/shared/ImageToggle'
import CardDetailModal from '@/components/admin/shared/CardDetailModal'

interface MispricedItem {
  item_id: string
  card_id?: string
  name: string
  location?: string
  cost_basis: string
  current_market_value: string
  sticker_price?: string | null
  sticker_notes?: string | null
  delta_pct: string
  delta_dollar?: string
  [key: string]: unknown
}

interface LocationData {
  locations: Record<string, number>
  total: number
}

export default function AdminShowPrepPage() {
  const api = useAdminApi()

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
    const price = parseFloat(stickerValue)
    if (isNaN(price) || price < 0) { setUpdatingStickers(false); return }

    for (const id of selectedIds) {
      try {
        await api.put(`/inventory/${id}`, { sticker_price: stickerValue })
        updated++
      } catch { /* continue on error */ }
    }
    setMoveResult(`Updated sticker price to $${price.toFixed(2)} on ${updated} item${updated !== 1 ? 's' : ''}`)
    setStickerValue('')
    setSelectedIds(new Set())
    setUpdatingStickers(false)
    fetchMispriced()
  }

  const handleSort = (key: string) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir('desc')
    }
  }

  // Apply local sort
  const sortedMispriced = [...mispriced].sort((a, b) => {
    if (!sortKey) return 0
    if (sortKey === 'delta_pct') {
      const aVal = parseFloat(a.delta_pct) || 0
      const bVal = parseFloat(b.delta_pct) || 0
      return sortDir === 'asc' ? aVal - bVal : bVal - aVal
    }
    if (sortKey === 'delta_dollar') {
      const aVal = a.delta_dollar ? parseFloat(a.delta_dollar) : 0
      const bVal = b.delta_dollar ? parseFloat(b.delta_dollar) : 0
      return sortDir === 'asc' ? aVal - bVal : bVal - aVal
    }
    if (sortKey === 'current_market_value') {
      const aVal = parseFloat(a.current_market_value) || 0
      const bVal = parseFloat(b.current_market_value) || 0
      return sortDir === 'asc' ? aVal - bVal : bVal - aVal
    }
    if (sortKey === 'cost_basis') {
      const aVal = parseFloat(a.cost_basis) || 0
      const bVal = parseFloat(b.cost_basis) || 0
      return sortDir === 'asc' ? aVal - bVal : bVal - aVal
    }
    return 0
  })

  const columns: Column<MispricedItem>[] = [
    ...(showImages
      ? [
          {
            key: '_image',
            label: '',
            className: 'w-12',
            render: (item: MispricedItem) => (
              <CardImage
                imageUrl={getImageUrl(item.card_id)}
                alt={item.name || 'card'}
                size="sm"
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
      className: 'text-right',
      render: (item) => (
        <div className="flex items-center justify-end gap-1">
          {item.sticker_price ? <PriceDisplay value={item.sticker_price} className="text-xs text-amber-400" /> : <span className="text-xs text-pine-600">—</span>}
          {item.sticker_notes && (
            <span className="text-[9px] text-pine-500 italic truncate max-w-[60px]" title={item.sticker_notes}>
              ({item.sticker_notes})
            </span>
          )}
        </div>
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
      className: 'w-28',
      render: (item) => {
        // Build a TCGplayer search URL from the card name
        const searchQuery = encodeURIComponent(item.name || '')
        const tcgSearchUrl = `https://www.tcgplayer.com/search/pokemon/product?q=${searchQuery}&view=grid`

        return (
          <a
            href={tcgSearchUrl}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="inline-flex items-center gap-1 text-[10px] text-blue-400 hover:text-blue-300 transition-colors"
            title={`Search TCGplayer for "${item.name}"`}
          >
            <ExternalLink size={11} />
            Check Price
          </a>
        )
      },
    },
  ]

  return (
    <div className="p-6 lg:p-8 max-w-6xl">
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
              {LOCATION_OPTIONS.map((loc) => (
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
              <div className="relative">
                <span className="absolute left-1.5 top-1/2 -translate-y-1/2 text-[10px] text-pine-500">$</span>
                <input
                  type="number"
                  step="0.01"
                  value={stickerValue}
                  onChange={(e) => setStickerValue(e.target.value)}
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
        onUpdated={fetchMispriced}
        imageUrl={detailItem?.card_id ? getImageUrl(detailItem.card_id) : null}
      />
    </div>
  )
}
