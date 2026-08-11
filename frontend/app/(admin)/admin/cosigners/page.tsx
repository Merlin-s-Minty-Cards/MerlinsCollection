'use client'

import { useCallback, useEffect, useState } from 'react'
import {
  Users,
  Plus,
  Edit3,
  Trash2,
  Link2,
  BarChart3,
  X,
  Check,
  Package,
} from 'lucide-react'
import { useAdminApi, AdminApiError } from '@/lib/admin-api'
import SearchInput from '@/components/admin/shared/SearchInput'
import DataTable, { Column } from '@/components/admin/shared/DataTable'
import PriceDisplay from '@/components/admin/shared/PriceDisplay'
import ConfirmDialog from '@/components/admin/shared/ConfirmDialog'
import StatusBadge from '@/components/admin/shared/StatusBadge'
import MoneyInput from '@/components/admin/shared/MoneyInput'
import { parseMoney } from '@/lib/money'
import { adminItemName } from '@/lib/admin-item-name'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Cosigner {
  consignor_id: string
  name: string
  email?: string | null
  phone?: string | null
  contact?: string | null
  payout_percent: string | number
  active: boolean
  notes?: string | null
  [key: string]: unknown
}

interface CosignerAnalytics {
  consignor_id: string
  total_items: number
  items_sold: number
  total_value: string
}

