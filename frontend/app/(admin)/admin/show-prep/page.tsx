'use client'

import { useCallback, useEffect, useState } from 'react'
import { MapPin, AlertTriangle, ArrowRight, Check } from 'lucide-react'
import { useAdminApi, AdminApiError } from '@/lib/admin-api'
import DataTable, { Column } from '@/components/admin/shared/DataTable'
import PriceDisplay from '@/components/admin/shared/PriceDisplay'

interface MispricedItem {
  item_id: string
  card_id?: string
  name: string
  location?: string
  cost_basis: string
  current_market_value: string
  delta_pct: string
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
  const [mispriced, setMispriced] = useState<MispricedItem[]>([])
  const [loadingMispriced, setLoadingMispriced] = useState(true)

  // Locations
  const [locations, setLocations] = useState<LocationData | null>(null)

  // Bulk move
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [moveTarget, setMoveTarget] = useState('')
  const [moving, setMoving] = useState(false)
  const [moveResult, setMoveResult] = useState<string | null>(null)

  const fetchMispriced = useCallback(async () => {
    if (!api.isAuthenticated) return
    setLoadingMispriced(true)
    try {
      const res = await api.get<{ items: MispricedItem[]; total_flagged: number }>('/show-prep/mispriced', { threshold })
      setMispriced(res.items)
    } catch { setMispriced([]) }
    finally { setLoadingMispriced(false) }
  }, [api, threshold])

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

  const columns: Column<MispricedItem>[] = [
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
      label: 'Cost',
      className: 'text-right',
      render: (item) => <PriceDisplay value={item.cost_basis} className="text-xs text-pine-300" />,
    },
    {
      key: 'current_market_value',
      label: 'Market',
      className: 'text-right',
      render: (item) => <PriceDisplay value={item.current_market_value} className="text-xs text-mint" />,
    },
    {
      key: 'delta_pct',
      label: 'Delta',
      className: 'text-right',
      render: (item) => {
        const val = parseFloat(item.delta_pct)
        const color = val > 0 ? 'text-mint' : 'text-red-400'
        return <span className={`text-xs font-mono ${color}`}>{val > 0 ? '+' : ''}{val.toFixed(1)}%</span>
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
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <AlertTriangle size={15} className="text-amber-400" />
            <h2 className="text-xs font-semibold text-pine-200 uppercase tracking-wider">
              Mispriced Cards
            </h2>
          </div>
          <div className="flex items-center gap-2">
            <label className="text-[10px] text-pine-400">Threshold:</label>
            <input
              type="range"
              min={5}
              max={80}
              value={threshold}
              onChange={(e) => setThreshold(Number(e.target.value))}
              className="w-24 accent-mint"
            />
            <span className="text-xs font-mono text-pine-300 w-8">{threshold}%</span>
          </div>
        </div>

        {/* Bulk move bar */}
        {selectedIds.size > 0 && (
          <div className="vault-panel rounded-lg px-4 py-2.5 flex items-center gap-3">
            <span className="text-xs text-pine-200">
              <span className="font-mono text-mint">{selectedIds.size}</span> selected
            </span>
            <ArrowRight size={14} className="text-pine-500" />
            <input
              type="text"
              value={moveTarget}
              onChange={(e) => setMoveTarget(e.target.value)}
              placeholder="Move to location…"
              className="vault-field px-2.5 py-1 rounded-lg text-xs flex-1 max-w-48"
            />
            <button
              type="button"
              onClick={handleBulkMove}
              disabled={!moveTarget.trim() || moving}
              className="px-3 py-1.5 rounded-lg text-[11px] font-medium bg-mint/15 text-mint border border-mint/30 hover:bg-mint/25 disabled:opacity-40 transition-colors"
            >
              {moving ? 'Moving…' : 'Move'}
            </button>
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
          data={mispriced}
          keyField="item_id"
          loading={loadingMispriced}
          emptyMessage="No mispriced items found at this threshold"
          selectedIds={selectedIds}
          onSelect={handleSelect}
          onSelectAll={handleSelectAll}
        />
      </section>
    </div>
  )
}
