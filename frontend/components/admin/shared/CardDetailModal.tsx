'use client'

import { useCallback, useEffect, useState } from 'react'
import { X, Pencil, Check, XCircle } from 'lucide-react'
import { useAdminApi, AdminApiError } from '@/lib/admin-api'
import PriceDisplay from './PriceDisplay'
import CardImage from './CardImage'
import PriceChart from './PriceChart'

interface CardDetailModalProps {
  /** The item to display — null means modal is closed */
  item: Record<string, unknown> | null
  /** Close handler */
  onClose: () => void
  /** Called after a successful edit so the parent can refresh data */
  onUpdated?: () => void
  /** Resolved image URL for the card (or null) */
  imageUrl?: string | null
}

/** Editable fields with their display labels and value types */
const EDITABLE_FIELDS: { key: string; label: string; type: 'text' | 'number' }[] = [
  { key: 'display_name', label: 'Display Name', type: 'text' },
  { key: 'product_name', label: 'Product Name', type: 'text' },
  { key: 'condition', label: 'Condition', type: 'text' },
  { key: 'location', label: 'Location', type: 'text' },
  { key: 'cost_basis', label: 'Cost Basis', type: 'number' },
  { key: 'current_market_value', label: 'Market Value', type: 'number' },
  { key: 'sticker_price', label: 'Sticker Price', type: 'number' },
  { key: 'listed_price', label: 'Listed Price', type: 'number' },
  { key: 'notes', label: 'Notes', type: 'text' },
  { key: 'status', label: 'Status', type: 'text' },
  { key: 'finish', label: 'Finish', type: 'text' },
  { key: 'language', label: 'Language', type: 'text' },
]

/**
 * Shared modal for viewing/editing inventory item details with price history chart.
 * Opens when clicking a card row in any admin page.
 */