interface CosignerAsset {
  item_id: string
  product_name?: string
  display_name?: string
  name?: string
  cost_basis?: string
  status?: string
  location?: string
  [key: string]: unknown
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export default function AdminCosignersPage() {
  const api = useAdminApi()

  // Cosigner list
  const [cosigners, setCosigners] = useState<Cosigner[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')

  // Form mode
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<Cosigner | null>(null)

  // Form fields
  const [formName, setFormName] = useState('')
  const [formEmail, setFormEmail] = useState('')
  const [formPhone, setFormPhone] = useState('')
  const [formPayout, setFormPayout] = useState('50')
  const [formNotes, setFormNotes] = useState('')
  const [saving, setSaving] = useState(false)

  // Detail / analytics view
  const [selectedCosigner, setSelectedCosigner] = useState<Cosigner | null>(null)
  const [analytics, setAnalytics] = useState<CosignerAnalytics | null>(null)
  const [assets, setAssets] = useState<CosignerAsset[]>([])
  const [loadingDetail, setLoadingDetail] = useState(false)

  // Link items
  const [linkOpen, setLinkOpen] = useState(false)
  const [linkItemIds, setLinkItemIds] = useState('')
  const [linkSplit, setLinkSplit] = useState('')
  const [linkMinPrice, setLinkMinPrice] = useState('')
  const [linking, setLinking] = useState(false)

  // Delete confirmation
  const [deleteTarget, setDeleteTarget] = useState<Cosigner | null>(null)

  // Unlink confirmation
  const [unlinkTarget, setUnlinkTarget] = useState<CosignerAsset | null>(null)
  const [unlinking, setUnlinking] = useState(false)

  // ---------------------------------------------------------------------------
  // Data fetching
  // ---------------------------------------------------------------------------

  const fetchCosigners = useCallback(async () => {
    if (!api.isAuthenticated) return
    setLoading(true)
    try {
      const res = await api.get<Cosigner[]>('/cosigners')
      setCosigners(Array.isArray(res) ? res : [])
    } catch {
      setCosigners([])
    } finally {
      setLoading(false)
    }
  }, [api])

  useEffect(() => {
    fetchCosigners()
  }, [fetchCosigners])

  const fetchDetail = useCallback(
    async (cosigner: Cosigner) => {
      if (!api.isAuthenticated) return
      setLoadingDetail(true)
      try {
        const [analyticsRes, assetsRes] = await Promise.all([
          api.get<CosignerAnalytics>(`/cosigners/${cosigner.consignor_id}/analytics`),
          api.get<{ items: CosignerAsset[]; total: number }>(`/cosigners/${cosigner.consignor_id}/assets`),
        ])
        setAnalytics(analyticsRes)
        setAssets(assetsRes.items)
      } catch {
        setAnalytics(null)
        setAssets([])
      } finally {
        setLoadingDetail(false)
      }
    },
    [api],
  )

  // ---------------------------------------------------------------------------
  // Form handlers
  // ---------------------------------------------------------------------------

  const openCreateForm = () => {
    setEditing(null)
    setFormName('')
    setFormEmail('')
    setFormPhone('')
    setFormPayout('50')
    setFormNotes('')
    setFormOpen(true)
  }

  const openEditForm = (cosigner: Cosigner) => {
    setEditing(cosigner)
    setFormName(cosigner.name)
    setFormEmail(cosigner.email || '')
    setFormPhone(cosigner.phone || '')
    setFormPayout(String(cosigner.payout_percent))
    setFormNotes(cosigner.notes || '')
    setFormOpen(true)
  }

  const handleSave = async () => {
    if (!formName.trim()) return
    setSaving(true)
    try {
      const payload: Record<string, unknown> = {
        name: formName.trim(),
        email: formEmail.trim() || null,
        phone: formPhone.trim() || null,
        payout_percent: parseFloat(formPayout) || 50,
        notes: formNotes.trim() || null,
      }

      if (editing) {
        await api.patch(`/cosigners/${editing.consignor_id}`, payload)
      } else {
        await api.post('/cosigners', payload)
      }

      setFormOpen(false)
      fetchCosigners()
      // Refresh detail if viewing the edited cosigner
      if (selectedCosigner && editing && selectedCosigner.consignor_id === editing.consignor_id) {
        fetchDetail(selectedCosigner)
      }
    } catch (err) {
      alert(err instanceof AdminApiError ? err.detail : 'Failed to save cosigner')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async () => {
    if (!deleteTarget) return
    try {
      await api.del(`/cosigners/${deleteTarget.consignor_id}`)
      setDeleteTarget(null)
      if (selectedCosigner?.consignor_id === deleteTarget.consignor_id) {
        setSelectedCosigner(null)
        setAnalytics(null)
        setAssets([])
      }
      fetchCosigners()
    } catch (err) {
      alert(err instanceof AdminApiError ? err.detail : 'Failed to delete cosigner')
    }
  }

  // ---------------------------------------------------------------------------
  // Link items
  // ---------------------------------------------------------------------------

  const handleLinkItems = async () => {
    if (!selectedCosigner || !linkItemIds.trim()) return
    setLinking(true)
    try {
      const ids = linkItemIds
        .split(/[,\n]+/)
        .map((s) => s.trim())
        .filter(Boolean)

      const payload: Record<string, unknown> = { item_ids: ids }
      // split_percent is a bounded percent, not money — no thousands separator
      // is possible, so parseFloat stays. minimum_price IS money.
      if (linkSplit.trim()) payload.split_percent = parseFloat(linkSplit) / 100
      if (linkMinPrice.trim()) {
        const minPrice = parseMoney(linkMinPrice)
        if (minPrice === null) { setLinking(false); return }
        payload.minimum_price = String(minPrice)
      }

      const result = await api.post<{ linked: number; failed_item_ids: string[] }>(
        `/cosigners/${selectedCosigner.consignor_id}/link`,
        payload,
      )
      setLinkOpen(false)
      setLinkItemIds('')
      setLinkSplit('')
      setLinkMinPrice('')
      if (result.failed_item_ids.length > 0) {
        alert(`Linked ${result.linked} item(s). Not found: ${result.failed_item_ids.join(', ')}`)
      }
      fetchDetail(selectedCosigner)
    } catch (err) {
      alert(err instanceof AdminApiError ? err.detail : 'Failed to link items')
    } finally {
      setLinking(false)
    }
  }

  const handleUnlink = async () => {
    if (!selectedCosigner || !unlinkTarget) return
    setUnlinking(true)
    try {
      await api.del(`/cosigners/${selectedCosigner.consignor_id}/assets/${unlinkTarget.item_id}`)
      setUnlinkTarget(null)
      fetchDetail(selectedCosigner)
    } catch (err) {
      alert(err instanceof AdminApiError ? err.detail : 'Failed to unlink item')
    } finally {
      setUnlinking(false)
    }
  }

  // ---------------------------------------------------------------------------
  // Filtering
  // ---------------------------------------------------------------------------

  const filtered = cosigners.filter((c) => {
    if (!search) return true
    const term = search.toLowerCase()
    return (
      c.name.toLowerCase().includes(term) ||
      (c.email && c.email.toLowerCase().includes(term)) ||
      (c.phone && c.phone.includes(term))
    )
  })

  // ---------------------------------------------------------------------------
  // Table columns
  // ---------------------------------------------------------------------------

  const columns: Column<Cosigner>[] = [
    {
      key: 'name',
      label: 'Name',
      className: 'min-w-[140px]',
      render: (item) => (
        <span className="text-pine-100 text-sm font-medium">{item.name}</span>
      ),
    },
    {
      key: 'email',
      label: 'Email',
      render: (item) => (
        <span className="text-xs text-pine-300">{item.email || '—'}</span>
      ),
    },
    {
      key: 'phone',
      label: 'Phone',
      render: (item) => (
        <span className="text-xs text-pine-300">{item.phone || '—'}</span>
      ),
    },
    {
      key: 'payout_percent',
      label: 'Payout %',
      className: 'text-right',
      render: (item) => (
        <span className="text-xs font-mono text-mint">{item.payout_percent}%</span>
      ),
    },
    {
      key: 'active',
      label: 'Status',
      render: (item) => (
        <StatusBadge status={item.active ? 'available' : 'sold'} />
      ),
    },
    {
      key: '_actions',
      label: '',
      className: 'w-20',
      render: (item) => (
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              openEditForm(item)
            }}
            className="p-1 rounded text-pine-400 hover:text-pine-200 transition-colors"
            aria-label={`Edit ${item.name}`}
          >
            <Edit3 size={14} />
          </button>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              setDeleteTarget(item)
            }}
            className="p-1 rounded text-pine-400 hover:text-red-400 transition-colors"
            aria-label={`Delete ${item.name}`}
          >
            <Trash2 size={14} />
          </button>
        </div>
      ),
    },
  ]

