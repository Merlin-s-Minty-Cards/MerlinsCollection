'use client'

import { useCallback, useEffect, useState } from 'react'
import { Plus, RefreshCw, Columns3, EyeOff } from 'lucide-react'
import { useAdminApi, AdminApiError } from '@/lib/admin-api'
import { CONDITION_OPTIONS as COND_VALUES } from '@/lib/constants'
import { useCardImages } from '@/lib/use-card-images'
import { useLocations } from '@/lib/use-locations'
import { useShows } from '@/lib/use-shows'
import { useCatalogSets, toComboboxSets } from '@/lib/use-catalog-sets'
import SetCombobox from '@/components/shared/SetCombobox'
import DataTable from '@/components/admin/shared/DataTable'
import SearchInput from '@/components/admin/shared/SearchInput'
import ColumnFilter from '@/components/admin/shared/ColumnFilter'
import ConfirmDialog from '@/components/admin/shared/ConfirmDialog'
import ImageToggle from '@/components/admin/shared/ImageToggle'
import CardDetailModal from '@/components/admin/shared/CardDetailModal'
import { patchRow } from '@/lib/item-update'
import { adminItemName } from '@/lib/admin-item-name'
import {
  INVENTORY_FILTERS,
  TOGGLEABLE_COLUMNS,
  DEFAULT_VISIBLE_COLUMN_KEYS,
  buildFilterParams,
  isFilterVisible,
  loadVisibleColumnKeys,
  saveVisibleColumnKeys,
  toDataTableColumns,
  type FilterValues,
  type InventoryFilterDef,
  type InventoryItem,
} from '@/lib/admin-inventory-columns'

/** The image column is a registry entry now, not a second competing toggle. */
const IMAGE_COLUMN_KEY = '_image'

