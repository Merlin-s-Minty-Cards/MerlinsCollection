'use client'

import { useCallback, useEffect, useState } from 'react'
import { Plus, Trash2, Pencil } from 'lucide-react'
import { useAdminApi, AdminApiError } from '@/lib/admin-api'
import { useCardImages } from '@/lib/use-card-images'
import DataTable, { Column } from '@/components/admin/shared/DataTable'
import SearchInput from '@/components/admin/shared/SearchInput'
import StatusBadge from '@/components/admin/shared/StatusBadge'
import PriceDisplay from '@/components/admin/shared/PriceDisplay'
import ConfirmDialog from '@/components/admin/shared/ConfirmDialog'
import CardImage from '@/components/admin/shared/CardImage'
import ImageToggle from '@/components/admin/shared/ImageToggle'
import CardDetailModal from '@/components/admin/shared/CardDetailModal'

interface InventoryItem {
  item_id: string
  kind: string
  status: string
  card_id?: string
  display_name?: string
  product_name?: string
  condition?: string
  location?: string
  cost_basis?: string
  current_market_value?: string
  sticker_price?: string
  finish?: string
  language?: string
  notes?: string
  acquired_at?: string
  [key: string]: unknown
}

const STATUS_OPTIONS = ['', 'available', 'sold', 'lost', 'on_hold', 'consigned']
const CONDITION_OPTIONS = ['', 'M', 'NM', 'LP', 'MP', 'HP', 'D']
const KIND_OPTIONS = ['', 'raw', 'graded', 'sealed', 'bulk']