export default function CardDetailModal({
  item,
  onClose,
  onUpdated,
  imageUrl,
}: CardDetailModalProps) {
  const api = useAdminApi()
  const [editingField, setEditingField] = useState<string | null>(null)
  const [editValue, setEditValue] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Reset editing state when item changes
  useEffect(() => {
    setEditingField(null)
    setEditValue('')
    setError(null)
  }, [item?.item_id])

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    if (item) {
      document.addEventListener('keydown', handler)
      return () => document.removeEventListener('keydown', handler)
    }
  }, [item, onClose])

  const startEdit = (field: string) => {
    setEditingField(field)
    setEditValue(String(item?.[field] ?? ''))
    setError(null)
  }

  const cancelEdit = () => {
    setEditingField(null)
    setEditValue('')
    setError(null)
  }

  const saveEdit = useCallback(async () => {
    if (!editingField || !item) return
    setSaving(true)
    setError(null)
    try {
      const value = editValue.trim() === '' ? null : editValue.trim()
      await api.put(`/inventory/${item.item_id}`, { [editingField]: value })
      setEditingField(null)
      setEditValue('')
      onUpdated?.()
    } catch (err) {
      setError(err instanceof AdminApiError ? (err.detail ?? 'Update failed') : 'Update failed')
    } finally {
      setSaving(false)
    }
  }, [api, editingField, editValue, item, onUpdated])

  if (!item) return null

  const itemId = String(item.item_id ?? '')
  const name = String(item.display_name ?? item.product_name ?? item.description ?? '(unnamed)')
  const kind = String(item.kind ?? '')

  // Filter to fields that exist on this item type
  const visibleFields = EDITABLE_FIELDS.filter((f) => {
    // Show product_name only for sealed, display_name for raw/graded
    if (f.key === 'product_name' && kind !== 'sealed') return false
    if (f.key === 'display_name' && kind === 'sealed') return false
    if (f.key === 'finish' && kind !== 'raw') return false
    return true
  })

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={`Details for ${name}`}
    >
      <div
        className="relative w-full max-w-2xl max-h-[90vh] overflow-y-auto vault-panel rounded-2xl border border-pine-700/50 shadow-2xl mx-4"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-pine-700/40 bg-pine-900/95 backdrop-blur px-5 py-4 rounded-t-2xl">
          <div className="flex items-center gap-3 min-w-0">
            <CardImage imageUrl={imageUrl} alt={name} size="sm" />
            <div className="min-w-0">
              <h2 className="text-base font-semibold text-pine-100 truncate">{name}</h2>
              <p className="text-[10px] text-pine-500 font-mono">{kind} &middot; {itemId}</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-md text-pine-400 hover:text-pine-200 hover:bg-pine-800 transition-colors"
            aria-label="Close modal"
          >
            <X size={18} />
          </button>
        </div>

        <div className="p-5 space-y-5">
          {/* Error banner */}
          {error && (
            <div className="text-xs text-red-400 bg-red-400/10 border border-red-400/20 rounded px-3 py-2">
              {error}
            </div>
          )}

          {/* Price Chart */}
          <section>
            <h3 className="text-[11px] font-semibold uppercase tracking-wider text-pine-400 mb-2">
              Price History
            </h3>
            <PriceChart
              itemId={itemId}
              costBasis={item.cost_basis as string | undefined}
              acquiredAt={item.acquired_at as string | undefined}
            />
          </section>

          {/* Editable Fields */}
          <section>
            <h3 className="text-[11px] font-semibold uppercase tracking-wider text-pine-400 mb-2">
              Item Details
            </h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {visibleFields.map((field) => {
                const value = item[field.key]
                const isEditing = editingField === field.key
                const displayValue = value != null ? String(value) : '—'

                return (
                  <div
                    key={field.key}
                    className="flex items-center gap-2 px-3 py-2 rounded-lg bg-pine-800/30 border border-pine-700/20"
                  >
                    <span className="text-[10px] text-pine-500 uppercase tracking-wider w-24 flex-shrink-0">
                      {field.label}
                    </span>
                    {isEditing ? (
                      <div className="flex items-center gap-1 flex-1 min-w-0">
                        <input
                          type={field.type}
                          value={editValue}
                          onChange={(e) => setEditValue(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') saveEdit()
                            if (e.key === 'Escape') cancelEdit()
                          }}
                          className="flex-1 min-w-0 bg-pine-900 border border-mint/30 rounded px-2 py-0.5 text-xs text-pine-100 focus:outline-none focus:border-mint/60"
                          autoFocus
                          disabled={saving}
                        />
                        <button
                          type="button"
                          onClick={saveEdit}
                          disabled={saving}
                          className="p-0.5 text-mint hover:text-mint/80"
                          aria-label="Save"
                        >
                          <Check size={13} />
                        </button>
                        <button
                          type="button"
                          onClick={cancelEdit}
                          className="p-0.5 text-pine-500 hover:text-pine-300"
                          aria-label="Cancel"
                        >
                          <XCircle size={13} />
                        </button>
                      </div>
                    ) : (
                      <div className="flex items-center gap-1 flex-1 min-w-0">
                        <span className="text-xs text-pine-200 truncate flex-1">
                          {field.type === 'number' && value != null ? (
                            <PriceDisplay value={displayValue} className="text-xs text-pine-200 font-mono" />
                          ) : (
                            displayValue
                          )}
                        </span>
                        <button
                          type="button"
                          onClick={() => startEdit(field.key)}
                          className="p-0.5 text-pine-600 hover:text-pine-300 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0"
                          style={{ opacity: 1 }}
                          aria-label={`Edit ${field.label}`}
                        >
                          <Pencil size={11} />
                        </button>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </section>

          {/* Quick Info */}
          <section className="flex flex-wrap gap-3 text-[10px] text-pine-500 border-t border-pine-700/30 pt-3">
            {item.card_id && (
              <span>Card: <span className="text-pine-300 font-mono">{String(item.card_id)}</span></span>
            )}
            {item.acquired_at && (
              <span>Acquired: <span className="text-pine-300">{String(item.acquired_at)}</span></span>
            )}
            {item.company && (
              <span>Grade: <span className="text-pine-300">{String(item.company)} {String(item.grade ?? '')}</span></span>
            )}
          </section>
        </div>
      </div>
    </div>
  )
}