  const assetColumns: Column<CosignerAsset>[] = [
    {
      key: 'name',
      label: 'Card',
      render: (item) => (
        <span className="text-pine-100 text-xs font-medium">
          {adminItemName(item)}
        </span>
      ),
    },
    {
      key: 'cost_basis',
      label: 'Value',
      className: 'text-right',
      render: (item) => <PriceDisplay value={item.cost_basis} className="text-xs" />,
    },
    {
      key: 'status',
      label: 'Status',
      render: (item) => <StatusBadge status={item.status || 'available'} />,
    },
    {
      key: 'location',
      label: 'Location',
      render: (item) => (
        <span className="text-xs text-pine-300 capitalize">{item.location || '—'}</span>
      ),
    },
    {
      key: '_actions',
      label: '',
      className: 'w-10',
      render: (item) => (
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); setUnlinkTarget(item) }}
          className="p-1 rounded text-pine-400 hover:text-red-400 transition-colors"
          aria-label={`Unlink ${adminItemName(item, item.item_id)}`}
        >
          <X size={13} />
        </button>
      ),
    },
  ]

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="p-6 lg:p-8 max-w-7xl">
      <header className="mb-6">
        <span className="font-mono text-[11px] uppercase tracking-[0.22em] text-mint/70">
          Admin
        </span>
        <h1 className="text-xl font-semibold text-pine-100">Cosigner Management</h1>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left column — cosigner list */}
        <div className="lg:col-span-2 space-y-4">
          {/* Search + Add */}
          <div className="flex items-center gap-3">
            <SearchInput
              value={search}
              onChange={setSearch}
              placeholder="Search cosigners…"
              className="flex-1"
            />
            <button
              type="button"
              onClick={openCreateForm}
              className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium bg-mint/15 text-mint border border-mint/30 hover:bg-mint/25 transition-colors"
            >
              <Plus size={14} />
              New Cosigner
            </button>
          </div>

          {/* Table */}
          <DataTable
            columns={columns}
            data={filtered}
            keyField="consignor_id"
            loading={loading}
            emptyMessage="No cosigners found"
            onRowClick={(item) => {
              setSelectedCosigner(item)
              fetchDetail(item)
            }}
          />
        </div>

        {/* Right column — detail panel */}
        <div className="space-y-4">
          {selectedCosigner ? (
            <>
              {/* Profile card */}
              <div className="vault-panel rounded-xl p-4">
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <Users size={16} className="text-mint" />
                    <h2 className="text-sm font-semibold text-pine-100">
                      {selectedCosigner.name}
                    </h2>
                  </div>
                  <StatusBadge status={selectedCosigner.active ? 'available' : 'sold'} />
                </div>
                <div className="space-y-1.5 text-xs text-pine-300">
                  {selectedCosigner.email && <p>Email: {selectedCosigner.email}</p>}
                  {selectedCosigner.phone && <p>Phone: {selectedCosigner.phone}</p>}
                  <p>Payout: <span className="text-mint font-mono">{selectedCosigner.payout_percent}%</span></p>
                  {selectedCosigner.notes && (
                    <p className="text-pine-400 italic mt-2">{selectedCosigner.notes}</p>
                  )}
                </div>
              </div>

              {/* Analytics card */}
              {analytics && (
                <div className="vault-panel rounded-xl p-4">
                  <div className="flex items-center gap-2 mb-3">
                    <BarChart3 size={15} className="text-mint" />
                    <h3 className="text-xs font-semibold text-pine-200 uppercase tracking-wider">
                      Analytics
                    </h3>
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <AnalyticsStat label="Total Items" value={String(analytics.total_items)} />
                    <AnalyticsStat label="Items Sold" value={String(analytics.items_sold)} />
                    <AnalyticsStat
                      label="Total Value"
                      value={`$${parseFloat(analytics.total_value || '0').toFixed(2)}`}
                      accent
                    />
                    <AnalyticsStat
                      label="Sell-Through"
                      value={
                        analytics.total_items > 0
                          ? `${Math.round((analytics.items_sold / analytics.total_items) * 100)}%`
                          : '0%'
                      }
                    />
                  </div>
                </div>
              )}

              {/* Assets section */}
              <div className="vault-panel rounded-xl p-4">
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <Package size={15} className="text-mint" />
                    <h3 className="text-xs font-semibold text-pine-200 uppercase tracking-wider">
                      Linked Assets ({assets.length})
                    </h3>
                  </div>
                  <button
                    type="button"
                    onClick={() => setLinkOpen(true)}
                    className="inline-flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium bg-mint/10 text-mint border border-mint/20 hover:bg-mint/20 transition-colors"
                  >
                    <Link2 size={11} />
                    Link Items
                  </button>
                </div>

                {loadingDetail ? (
                  <p className="text-xs text-pine-400">Loading…</p>
                ) : assets.length === 0 ? (
                  <p className="text-xs text-pine-500">No items linked to this cosigner.</p>
                ) : (
                  <div className="max-h-64 overflow-y-auto vault-scroll">
                    <DataTable
                      columns={assetColumns}
                      data={assets}
                      keyField="item_id"
                      emptyMessage="No assets"
                    />
                  </div>
                )}
              </div>
            </>
          ) : (
            <div className="vault-panel rounded-xl p-6 text-center">
              <Users size={32} className="text-pine-600 mx-auto mb-2" />
              <p className="text-xs text-pine-400">
                Select a cosigner to view details
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Create/Edit modal */}
      {formOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="vault-panel rounded-xl p-6 w-full max-w-md mx-4">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-semibold text-pine-100">
                {editing ? 'Edit Cosigner' : 'New Cosigner'}
              </h2>
              <button
                type="button"
                onClick={() => setFormOpen(false)}
                className="p-1 rounded text-pine-400 hover:text-pine-200"
                aria-label="Close form"
              >
                <X size={16} />
              </button>
            </div>

            <div className="space-y-3">
              <div>
                <label className="block text-[11px] text-pine-400 mb-1">Name *</label>
                <input
                  type="text"
                  value={formName}
                  onChange={(e) => setFormName(e.target.value)}
                  className="vault-field w-full px-3 py-2 rounded-lg text-sm"
                  placeholder="Cosigner name"
                />
              </div>
              <div>
                <label className="block text-[11px] text-pine-400 mb-1">Email</label>
                <input
                  type="email"
                  value={formEmail}
                  onChange={(e) => setFormEmail(e.target.value)}
                  className="vault-field w-full px-3 py-2 rounded-lg text-sm"
                  placeholder="email@example.com"
                />
              </div>
              <div>
                <label className="block text-[11px] text-pine-400 mb-1">Phone</label>
                <input
                  type="tel"
                  value={formPhone}
                  onChange={(e) => setFormPhone(e.target.value)}
                  className="vault-field w-full px-3 py-2 rounded-lg text-sm"
                  placeholder="(555) 123-4567"
                />
              </div>
              <div>
                <label className="block text-[11px] text-pine-400 mb-1">Payout %</label>
                <input
                  type="number"
                  min={0}
                  max={100}
                  value={formPayout}
                  onChange={(e) => setFormPayout(e.target.value)}
                  className="vault-field w-full px-3 py-2 rounded-lg text-sm font-mono"
                  placeholder="50"
                />
              </div>
              <div>
                <label className="block text-[11px] text-pine-400 mb-1">Notes</label>
                <textarea
                  value={formNotes}
                  onChange={(e) => setFormNotes(e.target.value)}
                  rows={2}
                  className="vault-field w-full px-3 py-2 rounded-lg text-sm resize-none"
                  placeholder="Any notes about this cosigner…"
                />
              </div>
            </div>

            <div className="flex justify-end gap-2 mt-5">
              <button
                type="button"
                onClick={() => setFormOpen(false)}
                className="px-3 py-1.5 rounded-lg text-xs text-pine-300 hover:text-pine-100 transition-colors"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleSave}
                disabled={!formName.trim() || saving}
                className="inline-flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-medium bg-mint/15 text-mint border border-mint/30 hover:bg-mint/25 disabled:opacity-40 transition-colors"
              >
                <Check size={13} />
                {saving ? 'Saving…' : editing ? 'Update' : 'Create'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Link items modal */}
      {linkOpen && selectedCosigner && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="vault-panel rounded-xl p-6 w-full max-w-md mx-4">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-semibold text-pine-100">
                Link Items to {selectedCosigner.name}
              </h2>
              <button
                type="button"
                onClick={() => setLinkOpen(false)}
                className="p-1 rounded text-pine-400 hover:text-pine-200"
                aria-label="Close link form"
              >
                <X size={16} />
              </button>
            </div>

            <div className="space-y-3">
              <div>
                <label className="block text-[11px] text-pine-400 mb-1">
                  Item IDs (comma or newline separated)
                </label>
                <textarea
                  value={linkItemIds}
                  onChange={(e) => setLinkItemIds(e.target.value)}
                  rows={3}
                  className="vault-field w-full px-3 py-2 rounded-lg text-xs font-mono resize-none"
                  placeholder="item_id_1, item_id_2, ..."
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[11px] text-pine-400 mb-1">Split % (optional)</label>
                  <input
                    type="number"
                    min={0}
                    max={100}
                    value={linkSplit}
                    onChange={(e) => setLinkSplit(e.target.value)}
                    className="vault-field w-full px-3 py-2 rounded-lg text-sm font-mono"
                    placeholder="Default"
                  />
                </div>
                <div>
                  <label className="block text-[11px] text-pine-400 mb-1">Min Price (optional)</label>
                  <MoneyInput
                    label="Min Price"
                    value={linkMinPrice}
                    onChange={(raw) => setLinkMinPrice(raw)}
                    className="vault-field w-full px-3 py-2 rounded-lg text-sm font-mono"
                    placeholder="$0.00"
                  />
                </div>
              </div>
            </div>

            <div className="flex justify-end gap-2 mt-5">
              <button
                type="button"
                onClick={() => setLinkOpen(false)}
                className="px-3 py-1.5 rounded-lg text-xs text-pine-300 hover:text-pine-100 transition-colors"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleLinkItems}
                disabled={!linkItemIds.trim() || linking}
                className="inline-flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-medium bg-mint/15 text-mint border border-mint/30 hover:bg-mint/25 disabled:opacity-40 transition-colors"
              >
                <Link2 size={13} />
                {linking ? 'Linking…' : 'Link Items'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete confirmation */}
      <ConfirmDialog
        open={!!deleteTarget}
        title="Deactivate Cosigner"
        description={`This will deactivate "${deleteTarget?.name}". Their linked items will remain in inventory.`}
        confirmLabel="Deactivate"
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
      />

      {/* Unlink confirmation — every other destructive action touched or
          added in this round (Locations delete, cosigner delete above)
          already goes through ConfirmDialog; unlink was the one click that
          fired immediately (Round 6 audit finding 4). */}
      <ConfirmDialog
        open={!!unlinkTarget}
        title="Unlink Item"
        description={`Remove "${adminItemName(unlinkTarget, 'this item')}" from ${selectedCosigner?.name}'s consigned assets?`}
        confirmLabel="Unlink"
        variant="danger"
        loading={unlinking}
        onConfirm={handleUnlink}
        onCancel={() => setUnlinkTarget(null)}
      />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Helper component
// ---------------------------------------------------------------------------

function AnalyticsStat({
  label,
  value,
  accent,
}: {
  label: string
  value: string
  accent?: boolean
}) {
  return (
    <div className="px-3 py-2 rounded-lg bg-pine-800/50 border border-pine-700/30">
      <div className="text-[10px] text-pine-400 mb-0.5">{label}</div>
      <div className={`text-sm font-mono font-semibold ${accent ? 'text-mint' : 'text-pine-100'}`}>
        {value}
      </div>
    </div>
  )
}