export default function AdminInventoryPage() {
  const api = useAdminApi()
  const [items, setItems] = useState<InventoryItem[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [conditionFilter, setConditionFilter] = useState('')
  const [kindFilter, setKindFilter] = useState('')
  const [locationFilter, setLocationFilter] = useState('')
  const [sortKey, setSortKey] = useState<string | null>(null)
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')

  // Editing
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editField, setEditField] = useState<string | null>(null)
  const [editValue, setEditValue] = useState('')

  // Delete dialog
  const [deleteTarget, setDeleteTarget] = useState<InventoryItem | null>(null)
  const [deleting, setDeleting] = useState(false)

  // Create form
  const [showCreate, setShowCreate] = useState(false)

  // Image toggle
  const [showImages, setShowImages] = useState(false)

  // Detail modal
  const [detailItem, setDetailItem] = useState<InventoryItem | null>(null)

  // Resolve card images
  const cardIds = items.map((i) => i.card_id as string | undefined)
  const { getImageUrl } = useCardImages(showImages ? cardIds : [])

  const fetchItems = useCallback(async () => {
    if (!api.isAuthenticated) return
    setLoading(true)
    try {
      const params: Record<string, string> = {}
      if (search) params.name = search
      if (statusFilter) params.status = statusFilter
      if (conditionFilter) params.condition = conditionFilter
      if (kindFilter) params.kind = kindFilter
      if (locationFilter) params.location = locationFilter
      if (sortKey) params.sort = `${sortKey}_${sortDir}`

      const res = await api.get<{ items: InventoryItem[]; total: number }>('/inventory/search', params)
      setItems(res.items)
      setTotal(res.total)
    } catch {
      // handle silently
    } finally {
      setLoading(false)
    }
  }, [api, search, statusFilter, conditionFilter, kindFilter, locationFilter, sortKey, sortDir])

  useEffect(() => {
    fetchItems()
  }, [fetchItems])

  const handleSort = (key: string) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir('desc')
    }
  }

  const startEdit = (item: InventoryItem, field: string) => {
    setEditingId(item.item_id)
    setEditField(field)
    setEditValue(String((item as Record<string, unknown>)[field] ?? ''))
  }

  const saveEdit = async () => {
    if (!editingId || !editField) return
    try {
      await api.put(`/inventory/${editingId}`, { [editField]: editValue || null })
      setEditingId(null)
      setEditField(null)
      fetchItems()
    } catch (err) {
      if (err instanceof AdminApiError) alert(err.detail || err.message)
    }
  }

  const handleDelete = async () => {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await api.del(`/inventory/${deleteTarget.item_id}`)
      setDeleteTarget(null)
      fetchItems()
    } catch (err) {
      if (err instanceof AdminApiError) alert(err.detail || err.message)
    } finally {
      setDeleting(false)
    }
  }

  const columns: Column<InventoryItem>[] = [
    // Image column (conditionally shown)
    ...(showImages
      ? [
          {
            key: '_image',
            label: '',
            className: 'w-12',
            render: (item: InventoryItem) => (
              <CardImage
                imageUrl={getImageUrl(item.card_id)}
                alt={item.display_name || item.product_name || 'card'}
                size="sm"
              />
            ),
          },
        ]
      : []),
    {
      key: 'display_name',
      label: 'Name',
      sortable: true,
      className: 'min-w-[180px]',
      render: (item) => (
        <span className="text-pine-100 font-medium truncate block max-w-[260px]">
          {item.display_name || item.product_name || '(unnamed)'}
        </span>
      ),
    },
    {
      key: 'status',
      label: 'Status',
      sortable: true,
      render: (item) => <StatusBadge status={item.status} />,
    },
    {
      key: 'kind',
      label: 'Kind',
      render: (item) => (
        <span className="text-xs capitalize text-pine-300">{item.kind}</span>
      ),
    },
    {
      key: 'condition',
      label: 'Cond',
      render: (item) => (
        <span className="text-xs font-mono text-pine-300">{item.condition ?? '—'}</span>
      ),
    },
    {
      key: 'location',
      label: 'Location',
      sortable: true,
      render: (item) => {
        if (editingId === item.item_id && editField === 'location') {
          return (
            <input
              type="text"
              value={editValue}
              onChange={(e) => setEditValue(e.target.value)}
              onBlur={saveEdit}
              onKeyDown={(e) => { if (e.key === 'Enter') saveEdit(); if (e.key === 'Escape') { setEditingId(null); setEditField(null); } }}
              className="vault-field px-1.5 py-0.5 text-xs w-24 rounded"
              autoFocus
            />
          )
        }
        return (
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); startEdit(item, 'location') }}
            className="text-xs text-pine-300 hover:text-mint cursor-pointer flex items-center gap-1 group"
            title="Click to edit"
          >
            <span className="capitalize">{item.location ?? '—'}</span>
            <Pencil size={10} className="opacity-0 group-hover:opacity-100" />
          </button>
        )
      },
    },
    {
      key: 'cost_basis',
      label: 'Cost',
      sortable: true,
      className: 'text-right',
      render: (item) => (
        <PriceDisplay value={item.cost_basis} className="text-xs text-pine-300" />
      ),
    },
    {
      key: 'current_market_value',
      label: 'Market',
      sortable: true,
      className: 'text-right',
      render: (item) => (
        <PriceDisplay value={item.current_market_value} className="text-xs text-mint" />
      ),
    },
    {
      key: 'sticker_price',
      label: 'Sticker',
      className: 'text-right',
      render: (item) => {
        const sticker = item.sticker_price as string | undefined
        if (editingId === item.item_id && editField === 'sticker_price') {
          return (
            <input
              type="number"
              step="0.01"
              value={editValue}
              onChange={(e) => setEditValue(e.target.value)}
              onBlur={saveEdit}
              onKeyDown={(e) => { if (e.key === 'Enter') saveEdit(); if (e.key === 'Escape') { setEditingId(null); setEditField(null); } }}
              className="vault-field px-1.5 py-0.5 text-xs w-20 rounded text-right"
              autoFocus
            />
          )
        }
        return (
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); startEdit(item, 'sticker_price') }}
            className="text-xs text-amber-400/80 hover:text-amber-300 cursor-pointer flex items-center gap-1 group justify-end w-full"
            title="Click to edit sticker price"
          >
            <span className="font-mono">{sticker ? `$${parseFloat(sticker).toFixed(2)}` : '—'}</span>
            <Pencil size={10} className="opacity-0 group-hover:opacity-100" />
          </button>
        )
      },
    },
    {
      key: '_actions',
      label: '',
      className: 'w-20',
      render: (item) => (
        <div className="flex items-center gap-1 justify-end">
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); setDeleteTarget(item) }}
            className="p-1.5 rounded text-pine-500 hover:text-red-400 hover:bg-red-500/10 transition-colors"
            title="Delete"
          >
            <Trash2 size={14} />
          </button>
        </div>
      ),
    },
  ]

  return (
    <div className="p-6 lg:p-8 max-w-7xl">
      {/* Header */}
      <header className="flex items-center justify-between mb-6">
        <div>
          <span className="font-mono text-[11px] uppercase tracking-[0.22em] text-mint/70">
            Inventory
          </span>
          <h1 className="text-xl font-semibold text-pine-100">
            All Items
            <span className="ml-2 text-sm font-normal text-pine-400">({total})</span>
          </h1>
        </div>
        <button
          type="button"
          onClick={() => setShowCreate(true)}
          className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-xs font-medium bg-mint/15 text-mint border border-mint/30 hover:bg-mint/25 transition-colors"
        >
          <Plus size={14} />
          Add Item
        </button>
      </header>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2 mb-4">
        <SearchInput
          value={search}
          onChange={setSearch}
          placeholder="Search by name…"
          className="w-56"
        />
        <FilterSelect value={statusFilter} onChange={setStatusFilter} options={STATUS_OPTIONS} placeholder="Status" />
        <FilterSelect value={conditionFilter} onChange={setConditionFilter} options={CONDITION_OPTIONS} placeholder="Condition" />
        <FilterSelect value={kindFilter} onChange={setKindFilter} options={KIND_OPTIONS} placeholder="Kind" />
        <input
          type="text"
          value={locationFilter}
          onChange={(e) => setLocationFilter(e.target.value)}
          placeholder="Location"
          className="vault-field px-2.5 py-1.5 rounded-lg text-xs w-28"
        />
        <div className="ml-auto">
          <ImageToggle showImages={showImages} onToggle={() => setShowImages(!showImages)} label="Images" />
        </div>
      </div>

      {/* Table */}
      <DataTable
        columns={columns}
        data={items}
        keyField="item_id"
        sortKey={sortKey}
        sortDir={sortDir}
        onSort={handleSort}
        onRowClick={(item) => setDetailItem(item)}
        loading={loading}
        emptyMessage="No inventory items match your filters"
      />

      {/* Delete confirmation */}
      <ConfirmDialog
        open={!!deleteTarget}
        title="Delete Item"
        description={`Are you sure you want to delete "${deleteTarget?.display_name || deleteTarget?.product_name || 'this item'}"? This will soft-delete (mark as lost).`}
        confirmLabel="Delete"
        variant="danger"
        loading={deleting}
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
      />

      {/* Create form modal */}
      {showCreate && (
        <CreateItemModal
          onClose={() => setShowCreate(false)}
          onCreated={() => { setShowCreate(false); fetchItems() }}
        />
      )}

      {/* Detail modal */}
      <CardDetailModal
        item={detailItem}
        onClose={() => setDetailItem(null)}
        onUpdated={fetchItems}
        imageUrl={detailItem?.card_id ? getImageUrl(detailItem.card_id) : null}
      />
    </div>
  )
}

