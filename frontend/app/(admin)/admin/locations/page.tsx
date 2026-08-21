'use client'

import { useCallback, useEffect, useState } from 'react'
import { MapPinned, Plus, Trash2 } from 'lucide-react'
import { useAdminApi, AdminApiError } from '@/lib/admin-api'
import DataTable, { Column } from '@/components/admin/shared/DataTable'
import ConfirmDialog from '@/components/admin/shared/ConfirmDialog'

interface LocationOption {
  value: string
  label: string
  [key: string]: unknown
}

export default function AdminLocationsPage() {
  const api = useAdminApi()

  const [locations, setLocations] = useState<LocationOption[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  // RFC 0013 T4b — server-side sort via services/locations_sort.py. `null`
  // keeps today's storage order, which is what `GET /locations` has always
  // returned with no `sort` sent.
  const [sortKey, setSortKey] = useState<string | null>(null)
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')

  const [newValue, setNewValue] = useState('')
  const [newLabel, setNewLabel] = useState('')
  const [saving, setSaving] = useState(false)

  const [deleteTarget, setDeleteTarget] = useState<LocationOption | null>(null)

  const fetchLocations = useCallback(async () => {
    if (!api.isAuthenticated) return
    setLoading(true)
    try {
      const params: Record<string, string> = {}
      if (sortKey) params.sort = `${sortKey}_${sortDir}`
      const res = await api.get<LocationOption[]>('/locations', params)
      setLocations(Array.isArray(res) ? res : [])
    } catch {
      setLocations([])
    } finally {
      setLoading(false)
    }
  }, [api, sortKey, sortDir])

  useEffect(() => {
    fetchLocations()
  }, [fetchLocations])

  const handleAdd = async () => {
    if (!newValue.trim()) return
    setSaving(true)
    setError(null)
    try {
      await api.post('/locations', {
        value: newValue.trim(),
        label: newLabel.trim() || undefined,
      })
      setNewValue('')
      setNewLabel('')
      fetchLocations()
    } catch (err) {
      setError(err instanceof AdminApiError ? (err.detail ?? 'Failed to add location') : 'Failed to add location')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async () => {
    if (!deleteTarget) return
    setError(null)
    try {
      await api.del(`/locations/${deleteTarget.value}`)
      setDeleteTarget(null)
      fetchLocations()
    } catch (err) {
      setError(err instanceof AdminApiError ? (err.detail ?? 'Failed to delete location') : 'Failed to delete location')
      setDeleteTarget(null)
    }
  }

  const handleSort = (key: string) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir('desc')
    }
  }

  const columns: Column<LocationOption>[] = [
    {
      key: 'label',
      label: 'Label',
      sortable: true,
      render: (loc) => <span className="text-pine-100 text-sm font-medium">{loc.label}</span>,
    },
    {
      key: 'value',
      label: 'Value',
      sortable: true,
      render: (loc) => <span className="text-xs text-pine-400 font-mono">{loc.value}</span>,
    },
    {
      key: '_actions',
      label: '',
      className: 'w-16',
      render: (loc) => (
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); setDeleteTarget(loc) }}
          className="p-1 rounded text-pine-400 hover:text-red-400 transition-colors"
          aria-label={`Delete ${loc.label}`}
        >
          <Trash2 size={14} />
        </button>
      ),
    },
  ]

  return (
    <div className="p-6 lg:p-8">
      {/*
        aria-hidden while the delete confirmation is open: the row-level
        "Delete {label}" button and the dialog's "Delete" confirm button both
        match role=button name=/delete/i, which makes them ambiguous to
        role/label queries once both are in the accessibility tree at once.
        A real browser's dialog.showModal() makes the rest of the document
        inert automatically; jsdom doesn't implement that, so this page does
        it explicitly to keep exactly one matching control live at a time —
        matching the CreateItemModal role="dialog" scoping precedent used
        elsewhere in the admin app for the same ambiguity.
      */}
      <div aria-hidden={deleteTarget ? true : undefined}>
        <header className="mb-6">
          <span className="font-mono text-[11px] uppercase tracking-[0.22em] text-mint/70">Admin</span>
          <h1 className="text-xl font-semibold text-pine-100 flex items-center gap-2">
            <MapPinned size={18} className="text-mint" />
            Locations
          </h1>
        </header>

        {error && (
          <div className="text-xs text-red-400 bg-red-400/10 border border-red-400/20 rounded px-3 py-2 mb-4">
            {error}
          </div>
        )}

        <div className="vault-panel rounded-xl p-4 mb-6 flex items-end gap-3 flex-wrap">
          <div>
            <label htmlFor="new-location-value" className="block text-[11px] text-pine-400 mb-1">Value</label>
            <input
              id="new-location-value"
              type="text"
              value={newValue}
              onChange={(e) => setNewValue(e.target.value)}
              placeholder="display_case_2"
              className="vault-field px-3 py-2 rounded-lg text-sm"
            />
          </div>
          <div>
            <label htmlFor="new-location-label" className="block text-[11px] text-pine-400 mb-1">Label</label>
            <input
              id="new-location-label"
              type="text"
              value={newLabel}
              onChange={(e) => setNewLabel(e.target.value)}
              placeholder="Display Case 2"
              className="vault-field px-3 py-2 rounded-lg text-sm"
            />
          </div>
          <button
            type="button"
            onClick={handleAdd}
            disabled={!newValue.trim() || saving}
            className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium bg-mint/15 text-mint border border-mint/30 hover:bg-mint/25 disabled:opacity-40 transition-colors"
          >
            <Plus size={14} />
            {saving ? 'Adding…' : 'Add Location'}
          </button>
        </div>

        <DataTable
          columns={columns}
          data={locations}
          keyField="value"
          loading={loading}
          emptyMessage="No locations found"
          sortKey={sortKey}
          sortDir={sortDir}
          onSort={handleSort}
        />
      </div>

      <ConfirmDialog
        open={!!deleteTarget}
        title="Delete Location"
        description={`Delete "${deleteTarget?.label}"? This only works if no inventory item currently uses it.`}
        confirmLabel="Delete"
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  )
}