export default function AdminInventoryPage() {
  const api = useAdminApi()
  const [items, setItems] = useState<InventoryItem[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  // ONE record keyed by filter id, not thirteen `useState`s (RFC 0011 T4).
  // Every filter added used to cost a state hook, a JSX block and a line in
  // `fetchItems`' dependency array — which is how the panel came to cover
  // twelve of thirty-three columns. `''` is the unset value throughout.
  const [filterValues, setFilterValues] = useState<FilterValues>({})
  const setFilter = useCallback(
    (id: string, value: string) => setFilterValues((v) => ({ ...v, [id]: value })),
    [],
  )
  const [sortKey, setSortKey] = useState<string | null>(null)
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')

  // Editing
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editField, setEditField] = useState<string | null>(null)
  const [editValue, setEditValue] = useState('')
  const [editOriginalValue, setEditOriginalValue] = useState('')

  // Delete dialog
  const [deleteTarget, setDeleteTarget] = useState<InventoryItem | null>(null)
  const [deleting, setDeleting] = useState(false)

  // Create form
  const [showCreate, setShowCreate] = useState(false)

  // Column visibility (T6). Starts at the defaults and is replaced from
  // localStorage in an effect — reading storage during render would both throw
  // on the server and give React a different tree to hydrate than it rendered.
  const [visibleColumns, setVisibleColumns] = useState<string[]>(DEFAULT_VISIBLE_COLUMN_KEYS)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [showAllFilters, setShowAllFilters] = useState(false)

  useEffect(() => {
    setVisibleColumns(loadVisibleColumnKeys())
  }, [])

  // Detail modal
  const [detailItem, setDetailItem] = useState<InventoryItem | null>(null)

  // Market price refresh
  const [refreshing, setRefreshing] = useState(false)
  const [refreshResult, setRefreshResult] = useState<string | null>(null)

  // Dynamic locations dropdown
  const { options: locationOptions } = useLocations()

  // `acquired_show_id` stores an opaque id; the filter has to offer names.
  const { options: showOptions } = useShows()

  // Every set in the CATALOG, fetched once and narrowed in the browser — so a
  // set we own nothing from is still pickable. That is the whole point of the
  // control (RFC 0008 Q8); inventory-derived options could never show one.
  const { sets: catalogSets } = useCatalogSets()

  const visible = new Set(visibleColumns)
  const showImages = visible.has(IMAGE_COLUMN_KEY)

  // Resolve card images
  const cardIds = items.map((i) => i.card_id as string | undefined)
  const { getImageUrl } = useCardImages(showImages ? cardIds : [])

  /**
   * Persist on the toggle rather than in an effect. An effect keyed on
   * `visibleColumns` would fire once on mount with the still-default state and
   * overwrite the saved list before the load effect's value had landed.
   */
  const toggleColumn = (key: string) => {
    // Functional updater, so two toggles batched into one render cannot lose
    // the first. The write inside it is idempotent, which is what makes it safe
    // under StrictMode's double-invoked updaters.
    setVisibleColumns((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      // Never leave a table with no columns at all. The picker also disables
      // the last checkbox, so this is the belt to that's braces.
      if (next.size === 0) return prev
      const ordered = TOGGLEABLE_COLUMNS.filter((c) => next.has(c.key)).map((c) => c.key)
      saveVisibleColumnKeys(ordered)
      return ordered
    })
  }

  const showColumn = (key: string) => {
    if (!visible.has(key)) toggleColumn(key)
  }

  const fetchItems = useCallback(async () => {
    if (!api.isAuthenticated) return
    setLoading(true)
    try {
      // Two spellings, one evaluator: the pre-existing named parameters, plus
      // the repeatable generic `filter={field}:{op}:{value}`. `buildFilterParams`
      // is the only place that knows which filter is which.
      //
      // Note: set_id, card_number, and artist only match catalog-linked items
      // (the backend drops card_id=None rows for those — known behavior).
      const { params: named, filters } = buildFilterParams(filterValues)
      const params: Record<string, string | string[]> = { ...named }
      if (filters.length > 0) params.filter = filters
      if (sortKey) params.sort = `${sortKey}_${sortDir}`

      const res = await api.get<{ items: InventoryItem[]; total: number }>('/inventory/search', params)
      setItems(res.items)
      setTotal(res.total)
    } catch {
      // handle silently
    } finally {
      setLoading(false)
    }
  }, [api, filterValues, sortKey, sortDir])

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
    const value = String((item as Record<string, unknown>)[field] ?? '')
    setEditValue(value)
    setEditOriginalValue(value)
  }

  const cancelEdit = () => {
    setEditingId(null)
    setEditField(null)
  }

  const saveEdit = async () => {
    if (!editingId || !editField) return
    // No-op guard: skip the PUT entirely when nothing actually changed. This
    // also protects null-location items — the inline editor lost its
    // "— None —" option once location became required (Task 8), so opening
    // the editor on such an item and blurring without picking anything used
    // to always send `location: null` and 422 (Round 6 audit finding 6).
    if (editValue === editOriginalValue) {
      setEditingId(null)
      setEditField(null)
      return
    }
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
      // If already lost, perform hard delete; otherwise soft-delete (mark as lost)
      const isLost = deleteTarget.status === 'lost'
      const url = isLost
        ? `/inventory/${deleteTarget.item_id}?hard=true`
        : `/inventory/${deleteTarget.item_id}`
      await api.del(url)
      setDeleteTarget(null)
      fetchItems()
    } catch (err) {
      if (err instanceof AdminApiError) alert(err.detail || err.message)
    } finally {
      setDeleting(false)
    }
  }

  const handleRefreshPrices = async () => {
    setRefreshing(true)
    setRefreshResult(null)
    try {
      const res = await api.post<{ checked: number; updated: number; total_eligible: number }>('/inventory/refresh-prices', {})
      setRefreshResult(`Updated ${res.updated} of ${res.checked} items checked (${res.total_eligible} eligible)`)
      if (res.updated > 0) fetchItems()
    } catch (err) {
      setRefreshResult(err instanceof AdminApiError ? (err.detail ?? 'Refresh failed') : 'Refresh failed')
    } finally {
      setRefreshing(false)
    }
  }

  const columns = toDataTableColumns(visible, {
    editingId, editField, editValue, setEditValue,
    startEdit, saveEdit, cancelEdit,
    locationOptions, getImageUrl,
    onRefresh: fetchItems,
    onDelete: setDeleteTarget,
  })

  // --- Filters ------------------------------------------------------------
  // The panel is driven by INVENTORY_FILTERS so that "which filters are shown"
  // and "which columns are visible" cannot drift apart. Since T4 the registry
  // is TOTAL and every control is rendered from its declared `kind`, so a new
  // column arrives with a working filter rather than needing one written by
  // hand — which is what let coverage rot to twelve of thirty-three.
  //
  // Two entries are still rendered here rather than by `ColumnFilter`, because
  // neither is a plain form control: Name is a debounced `SearchInput`, and Set
  // is a combobox over ~400 catalog sets.
  const selectOptions = (def: InventoryFilterDef) => {
    if (def.optionSource === 'locations') return locationOptions
    if (def.optionSource === 'shows') return showOptions
    return def.options ?? []
  }

  const renderFilter = (def: InventoryFilterDef) => {
    const value = filterValues[def.id] ?? ''
    if (def.id === 'search') {
      return (
        <SearchInput
          ariaLabel="Name"
          value={value}
          onChange={(v) => setFilter('search', v)}
          placeholder="Search by name…"
        />
      )
    }
    if (def.id === 'setId') {
      return (
        <SetCombobox
          sets={toComboboxSets(catalogSets)}
          value={value}
          onChange={(v) => setFilter('setId', v)}
          inputId="admin-inv-set"
          ariaLabel="Set"
          placeholder="All sets"
          emptyLabel="All sets"
          className="vault-field px-2.5 py-1.5 rounded-lg text-xs w-full"
        />
      )
    }
    return (
      <ColumnFilter
        def={def}
        value={value}
        onChange={(v) => setFilter(def.id, v)}
        options={selectOptions(def)}
      />
    )
  }

  const shownFilters = INVENTORY_FILTERS.filter((f) => isFilterVisible(f, visible, showAllFilters))
  // An active filter whose column is not on screen changes the result set for a
  // reason the admin cannot see. That is the failure mode this whole feature
  // has to avoid, so it is named explicitly rather than left to be discovered.
  const hiddenActiveFilters = INVENTORY_FILTERS.filter(
    (f) => (filterValues[f.id] ?? '') !== '' && (f.columnKey === null || !visible.has(f.columnKey)),
  )

  return (
    <div className="p-6 lg:p-8">
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
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleRefreshPrices}
            disabled={refreshing}
            className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-xs font-medium text-pine-300 border border-pine-700/40 hover:border-pine-600 hover:text-pine-100 disabled:opacity-40 transition-colors"
          >
            <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} />
            {refreshing ? 'Refreshing…' : 'Refresh Prices'}
          </button>
          <button
            type="button"
            onClick={() => setShowCreate(true)}
            className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-xs font-medium bg-mint/15 text-mint border border-mint/30 hover:bg-mint/25 transition-colors"
          >
            <Plus size={14} />
            Add Item
          </button>
        </div>
      </header>

      {/* Toolbar: what is on screen, and how much of the filter panel to show */}
      <div className="flex flex-wrap items-center gap-2 mb-3">
        <button
          type="button"
          onClick={() => setPickerOpen((open) => !open)}
          aria-expanded={pickerOpen}
          className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium text-pine-300 border border-pine-700/40 hover:border-pine-600 hover:text-pine-100 transition-colors"
        >
          <Columns3 size={14} />
          Columns
          {/* Decorative: the picker's own checkboxes carry this state, and
              folding the count into the button's accessible name would make it
              read as "Columns (9)". */}
          <span aria-hidden="true" className="text-pine-500">({visibleColumns.length})</span>
        </button>
        <button
          type="button"
          onClick={() => setShowAllFilters((all) => !all)}
          aria-pressed={showAllFilters}
          className={`inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
            showAllFilters
              ? 'border-mint/40 text-mint bg-mint/10 hover:bg-mint/15'
              : 'border-pine-700/40 text-pine-400 hover:text-pine-200 hover:border-pine-600'
          }`}
        >
          Show all filters
        </button>
        <ImageToggle
          showImages={showImages}
          onToggle={() => toggleColumn(IMAGE_COLUMN_KEY)}
          label="Images"
        />
      </div>

      {/* Column picker */}
      {pickerOpen && (
        <div
          role="group"
          aria-label="Column visibility"
          className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-x-4 gap-y-1.5 mb-4 p-3 rounded-xl border border-pine-700/40 bg-pine-800/20"
        >
          {TOGGLEABLE_COLUMNS.map((col) => (
            <label key={col.key} className="flex items-center gap-2 text-xs text-pine-300 cursor-pointer">
              <input
                type="checkbox"
                checked={visible.has(col.key)}
                onChange={() => toggleColumn(col.key)}
                // A silently unresponsive checkbox reads as broken. Disabling
                // the last one says "not allowed" instead of doing nothing.
                disabled={visible.has(col.key) && visibleColumns.length === 1}
                className="rounded border-pine-600 bg-pine-800 text-mint focus:ring-mint/30 disabled:opacity-40"
              />
              {col.label}
            </label>
          ))}
        </div>
      )}

      {/* Filters — only the ones whose column is on screen, unless overridden */}
      <div
        role="group"
        aria-label="Filters"
        className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-2 mb-4"
      >
        {shownFilters.map((f) => (
          <div key={f.id} className="contents">{renderFilter(f)}</div>
        ))}
      </div>

      {/* Filtering on something the table is not showing */}
      {hiddenActiveFilters.length > 0 && (
        <div
          role="region"
          aria-label="Filters on a hidden column"
          className="flex flex-wrap items-center gap-2 text-xs text-amber-300 bg-amber-400/5 border border-amber-400/20 rounded-lg px-3 py-2 mb-4"
        >
          <EyeOff size={14} className="flex-shrink-0" />
          <span className="text-pine-300">Filtering on a hidden column:</span>
          {hiddenActiveFilters.map((f) => (
            <span
              key={f.id}
              className="inline-flex items-center gap-1.5 rounded-md border border-amber-400/30 bg-amber-400/10 px-2 py-0.5"
            >
              <span>{f.label}: {filterValues[f.id]}</span>
              {f.columnKey && (
                <button
                  type="button"
                  onClick={() => showColumn(f.columnKey as string)}
                  className="text-mint hover:text-mint/80 underline underline-offset-2"
                >
                  Show column
                </button>
              )}
              <button
                type="button"
                onClick={() => setFilter(f.id, '')}
                aria-label={`Clear ${f.label} filter`}
                className="text-pine-400 hover:text-pine-200"
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}

      {/* Refresh result toast */}
      {refreshResult && (
        <div className="flex items-center gap-2 text-xs text-mint bg-mint/5 border border-mint/20 rounded-lg px-3 py-2 mb-4">
          <RefreshCw size={14} />
          {refreshResult}
          <button
            type="button"
            onClick={() => setRefreshResult(null)}
            className="ml-auto text-pine-500 hover:text-pine-300"
            aria-label="Dismiss"
          >
            ×
          </button>
        </div>
      )}

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
        title={deleteTarget?.status === 'lost' ? 'Permanently Delete' : 'Delete Item'}
        description={
          deleteTarget?.status === 'lost'
            ? `This will permanently delete "${adminItemName(deleteTarget, 'this item')}". This cannot be undone.`
            : `Are you sure you want to delete "${adminItemName(deleteTarget, 'this item')}"? This will mark it as lost.`
        }
        confirmLabel={deleteTarget?.status === 'lost' ? 'Permanently Delete' : 'Delete'}
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
        // Patch the one row rather than refetching (RFC 0010 T5). A refetch
        // replaces the array, re-mounts the table and throws an admin who had
        // scrolled well down back to the top — the second half of the owner's
        // report. `updated` is absent only when the response was not a
        // recognisable item, where a refetch is the honest answer.
        onUpdated={(updated) => {
          if (!updated) { fetchItems(); return }
          setItems((rows) => patchRow(rows, updated))
        }}
      />
    </div>
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
  const { options: locationOptions, loading: locationsLoading } = useLocations()
  const [form, setForm] = useState({
    kind: 'raw',
    display_name: '',
    condition: 'NM',
    finish: 'normal',
    language: 'EN',
    location: '',
    cost_basis: '',
    current_market_value: '',
    notes: '',
  })
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Seed the location default from the live list once it loads, instead of
  // a hardcoded string — a hardcoded default (e.g. "toploader") can point at
  // a location an admin has since deleted via DELETE /admin/locations/{value}
  // (allowed once no item uses it), which then 422s "Unknown location" on
  // submit unless the admin happens to touch the dropdown themselves
  // (Round 6 audit finding 2). Waits for `loading` to clear rather than just
  // "options non-empty" — useLocations() starts synchronously populated with
  // its static offline-fallback list (see use-locations.ts), so seeding on
  // the first non-empty render would grab that fallback instead of the real
  // list once it lands. Only seeds while still empty, so it never clobbers
  // an explicit pick.
  useEffect(() => {
    if (!form.location && !locationsLoading && locationOptions.length > 0) {
      setForm((f) => (f.location ? f : { ...f, location: locationOptions[0].value }))
    }
  }, [locationOptions, locationsLoading, form.location])

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
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Add New Item"
    >
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
              {COND_VALUES.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </label>
          <label>
            <span className="text-[11px] text-pine-400 uppercase tracking-wider">Location</span>
            <select value={form.location} onChange={(e) => update('location', e.target.value)} className="vault-field w-full mt-1 px-2.5 py-1.5 rounded-lg text-xs">
              {locationOptions.map((loc) => <option key={loc.value} value={loc.value}>{loc.label}</option>)}
            </select>
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
