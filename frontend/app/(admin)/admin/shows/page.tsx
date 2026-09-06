'use client'

import { useCallback, useEffect, useState } from 'react'
import { CalendarDays, Plus, Edit3, Archive, ArchiveRestore, X, Check } from 'lucide-react'
import { useAdminApi, AdminApiError } from '@/lib/admin-api'
import DataTable, { Column } from '@/components/admin/shared/DataTable'
import PriceDisplay from '@/components/admin/shared/PriceDisplay'
import ConfirmDialog from '@/components/admin/shared/ConfirmDialog'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Show {
  show_id: string
  name: string
  date: string
  venue?: string | null
  city?: string | null
  sales_goal?: string | null
  cash_at_start?: string | null
  inventory_value_at_start?: string | null
  notes?: string | null
  archived: boolean
  [key: string]: unknown
}

// Every optional numeric field: blank means "not set", which the backend models
// as null. Sending "" instead would 422 on a Decimal field.
function money(value: string): string | null {
  return value.trim() === '' ? null : value.trim()
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function AdminShowsPage() {
  const api = useAdminApi()

  const [shows, setShows] = useState<Show[]>([])
  const [loading, setLoading] = useState(true)
  const [includeArchived, setIncludeArchived] = useState(false)
  // RFC 0013 T4b — server-side sort via services/shows_sort.py. `null` keeps
  // the endpoint's existing date-desc default untouched (`GET /shows`
  // preserves that when no `sort` is sent).
  const [sortKey, setSortKey] = useState<string | null>(null)
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')

  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<Show | null>(null)
  const [saving, setSaving] = useState(false)

  const [formName, setFormName] = useState('')
  const [formDate, setFormDate] = useState('')
  const [formVenue, setFormVenue] = useState('')
  const [formCity, setFormCity] = useState('')
  const [formSalesGoal, setFormSalesGoal] = useState('')
  const [formCashAtStart, setFormCashAtStart] = useState('')
  const [formNotes, setFormNotes] = useState('')

  // Archive is the destructive-looking action, so it is gated. Unarchive is
  // not: restoring something can be undone by archiving again.
  const [archiveTarget, setArchiveTarget] = useState<Show | null>(null)
  const [archiving, setArchiving] = useState(false)

  // Returns a canceller rather than taking one: flipping "Show archived" twice
  // in quick succession puts two requests in flight for two DIFFERENT lists,
  // and without this the slower one wins and the table contradicts the toggle.
  const fetchShows = useCallback(() => {
    if (!api.isAuthenticated) return () => {}
    let cancelled = false
    setLoading(true)
    const params: Record<string, string | boolean> = { include_archived: includeArchived }
    if (sortKey) params.sort = `${sortKey}_${sortDir}`
    api
      .get<Show[]>('/shows', params)
      .then((res) => { if (!cancelled) setShows(Array.isArray(res) ? res : []) })
      .catch(() => { if (!cancelled) setShows([]) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [api, includeArchived, sortKey, sortDir])

  useEffect(() => fetchShows(), [fetchShows])

  // ---------------------------------------------------------------------------
  // Form
  // ---------------------------------------------------------------------------

  const openCreateForm = () => {
    setEditing(null)
    setFormName('')
    setFormDate('')
    setFormVenue('')
    setFormCity('')
    setFormSalesGoal('')
    setFormCashAtStart('')
    setFormNotes('')
    setFormOpen(true)
  }

  const openEditForm = (show: Show) => {
    setEditing(show)
    setFormName(show.name)
    setFormDate(show.date)
    setFormVenue(show.venue || '')
    setFormCity(show.city || '')
    setFormSalesGoal(show.sales_goal ? String(show.sales_goal) : '')
    setFormCashAtStart(show.cash_at_start ? String(show.cash_at_start) : '')
    setFormNotes(show.notes || '')
    setFormOpen(true)
  }

  const handleSave = async () => {
    if (!formName.trim() || !formDate) return
    setSaving(true)
    try {
      const payload: Record<string, unknown> = {
        name: formName.trim(),
        date: formDate,
        venue: formVenue.trim() || null,
        city: formCity.trim() || null,
        sales_goal: money(formSalesGoal),
        cash_at_start: money(formCashAtStart),
        notes: formNotes.trim() || null,
      }

      if (editing) {
        await api.put(`/shows/${editing.show_id}`, payload)
      } else {
        await api.post('/shows', payload)
      }

      setFormOpen(false)
      fetchShows()
    } catch (err) {
      alert(err instanceof AdminApiError ? err.detail : 'Failed to save show')
    } finally {
      setSaving(false)
    }
  }

  // ---------------------------------------------------------------------------
  // Archive / unarchive
  // ---------------------------------------------------------------------------

  const handleArchive = async () => {
    if (!archiveTarget) return
    setArchiving(true)
    try {
      await api.post(`/shows/${archiveTarget.show_id}/archive`)
      setArchiveTarget(null)
      fetchShows()
    } catch (err) {
      alert(err instanceof AdminApiError ? err.detail : 'Failed to archive show')
    } finally {
      setArchiving(false)
    }
  }

  const handleUnarchive = async (show: Show) => {
    try {
      await api.post(`/shows/${show.show_id}/unarchive`)
      fetchShows()
    } catch (err) {
      alert(err instanceof AdminApiError ? err.detail : 'Failed to unarchive show')
    }
  }

  // ---------------------------------------------------------------------------
  // Columns
  // ---------------------------------------------------------------------------

  const handleSort = (key: string) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir('desc')
    }
  }

  const columns: Column<Show>[] = [
    {
      key: 'date',
      label: 'Date',
      className: 'w-28',
      sortable: true,
      render: (show) => (
        <span className="text-xs font-mono text-pine-300">{show.date}</span>
      ),
      // The show SK embeds the date, and put_show sweeps superseded rows
      // after writing — an existing, already-correct mechanism, not
      // something this edit needs to know about (see CLAUDE.md's put_show
      // gotcha note). A plain PUT is all this cell needs to do.
      edit: {
        type: 'date',
        value: (show) => show.date,
        save: async (show, next) => {
          await api.put(`/shows/${show.show_id}`, { date: next })
          fetchShows()
        },
      },
    },
    {
      key: 'name',
      label: 'Show',
      className: 'min-w-[160px]',
      sortable: true,
      render: (show) => (
        <span className="flex items-center gap-2">
          <span className="text-pine-100 text-sm font-medium">{show.name}</span>
          {show.archived && (
            <span className="rounded-full bg-pine-700/60 text-pine-300 text-[10px] px-1.5 py-0.5 leading-none">
              Archived
            </span>
          )}
        </span>
      ),
      edit: {
        type: 'text',
        value: (show) => show.name,
        save: async (show, next) => {
          await api.put(`/shows/${show.show_id}`, { name: next })
          fetchShows()
        },
      },
    },
    {
      key: 'venue',
      label: 'Venue',
      sortable: true,
      render: (show) => (
        <span className="text-xs text-pine-300">{show.venue || '—'}</span>
      ),
      edit: {
        type: 'text',
        value: (show) => show.venue ?? '',
        save: async (show, next) => {
          await api.put(`/shows/${show.show_id}`, { venue: next || null })
          fetchShows()
        },
      },
    },
    {
      key: 'city',
      label: 'City',
      sortable: true,
      render: (show) => (
        <span className="text-xs text-pine-300">{show.city || '—'}</span>
      ),
      edit: {
        type: 'text',
        value: (show) => show.city ?? '',
        save: async (show, next) => {
          await api.put(`/shows/${show.show_id}`, { city: next || null })
          fetchShows()
        },
      },
    },
    {
      key: 'sales_goal',
      label: 'Goal',
      className: 'text-right',
      sortable: true,
      render: (show) => <PriceDisplay value={show.sales_goal} className="text-xs" />,
      edit: {
        type: 'money',
        value: (show) => show.sales_goal ?? '',
        save: async (show, next) => {
          await api.put(`/shows/${show.show_id}`, { sales_goal: next || null })
          fetchShows()
        },
      },
    },
    {
      key: '_actions',
      label: '',
      className: 'w-20',
      render: (show) => (
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); openEditForm(show) }}
            className="p-1 rounded text-pine-400 hover:text-pine-200 transition-colors"
            aria-label={`Edit ${show.name}`}
          >
            <Edit3 size={14} />
          </button>
          {show.archived ? (
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); handleUnarchive(show) }}
              className="p-1 rounded text-pine-400 hover:text-mint transition-colors"
              aria-label={`Unarchive ${show.name}`}
            >
              <ArchiveRestore size={14} />
            </button>
          ) : (
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); setArchiveTarget(show) }}
              className="p-1 rounded text-pine-400 hover:text-red-400 transition-colors"
              aria-label={`Archive ${show.name}`}
            >
              <Archive size={14} />
            </button>
          )}
        </div>
      ),
    },
  ]

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="p-6 lg:p-8">
      <header className="mb-6">
        <span className="font-mono text-[11px] uppercase tracking-[0.22em] text-mint/70">
          Admin
        </span>
        <h1 className="text-xl font-semibold text-pine-100">Shows</h1>
      </header>

      <div className="flex items-center justify-between gap-3 mb-4">
        <label
          htmlFor="include-archived"
          className="inline-flex items-center gap-2 text-xs text-pine-300 cursor-pointer"
        >
          <input
            id="include-archived"
            type="checkbox"
            checked={includeArchived}
            onChange={(e) => setIncludeArchived(e.target.checked)}
            className="accent-mint"
          />
          Show archived
        </label>
        <button
          type="button"
          onClick={openCreateForm}
          className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium bg-mint/15 text-mint border border-mint/30 hover:bg-mint/25 transition-colors"
        >
          <Plus size={14} />
          New Show
        </button>
      </div>

      <DataTable
        columns={columns}
        data={shows}
        keyField="show_id"
        loading={loading}
        emptyMessage="No shows yet"
        sortKey={sortKey}
        sortDir={sortDir}
        onSort={handleSort}
      />

      {/* Create/Edit modal */}
      {formOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="vault-panel rounded-xl p-6 w-full max-w-md mx-4">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-semibold text-pine-100">
                {editing ? 'Edit Show' : 'New Show'}
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
              <Field id="show-name" label="Name *">
                <input
                  id="show-name"
                  type="text"
                  value={formName}
                  onChange={(e) => setFormName(e.target.value)}
                  className="vault-field w-full px-3 py-2 rounded-lg text-sm"
                  placeholder="Portland Card Show"
                />
              </Field>
              <Field id="show-date" label="Date *">
                <input
                  id="show-date"
                  type="date"
                  value={formDate}
                  onChange={(e) => setFormDate(e.target.value)}
                  className="vault-field w-full px-3 py-2 rounded-lg text-sm font-mono"
                />
              </Field>
              <Field id="show-venue" label="Venue">
                <input
                  id="show-venue"
                  type="text"
                  value={formVenue}
                  onChange={(e) => setFormVenue(e.target.value)}
                  className="vault-field w-full px-3 py-2 rounded-lg text-sm"
                  placeholder="Lloyd Center"
                />
              </Field>
              <Field id="show-city" label="City">
                <input
                  id="show-city"
                  type="text"
                  value={formCity}
                  onChange={(e) => setFormCity(e.target.value)}
                  className="vault-field w-full px-3 py-2 rounded-lg text-sm"
                  placeholder="Portland, OR"
                />
              </Field>
              <div className="grid grid-cols-2 gap-3">
                <Field id="show-goal" label="Sales Goal">
                  <input
                    id="show-goal"
                    type="number"
                    step="0.01"
                    value={formSalesGoal}
                    onChange={(e) => setFormSalesGoal(e.target.value)}
                    className="vault-field w-full px-3 py-2 rounded-lg text-sm font-mono"
                    placeholder="$0.00"
                  />
                </Field>
                <Field id="show-cash" label="Cash at Start">
                  <input
                    id="show-cash"
                    type="number"
                    step="0.01"
                    value={formCashAtStart}
                    onChange={(e) => setFormCashAtStart(e.target.value)}
                    className="vault-field w-full px-3 py-2 rounded-lg text-sm font-mono"
                    placeholder="$0.00"
                  />
                </Field>
              </div>
              <Field id="show-notes" label="Notes">
                <textarea
                  id="show-notes"
                  value={formNotes}
                  onChange={(e) => setFormNotes(e.target.value)}
                  rows={2}
                  className="vault-field w-full px-3 py-2 rounded-lg text-sm resize-none"
                  placeholder="Anything worth remembering about this show…"
                />
              </Field>
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
                disabled={!formName.trim() || !formDate || saving}
                className="inline-flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-medium bg-mint/15 text-mint border border-mint/30 hover:bg-mint/25 disabled:opacity-40 transition-colors"
              >
                <Check size={13} />
                {saving ? 'Saving…' : editing ? 'Update' : 'Create'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Archive confirmation. Worded as reversible on purpose — the whole
          reason this is an archive and not a delete is that a mis-typed show
          with real transactions behind it stays recoverable. */}
      <ConfirmDialog
        open={!!archiveTarget}
        title="Archive Show"
        description={`"${archiveTarget?.name}" will be hidden from the show list. Nothing is deleted — its transactions and analytics stay intact, and you can restore it from "Show archived".`}
        confirmLabel="Archive"
        variant="danger"
        loading={archiving}
        onConfirm={handleArchive}
        onCancel={() => setArchiveTarget(null)}
      />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

function Field({
  id,
  label,
  children,
}: {
  id: string
  label: string
  children: React.ReactNode
}) {
  return (
    <div>
      <label htmlFor={id} className="block text-[11px] text-pine-400 mb-1">
        {label}
      </label>
      {children}
    </div>
  )
}
