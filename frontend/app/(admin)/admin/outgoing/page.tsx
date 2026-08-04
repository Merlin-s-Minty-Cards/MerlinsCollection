'use client'

import { useCallback, useEffect, useState } from 'react'
import {
  Package,
  Truck,
  Check,
  Filter,
  Pencil,
  X,
} from 'lucide-react'
import { useAdminApi, AdminApiError } from '@/lib/admin-api'
import { useCardImages } from '@/lib/use-card-images'
import { LOCATION_OPTIONS } from '@/lib/constants'
import DataTable, { Column } from '@/components/admin/shared/DataTable'
import PriceDisplay from '@/components/admin/shared/PriceDisplay'
import CardImage from '@/components/admin/shared/CardImage'
import ImageToggle from '@/components/admin/shared/ImageToggle'
import StatusBadge from '@/components/admin/shared/StatusBadge'
import CardDetailModal from '@/components/admin/shared/CardDetailModal'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface OutgoingItem {
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
  counterparty?: string | null
  buyer_name?: string | null
  set_name?: string | null
  condition?: string | null
  [key: string]: unknown
}

type OutgoingFilter = 'all' | 'sold' | 'shipped' | 'completed'

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export default function AdminOutgoingPage() {
  const api = useAdminApi()

  // Data state
  const [items, setItems] = useState<OutgoingItem[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<OutgoingFilter>('all')

  // Inline editing
  const [editingPrice, setEditingPrice] = useState<string | null>(null)
  const [editPriceValue, setEditPriceValue] = useState('')
  const [editingLocation, setEditingLocation] = useState<string | null>(null)
  const [editLocationValue, setEditLocationValue] = useState('')
  const [saving, setSaving] = useState(false)

  // Images
  const [showImages, setShowImages] = useState(false)
  const cardIds = items.map((i) => i.card_id)
  const { getImageUrl } = useCardImages(showImages ? cardIds : [])

  // Detail modal
  const [detailItem, setDetailItem] = useState<OutgoingItem | null>(null)

  // Toast message
  const [message, setMessage] = useState<string | null>(null)

  // ---------------------------------------------------------------------------
  // Data fetching
  // ---------------------------------------------------------------------------

  const fetchItems = useCallback(async () => {
    if (!api.isAuthenticated) return
    setLoading(true)
    try {
      // Fetch sold items — the outgoing queue
      const params: Record<string, string> = { status: 'sold' }
      const res = await api.get<{ items: OutgoingItem[] }>('/inventory/search', params)
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
  // Filtering
  // ---------------------------------------------------------------------------

  const filteredItems = items.filter((item) => {
    if (filter === 'all') return true
    if (filter === 'sold') return item.status === 'sold' && item.location !== 'sold_pile'
    if (filter === 'shipped') return item.location === 'sold_pile'
    if (filter === 'completed') return item.status === 'completed'
    return true
  })

  // ---------------------------------------------------------------------------
  // Inline sticker price editing
  // ---------------------------------------------------------------------------

  const startPriceEdit = (itemId: string, currentPrice: string | null | undefined) => {
    setEditingPrice(itemId)
    setEditPriceValue(currentPrice ?? '')
  }

  const cancelPriceEdit = () => {
    setEditingPrice(null)
    setEditPriceValue('')
  }

  const savePriceEdit = async (itemId: string) => {
    setSaving(true)
    try {
      const price = editPriceValue.trim() === '' ? null : editPriceValue.trim()
      await api.put(`/inventory/${itemId}`, { sticker_price: price })
      setEditingPrice(null)
      setEditPriceValue('')
      setMessage('Sticker price updated')
      fetchItems()
    } catch (err) {
      setMessage(err instanceof AdminApiError ? (err.detail ?? 'Update failed') : 'Update failed')
    } finally {
      setSaving(false)
    }
  }

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
  // Completion workflow
  // ---------------------------------------------------------------------------

  const markAsShipped = async (itemId: string) => {
    setSaving(true)
    try {
      await api.put(`/inventory/${itemId}`, { location: 'sold_pile' })
      setMessage('Marked as shipped')
      fetchItems()
    } catch (err) {
      setMessage(err instanceof AdminApiError ? (err.detail ?? 'Failed') : 'Failed')
    } finally {
      setSaving(false)
    }
  }

  const markAsCompleted = async (itemId: string) => {
    setSaving(true)
    try {
      await api.put(`/inventory/${itemId}`, { status: 'completed' })
      setMessage('Marked as completed')
      fetchItems()
    } catch (err) {
      setMessage(err instanceof AdminApiError ? (err.detail ?? 'Failed') : 'Failed')
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

  const getItemName = (item: OutgoingItem): string => {
    return item.display_name || item.product_name || item.name || '(unnamed)'
  }

  // ---------------------------------------------------------------------------
  // Table columns
  // ---------------------------------------------------------------------------

  const columns: Column<OutgoingItem>[] = [
    ...(showImages
      ? [
          {
            key: '_image',
            label: '',
            className: 'w-12',
            render: (item: OutgoingItem) => (
              <CardImage
                imageUrl={getImageUrl(item.card_id)}
                alt={getItemName(item)}
                size="sm"
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
      render: (item) => {
        if (editingPrice === item.item_id) {
          return (
            <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
              <div className="relative">
                <span className="absolute left-1.5 top-1/2 -translate-y-1/2 text-[10px] text-pine-500">$</span>
                <input
                  type="number"
                  step="0.01"
                  value={editPriceValue}
                  onChange={(e) => setEditPriceValue(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') savePriceEdit(item.item_id)
                    if (e.key === 'Escape') cancelPriceEdit()
                  }}
                  onBlur={() => savePriceEdit(item.item_id)}
                  className="vault-field w-20 pl-4 pr-1.5 py-0.5 rounded text-xs font-mono"
                  autoFocus
                  disabled={saving}
                />
              </div>
              <button
                type="button"
                onClick={() => cancelPriceEdit()}
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
            className="flex items-center gap-1 group/price cursor-pointer"
            onClick={(e) => {
              e.stopPropagation()
              startPriceEdit(item.item_id, item.sticker_price)
            }}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === 'Enter') startPriceEdit(item.item_id, item.sticker_price)
            }}
            aria-label={`Edit sticker price for ${getItemName(item)}`}
          >
            {item.sticker_price ? (
              <PriceDisplay value={item.sticker_price} className="text-xs text-amber-400" />
            ) : (
              <span className="text-xs text-pine-600">—</span>
            )}
            <Pencil size={10} className="text-pine-600 opacity-0 group-hover/price:opacity-100 transition-opacity" />
          </div>
        )
      },
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
                <option value="">— None —</option>
                {LOCATION_OPTIONS.map((loc) => (
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
      key: 'counterparty',
      label: 'Buyer',
      className: 'w-28',
      render: (item) => (
        <span className="text-xs text-pine-300 truncate block max-w-[100px]">
          {item.buyer_name || item.counterparty || '—'}
        </span>
      ),
    },
    {
      key: 'status',
      label: 'Status',
      className: 'w-24',
      render: (item) => <StatusBadge status={item.status} />,
    },
    {
      key: '_actions',
      label: '',
      className: 'w-28',
      render: (item) => (
        <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
          {item.location !== 'sold_pile' && item.status !== 'completed' && (
            <button
              type="button"
              onClick={() => markAsShipped(item.item_id)}
              disabled={saving}
              className="inline-flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium text-blue-400 bg-blue-400/10 border border-blue-400/20 hover:bg-blue-400/20 disabled:opacity-40 transition-colors"
              title="Mark as shipped"
            >
              <Truck size={11} />
              Ship
            </button>
          )}
          {item.location === 'sold_pile' && item.status !== 'completed' && (
            <button
              type="button"
              onClick={() => markAsCompleted(item.item_id)}
              disabled={saving}
              className="inline-flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium text-mint bg-mint/10 border border-mint/20 hover:bg-mint/20 disabled:opacity-40 transition-colors"
              title="Mark as completed"
            >
              <Check size={11} />
              Done
            </button>
          )}
          {item.status === 'completed' && (
            <span className="text-[10px] text-pine-500 italic">Completed</span>
          )}
        </div>
      ),
    },
  ]

  // ---------------------------------------------------------------------------
  // Summary stats
  // ---------------------------------------------------------------------------

  const totalItems = items.length
  const pendingCount = items.filter((i) => i.status === 'sold' && i.location !== 'sold_pile').length
  const shippedCount = items.filter((i) => i.location === 'sold_pile' && i.status !== 'completed').length
  const completedCount = items.filter((i) => i.status === 'completed').length

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="p-6 lg:p-8 max-w-7xl">
      <header className="mb-6">
        <span className="font-mono text-[11px] uppercase tracking-[0.22em] text-mint/70">
          Outgoing
        </span>
        <h1 className="text-xl font-semibold text-pine-100">Outgoing Inventory Queue</h1>
        <p className="text-xs text-pine-400 mt-1">
          Items sold and awaiting shipment or completion
        </p>
      </header>

      {/* Summary cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
        <div className="vault-panel rounded-xl px-4 py-3 border border-pine-700/30">
          <div className="text-[10px] text-pine-500 uppercase tracking-wider mb-1">Total</div>
          <div className="text-lg font-mono text-pine-100">{totalItems}</div>
        </div>
        <div className="vault-panel rounded-xl px-4 py-3 border border-pine-700/30">
          <div className="text-[10px] text-pine-500 uppercase tracking-wider mb-1">Pending</div>
          <div className="text-lg font-mono text-amber-400">{pendingCount}</div>
        </div>
        <div className="vault-panel rounded-xl px-4 py-3 border border-pine-700/30">
          <div className="text-[10px] text-pine-500 uppercase tracking-wider mb-1">Shipped</div>
          <div className="text-lg font-mono text-blue-400">{shippedCount}</div>
        </div>
        <div className="vault-panel rounded-xl px-4 py-3 border border-pine-700/30">
          <div className="text-[10px] text-pine-500 uppercase tracking-wider mb-1">Completed</div>
          <div className="text-lg font-mono text-mint">{completedCount}</div>
        </div>
      </div>

      {/* Filter bar */}
      <div className="flex items-center justify-between flex-wrap gap-3 mb-4">
        <div className="flex items-center gap-2">
          <Filter size={14} className="text-pine-400" />
          <div className="flex rounded-lg border border-pine-700/40 overflow-hidden">
            {(['all', 'sold', 'shipped', 'completed'] as OutgoingFilter[]).map((f) => (
              <button
                key={f}
                type="button"
                onClick={() => setFilter(f)}
                className={`px-3 py-1.5 text-[11px] font-medium capitalize transition-colors ${
                  filter === f
                    ? 'bg-mint/15 text-mint'
                    : 'text-pine-400 hover:text-pine-200'
                } ${f !== 'all' ? 'border-l border-pine-700/40' : ''}`}
              >
                {f === 'sold' ? 'Pending' : f}
              </button>
            ))}
          </div>
        </div>
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
        data={filteredItems}
        keyField="item_id"
        loading={loading}
        emptyMessage="No outgoing items found"
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