function FilterSelect({
  value,
  onChange,
  options,
  placeholder,
}: {
  value: string
  onChange: (v: string) => void
  options: string[]
  placeholder: string
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="vault-field px-2.5 py-1.5 rounded-lg text-xs appearance-none cursor-pointer"
    >
      <option value="">{placeholder}</option>
      {options.filter(Boolean).map((opt) => (
        <option key={opt} value={opt}>
          {opt.replace(/_/g, ' ')}
        </option>
      ))}
    </select>
  )
}

function CreateItemModal({
  onClose,
  onCreated,
}: {
  onClose: () => void
  onCreated: () => void
}) {
  const api = useAdminApi()
  const [form, setForm] = useState({
    kind: 'raw',
    display_name: '',
    condition: 'NM',
    finish: 'normal',
    language: 'EN',
    location: 'toploader',
    cost_basis: '',
    current_market_value: '',
    notes: '',
  })
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!form.display_name.trim()) {
      setError('Name is required')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      const body: Record<string, unknown> = {
        kind: form.kind,
        display_name: form.display_name.trim(),
        condition: form.condition,
        finish: form.finish,
        language: form.language,
        location: form.location,
        notes: form.notes || undefined,
      }
      if (form.cost_basis) body.cost_basis = form.cost_basis
      if (form.current_market_value) body.current_market_value = form.current_market_value

      await api.post('/inventory', body)
      onCreated()
    } catch (err) {
      setError(err instanceof AdminApiError ? (err.detail || err.message) : 'Failed to create item')
    } finally {
      setSubmitting(false)
    }
  }

  const update = (field: string, value: string) => setForm((f) => ({ ...f, [field]: value }))

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60" onClick={onClose}>
      <form
        onClick={(e) => e.stopPropagation()}
        onSubmit={handleSubmit}
        className="vault-panel rounded-xl p-5 w-full max-w-md shadow-2xl space-y-4"
      >
        <h2 className="text-sm font-semibold text-pine-100">Add New Item</h2>

        {error && <p className="text-xs text-red-400">{error}</p>}

        <div className="grid grid-cols-2 gap-3">
          <label className="col-span-2">
            <span className="text-[11px] text-pine-400 uppercase tracking-wider">Name</span>
            <input value={form.display_name} onChange={(e) => update('display_name', e.target.value)} className="vault-field w-full mt-1 px-2.5 py-1.5 rounded-lg text-sm" required />
          </label>
          <label>
            <span className="text-[11px] text-pine-400 uppercase tracking-wider">Kind</span>
            <select value={form.kind} onChange={(e) => update('kind', e.target.value)} className="vault-field w-full mt-1 px-2.5 py-1.5 rounded-lg text-xs">
              <option value="raw">Raw</option>
              <option value="graded">Graded</option>
              <option value="sealed">Sealed</option>
              <option value="bulk">Bulk</option>
            </select>
          </label>
          <label>
            <span className="text-[11px] text-pine-400 uppercase tracking-wider">Condition</span>
            <select value={form.condition} onChange={(e) => update('condition', e.target.value)} className="vault-field w-full mt-1 px-2.5 py-1.5 rounded-lg text-xs">
              {['M', 'NM', 'LP', 'MP', 'HP', 'D'].map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </label>
          <label>
            <span className="text-[11px] text-pine-400 uppercase tracking-wider">Location</span>
            <input value={form.location} onChange={(e) => update('location', e.target.value)} className="vault-field w-full mt-1 px-2.5 py-1.5 rounded-lg text-xs" />
          </label>
          <label>
            <span className="text-[11px] text-pine-400 uppercase tracking-wider">Language</span>
            <select value={form.language} onChange={(e) => update('language', e.target.value)} className="vault-field w-full mt-1 px-2.5 py-1.5 rounded-lg text-xs">
              {['EN', 'JP', 'FR', 'DE', 'ES', 'IT', 'PT', 'KO', 'ZH'].map((l) => <option key={l} value={l}>{l}</option>)}
            </select>
          </label>
          <label>
            <span className="text-[11px] text-pine-400 uppercase tracking-wider">Cost Basis ($)</span>
            <input type="number" step="0.01" value={form.cost_basis} onChange={(e) => update('cost_basis', e.target.value)} className="vault-field w-full mt-1 px-2.5 py-1.5 rounded-lg text-xs" />
          </label>
          <label>
            <span className="text-[11px] text-pine-400 uppercase tracking-wider">Market Value ($)</span>
            <input type="number" step="0.01" value={form.current_market_value} onChange={(e) => update('current_market_value', e.target.value)} className="vault-field w-full mt-1 px-2.5 py-1.5 rounded-lg text-xs" />
          </label>
          <label className="col-span-2">
            <span className="text-[11px] text-pine-400 uppercase tracking-wider">Notes</span>
            <textarea value={form.notes} onChange={(e) => update('notes', e.target.value)} rows={2} className="vault-field w-full mt-1 px-2.5 py-1.5 rounded-lg text-xs resize-none" />
          </label>
        </div>

        <div className="flex justify-end gap-2 pt-2">
          <button type="button" onClick={onClose} className="px-3.5 py-1.5 rounded-lg text-xs font-medium text-pine-300 hover:bg-pine-700/50">Cancel</button>
          <button type="submit" disabled={submitting} className="px-3.5 py-1.5 rounded-lg text-xs font-medium bg-mint/15 text-mint border border-mint/30 hover:bg-mint/25 disabled:opacity-50">
            {submitting ? 'Creating…' : 'Create'}
          </button>
        </div>
      </form>
    </div>
  )
}
