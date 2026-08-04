'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Check, Pencil, X } from 'lucide-react'
import { useAdminApi, AdminApiError } from '@/lib/admin-api'
import { useCardImages } from '@/lib/use-card-images'
import { useLocations } from '@/lib/use-locations'
import DataTable, { Column } from '@/components/admin/shared/DataTable'
import PriceDisplay from '@/components/admin/shared/PriceDisplay'
import CardImage from '@/components/admin/shared/CardImage'
import ImageToggle from '@/components/admin/shared/ImageToggle'
import InlineEditCell from '@/components/admin/shared/InlineEditCell'
import CardDetailModal from '@/components/admin/shared/CardDetailModal'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface PrepQueueItem {
  item_id: string
  card_id?: string
  name?: string
  display_name?: string
  product_name?: string
  status: string
  location?: string
  sticker_price?: string | null
  cost_basis?: string | null
  current_market_value?: string | null
  set_name?: string | null
  condition?: string | null
  [key: string]: unknown
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export default function AdminPrepQueuePage() {
  const api = useAdminApi()
  const { options: locationOptions } = useLocations()

  // Data state
  const [items, setItems] = useState<PrepQueueItem[]>([])
  const [loading, setLoading] = useState(true)

  // Inline location editing (select — not handled by InlineEditCell)
  const [editingLocation, setEditingLocation] = useState<string | null>(null)
  const [editLocationValue, setEditLocationValue] = useState('')
  const [saving, setSaving] = useState(false)

  // Images — default ON per spec
  const [showImages, setShowImages] = useState(true)
  const cardIds = items.map((i) => i.card_id)
  const { getImageUrl } = useCardImages(showImages ? cardIds : [])

  // Detail modal
  const [detailItem, setDetailItem] = useState<PrepQueueItem | null>(null)

  // Toast message
  const [message, setMessage] = useState<string | null>(null)

  // ---------------------------------------------------------------------------
  // Data fetching
  // ---------------------------------------------------------------------------

  const fetchItems = useCallback(async () => {
    if (!api.isAuthenticated) return
    setLoading(true)
    try {
      const params: Record<string, string> = {
        status: 'available',
        missing_sticker: 'true',
      }
      const res = await api.get<{ items: PrepQueueItem[] }>('/inventory/search', params)
      setItems(res.items ?? [])
    } catch {
      setItems([])
    } finally {
      setLoading(false)
    }
  }, [api])

  useEffect(() => {
    fetchItems()
  }, [fetchItems])

  // ---------------------------------------------------------------------------
  // Inline sticker price editing (via InlineEditCell)
  // ---------------------------------------------------------------------------

  const handleStickerSave = useCallback(
    async (itemId: string, newValue: string) => {
      const price = newValue.trim() === '' ? null : newValue.trim()
      await api.put(`/inventory/${itemId}`, { sticker_price: price })
      setMessage('Priced → removed from queue')
      fetchItems()
    },
    [api, fetchItems],
  )

  const handleStickerError = useCallback(
    (err: unknown) => {
      setMessage(
        err instanceof AdminApiError ? (err.detail ?? 'Update failed') : 'Update failed',
      )
    },
    [],
  )

  // ---------------------------------------------------------------------------
  // Inline location editing
  // ---------------------------------------------------------------------------

  const startLocationEdit = (itemId: string, currentLocation: string | undefined) => {
    setEditingLocation(itemId)
    setEditLocationValue(currentLocation ?? '')
  }

  const cancelLocationEdit = () => {
    setEditingLocation(null)
    setEditLocationValue('')
  }

  const saveLocationEdit = async (itemId: string) => {
    setSaving(true)
    try {
      const location = editLocationValue.trim() === '' ? null : editLocationValue.trim()
      await api.put(`/inventory/${itemId}`, { location })
      setEditingLocation(null)
      setEditLocationValue('')
      setMessage('Location updated')
      fetchItems()
    } catch (err) {
      setMessage(err instanceof AdminApiError ? (err.detail ?? 'Update failed') : 'Update failed')
    } finally {
      setSaving(false)
    }
  }

  // ---------------------------------------------------------------------------
  // Clear message on timeout
  // ---------------------------------------------------------------------------

  useEffect(() => {
    if (message) {
      const timer = setTimeout(() => setMessage(null), 3000)
      return () => clearTimeout(timer)
    }
  }, [message])

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------

  const getItemName = (item: PrepQueueItem): string => {
    return item.display_name || item.product_name || item.name || '(unnamed)'
  }

  // ---------------------------------------------------------------------------
  // Table columns
  // ---------------------------------------------------------------------------

  const columns: Column<PrepQueueItem>[] = [
    ...(showImages
      ? [
          {
            key: '_image',
            label: '',
            className: 'w-24',
            render: (item: PrepQueueItem) => (
              <CardImage
                imageUrl={getImageUrl(item.card_id)}
                alt={getItemName(item)}
                size="lg"
              />
            ),
          },
        ]
      : []),
    {
      key: 'name',
      label: 'Card',
      className: 'min-w-[160px]',
      render: (item) => (
        <div className="space-y-0.5">
          <span className="text-pine-100 text-xs font-medium truncate block max-w-[200px]">
            {getItemName(item)}
          </span>
          {item.set_name && (
            <span className="text-[10px] text-pine-500 truncate block max-w-[200px]">
              {item.set_name}
            </span>
          )}
        </div>
      ),
    },
    {
      key: 'condition',
      label: 'Cond',
      className: 'w-16',
      render: (item) => (
        <span className="text-[11px] text-pine-300 font-mono">{item.condition || '—'}</span>
      ),
    },
    {
      key: 'sticker_price',
      label: 'Sticker',
      className: 'w-28',
      render: (item) => (
        <InlineEditCell
          value={item.sticker_price ?? ''}
          type="number"
          prefix="$"
          placeholder="0.00"
          aria-label={`Edit sticker price for ${getItemName(item)}`}
          displayValue={
            item.sticker_price ? (
              <PriceDisplay value={item.sticker_price} className="text-xs text-amber-400" />
            ) : (
              <span className="text-xs text-pine-600">—</span>
            )
          }
          onSave={(v) => handleStickerSave(item.item_id, v)}
          onError={handleStickerError}
        />
      ),
    },
    {
      key: 'location',
      label: 'Location',
      className: 'w-36',
      render: (item) => {
        if (editingLocation === item.item_id) {
          return (
            <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
              <select
                value={editLocationValue}
                onChange={(e) => setEditLocationValue(e.target.value)}
                onBlur={() => saveLocationEdit(item.item_id)}
                onKeyDown={(e) => {
                  if (e.key === 'Escape') cancelLocationEdit()
                }}
                className="vault-field px-2 py-0.5 rounded text-xs max-w-28"
                autoFocus
                disabled={saving}
              >
                {locationOptions.map((loc) => (
                  <option key={loc.value} value={loc.value}>
                    {loc.label}
                  </option>
                ))}
              </select>
              <button
                type="button"
                onClick={() => cancelLocationEdit()}
                className="p-0.5 text-pine-500 hover:text-pine-300"
                aria-label="Cancel"
              >
                <X size={12} />
              </button>
            </div>
          )
        }
        return (
          <div
            className="flex items-center gap-1 group/loc cursor-pointer"
            onClick={(e) => {
              e.stopPropagation()
              startLocationEdit(item.item_id, item.location)
            }}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === 'Enter') startLocationEdit(item.item_id, item.location)
            }}
            aria-label={`Edit location for ${getItemName(item)}`}
          >
            <span className="text-xs text-pine-300 capitalize">{item.location || '—'}</span>
            <Pencil size={10} className="text-pine-600 opacity-0 group-hover/loc:opacity-100 transition-opacity" />
          </div>
        )
      },
    },
    {
      key: 'cost_basis',
      label: 'Cost',
      className: 'text-right w-20',
      render: (item) => <PriceDisplay value={item.cost_basis} className="text-xs text-pine-400" />,
    },
    {
      key: 'current_market_value',
      label: 'Market',
      className: 'text-right w-20',
      render: (item) => <PriceDisplay value={item.current_market_value} className="text-xs text-pine-400" />,
    },
  ]

  // ---------------------------------------------------------------------------
  // Summary stats
  // ---------------------------------------------------------------------------

  const queueCount = items.length

  const estValue = useMemo(() => {
    return items.reduce((sum, item) => {
      const raw = item.current_market_value ?? item.cost_basis
      if (raw == null) return sum
      const n = typeof raw === 'string' ? parseFloat(raw) : raw
      return sum + (isNaN(n) ? 0 : n)
    }, 0)
  }, [items])

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="p-6 lg:p-8 max-w-7xl">
      <header className="mb-6">
        <span className="font-mono text-[11px] uppercase tracking-[0.22em] text-mint/70">
          Prep Queue
        </span>
        <h1 className="text-xl font-semibold text-pine-100">Prep Queue</h1>
        <p className="text-xs text-pine-400 mt-1">
          New inventory awaiting sticker prices
        </p>
      </header>

      {/* Summary cards */}
      <div className="grid grid-cols-2 gap-3 mb-6">
        <div className="vault-panel rounded-xl px-4 py-3 border border-pine-700/30">
          <div className="text-[10px] text-pine-500 uppercase tracking-wider mb-1">In queue</div>
          <div className="text-lg font-mono text-pine-100">{queueCount}</div>
        </div>
        <div className="vault-panel rounded-xl px-4 py-3 border border-pine-700/30">
          <div className="text-[10px] text-pine-500 uppercase tracking-wider mb-1">Est. value</div>
          <div className="text-lg font-mono text-amber-400">
            ${estValue.toFixed(2)}
          </div>
        </div>
      </div>

      {/* Image toggle */}
      <div className="flex items-center justify-end mb-4">
        <ImageToggle showImages={showImages} onToggle={() => setShowImages(!showImages)} label="Images" />
      </div>

      {/* Toast message */}
      {message && (
        <div className="flex items-center gap-2 text-xs text-mint bg-mint/5 border border-mint/20 rounded-lg px-3 py-2 mb-4">
          <Check size={14} />
          {message}
        </div>
      )}

      {/* Data table */}
      <DataTable
        columns={columns}
        data={items}
        keyField="item_id"
        loading={loading}
        emptyMessage="No items awaiting sticker prices"
        onRowClick={(item) => setDetailItem(item)}
      />

      {/* Detail modal */}
      <CardDetailModal
        item={detailItem as Record<string, unknown> | null}
        onClose={() => setDetailItem(null)}
        onUpdated={fetchItems}
        imageUrl={detailItem?.card_id ? getImageUrl(detailItem.card_id) : null}
      />
    </div>
  )
}
