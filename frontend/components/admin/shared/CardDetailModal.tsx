'use client'

import { useCallback, useEffect, useState } from 'react'
import { X, Pencil, Check, XCircle, Flag, Undo2 } from 'lucide-react'
import { useAdminApi, AdminApiError } from '@/lib/admin-api'
import { clearTriageBody, sendToTriageBody } from '@/lib/triage'
import { CONDITION_OPTIONS, parseCondition, formatCondition } from '@/lib/constants'
import { useCardImages } from '@/lib/use-card-images'
import { useLocations } from '@/lib/use-locations'
import PriceDisplay from './PriceDisplay'
import PriceChart from './PriceChart'
import { adminItemName } from '@/lib/admin-item-name'
import type { UpdatedItem } from '@/lib/item-update'

interface CardDetailModalProps {
  /** The item to display — null means modal is closed */
  item: Record<string, unknown> | null
  /** Close handler */
  onClose: () => void
  /**
   * Called after a successful edit, carrying the server's own copy of the item.
   *
   * The parameter is OPTIONAL on purpose (RFC 0010 T5): a parent that ignores
   * it keeps the whole-list refetch it had before and cannot break. It is also
   * absent when the response was not a recognisable item — see `asItem` — so
   * `onUpdated()` with no argument means "something changed, but I cannot tell
   * you what", which is exactly when a refetch is the right answer.
   */
  onUpdated?: (updated?: UpdatedItem) => void
}

/**
 * The server's copy of the item, or `null` if the response is not one.
 *
 * `PUT /admin/inventory/{item_id}` answers with the full updated item, and that
 * answer — not a local merge of the request payload — is what this modal
 * displays: the server normalises (`_split_combined_condition`, the
 * blank-to-None validators, the server-stamped `reviewed_at`), so a merge would
 * show a value the database does not hold, and the modal could claim a save
 * that did not land.
 *
 * Anything unrecognisable is DISCARDED rather than displayed. A `{}` — a 204, a
 * proxy, an older backend — assigned over the displayed item would erase
 * `item_id` and take the modal down with it.
 */
function asItem(response: unknown): UpdatedItem | null {
  if (!response || typeof response !== 'object') return null
  const record = response as UpdatedItem
  return typeof record.item_id === 'string' ? record : null
}

/** The four members of the backend's discriminated item union. */
type ItemKind = 'raw' | 'graded' | 'sealed' | 'bulk'

type FieldType =
  | 'text'
  | 'textarea'
  /** A dollar amount — displayed through PriceDisplay. */
  | 'number'
  /** A plain number that is NOT money. A PSA 9 must not render as "$9.00". */
  | 'decimal'
  | 'select'
  | 'checkbox'
  | 'date'

interface EditableField {
  key: string
  label: string
  type: FieldType
  /** Heading this field is grouped under; see SECTION_ORDER. */
  section: string
  /**
   * The item kinds this field exists on, mirroring the backend union. Absent
   * means every kind — i.e. the field lives on `_ItemBase`. Without this a
   * kind-specific input renders on an item that has no such field, and the
   * save silently no-ops (pydantic drops the extra key on merge).
   */
  kinds?: ItemKind[]
  /** Derived or immutable: displayed, but with no edit control. */
  readOnly?: true
}

const SECTION_ORDER = ['Identity', 'Pricing', 'Acquisition', 'Notes', 'Flags'] as const

/**
 * Every editable/displayable field, mirroring `_ItemBase` plus the kind-specific
 * members of `models/inventory.py`'s discriminated union.
 *
 * `consignment` is deliberately absent: it is a nested object, not a scalar, and
 * is rendered read-only by its own section below.
 */
const EDITABLE_FIELDS: EditableField[] = [
  // --- Identity -----------------------------------------------------------
  { key: 'item_id', label: 'Item ID', type: 'text', section: 'Identity', readOnly: true },
  // BOTH name fields are shown, deliberately. `display_name` is the fallback the
  // IMPORT materialized from the sheet's Name + Card # columns; `display_name_override`
  // is the admin's own correction and OUTRANKS it everywhere (customer tiles,
  // chat, and — since the T10 follow-up — every admin surface too). Editing
  // `display_name` on a catalog-matched item is a silent no-op, so an admin who
  // can only see that one row reasonably concludes the edit failed. Showing the
  // pair makes it obvious which is which and lets either be corrected.
  { key: 'display_name', label: 'Display Name (imported)', type: 'text', section: 'Identity', kinds: ['raw', 'graded'] },
  { key: 'display_name_override', label: 'Name Override (wins everywhere)', type: 'text', section: 'Identity' },
  { key: 'product_name', label: 'Product Name', type: 'text', section: 'Identity', kinds: ['sealed'] },
  { key: 'description', label: 'Description', type: 'text', section: 'Identity', kinds: ['bulk'] },
  { key: 'condition', label: 'Condition', type: 'select', section: 'Identity', kinds: ['raw'] },
  { key: 'finish', label: 'Finish', type: 'text', section: 'Identity', kinds: ['raw'] },
  { key: 'factory_sealed', label: 'Factory Sealed', type: 'checkbox', section: 'Identity', kinds: ['raw'] },
  { key: 'company', label: 'Grading Company', type: 'text', section: 'Identity', kinds: ['graded'] },
  { key: 'grade', label: 'Grade', type: 'decimal', section: 'Identity', kinds: ['graded'] },
  { key: 'cert_number', label: 'Cert Number', type: 'text', section: 'Identity', kinds: ['graded'] },
  { key: 'product_type', label: 'Product Type', type: 'text', section: 'Identity', kinds: ['sealed'] },
  { key: 'language', label: 'Language', type: 'text', section: 'Identity' },
  { key: 'status', label: 'Status', type: 'text', section: 'Identity' },
  { key: 'location', label: 'Location', type: 'select', section: 'Identity' },
  { key: 'tcg_url', label: 'TCGplayer Link', type: 'text', section: 'Identity' },
  { key: 'lineage_id', label: 'Lineage ID', type: 'text', section: 'Identity', readOnly: true },
  { key: 'predecessor_item_id', label: 'Predecessor', type: 'text', section: 'Identity', readOnly: true },

  // --- Pricing ------------------------------------------------------------
  { key: 'cost_basis', label: 'Price Paid', type: 'number', section: 'Pricing' },
  { key: 'market_value_at_purchase', label: 'Market at Purchase', type: 'number', section: 'Pricing' },
  { key: 'current_market_value', label: 'Market Value', type: 'number', section: 'Pricing' },
  { key: 'listed_price', label: 'Listed Price', type: 'number', section: 'Pricing' },
  { key: 'sticker_price', label: 'Sticker Price', type: 'number', section: 'Pricing' },
  { key: 'sticker_notes', label: 'Sticker Notes', type: 'text', section: 'Pricing' },

  // --- Acquisition --------------------------------------------------------
  { key: 'acquired_at', label: 'Acquired', type: 'date', section: 'Acquisition' },
  { key: 'acquired_show_id', label: 'Acquired Show', type: 'text', section: 'Acquisition' },

  // --- Notes --------------------------------------------------------------
  { key: 'notes', label: 'Notes', type: 'textarea', section: 'Notes' },
  { key: 'value_note', label: 'Value Note', type: 'textarea', section: 'Notes' },

  // --- Flags --------------------------------------------------------------
  { key: 'needs_review', label: 'Needs Review', type: 'checkbox', section: 'Flags' },
]

const FIELDS_BY_KEY = new Map(EDITABLE_FIELDS.map((f) => [f.key, f]))

/**
 * Shared modal for viewing/editing inventory item details with price history chart.
 *
 * Mounted by FIVE admin pages — inventory, outgoing (Prep Queue), sell,
 * show-prep and vault — NOT by "any admin page" as this docstring used to claim.
 * Buy, Trade, Market, History, Cosigners, Analytics and /admin/card/[id] each
 * have their own detail surface or none at all, so anything added here does not
 * reach them (see docs/plans/rfc-0008/follow-ups.md, T5).
 */
export default function CardDetailModal({
  item,
  onClose,
  onUpdated,
}: CardDetailModalProps) {
  const api = useAdminApi()
  const { options: locationOptions } = useLocations()
  const [editingField, setEditingField] = useState<string | null>(null)
  const [editValue, setEditValue] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Triage (T11). `triagePanel` is the inline note form — deliberately not a
  // window.prompt(): the note is free text an admin is encouraged to write, and
  // a native prompt cannot be styled, sized, or dismissed predictably.
  const [triagePanel, setTriagePanel] = useState(false)
  const [triageNote, setTriageNote] = useState('')
  const [triageUndo, setTriageUndo] = useState(false)
  /**
   * The item this modal DISPLAYS, which is not always the prop.
   *
   * Every parent passes an object out of its own list state, and the refetch
   * that `onUpdated` used to trigger replaced the array without replacing that
   * object — so an edited field kept its old value until the modal was closed
   * and reopened. The modal now owns its copy and replaces it with the server's
   * answer on every successful write.
   */
  const [current, setCurrent] = useState(item)
  /**
   * Guarded rather than trusted: the re-seed below is an effect, and effects run
   * AFTER the render that changed the prop, so without this an admin opening a
   * second card would see the first one's saved values for a frame.
   */
  const shown = current && current.item_id === item?.item_id ? current : item

  // Resolve this card's image independently of any page-level toggle —
  // the modal is a detail view, not a lazy list row, so it always wants
  // the real image if one exists (Round 6 audit item 1).
  const cardId = typeof shown?.card_id === 'string' ? shown.card_id : null
  const { getImageUrl } = useCardImages(cardId ? [cardId] : [])
  const imageUrl = cardId ? getImageUrl(cardId) : null

  // Re-seed on a NEW card, and reset the editing state with it.
  //
  // Keyed on `item_id` and nothing else, deliberately: re-seeding on every prop
  // change would let a stale parent object overwrite the fresh server value the
  // save just produced — the original bug, arriving through the other door.
  useEffect(() => {
    setCurrent(item)
    setEditingField(null)
    setEditValue('')
    setError(null)
    setTriagePanel(false)
    setTriageNote('')
    setTriageUndo(false)
    // `item` is read to re-seed FROM, but depending on it is precisely what must
    // not happen — that is the rule this effect exists to enforce.
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
    setEditValue(String(shown?.[field] ?? ''))
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
      // A checkbox backs a NON-optional bool on the model, and the update
      // endpoint merges the body straight into it — so the blank-is-null path
      // used for text would be a 422 there rather than a clear.
      const value =
        FIELDS_BY_KEY.get(editingField)?.type === 'checkbox'
          ? editValue === 'true'
          : editValue.trim() === ''
            ? null
            : editValue.trim()
      const payload: Record<string, unknown> = { [editingField]: value }
      if (typeof payload.condition === 'string') {
        const { condition, condition_modifier } = parseCondition(payload.condition)
        payload.condition = condition
        payload.condition_modifier = condition_modifier
      }
      const updated = asItem(await api.put(`/inventory/${item.item_id}`, payload))
      if (updated) setCurrent(updated)
      setEditingField(null)
      setEditValue('')
      onUpdated?.(updated ?? undefined)
    } catch (err) {
      setError(err instanceof AdminApiError ? (err.detail ?? 'Update failed') : 'Update failed')
    } finally {
      setSaving(false)
    }
  }, [api, editingField, editValue, item, onUpdated])

  const writeTriage = useCallback(
    // No `nextFlagged` parameter any more: `flagged` is DERIVED from the item on
    // screen, so a caller cannot tell the header one thing while the item says
    // another. The server's `needs_review` is the single answer.
    async (body: Record<string, unknown>, undoable: boolean) => {
      if (!item) return
      setSaving(true)
      setError(null)
      try {
        const updated = asItem(await api.put(`/inventory/${item.item_id}`, body))
        if (updated) setCurrent(updated)
        setTriagePanel(false)
        setTriageNote('')
        setTriageUndo(undoable)
        onUpdated?.(updated ?? undefined)
      } catch (err) {
        setError(err instanceof AdminApiError ? (err.detail ?? 'Update failed') : 'Update failed')
      } finally {
        setSaving(false)
      }
    },
    [api, item, onUpdated],
  )

  // `shown` is `item` whenever the two disagree, so the second half of this
  // guard only ever fires alongside the first — it is here to narrow the type.
  if (!item || !shown) return null

  const itemId = String(shown.item_id ?? '')
  // The override wins in the title too, so the header agrees with every list the
  // modal was opened from. `description` stays as a bulk-only last resort.
  const name =
    adminItemName(shown as Parameters<typeof adminItemName>[0], '') ||
    String(shown.description ?? '(unnamed)')
  const kind = String(shown.kind ?? '')
  // DERIVED, never separate state: two sources for "is this card flagged" is how
  // the header comes to disagree with the item it is describing.
  const flagged = Boolean(shown.needs_review)

  // Only the fields this kind actually has, per the backend union.
  const visibleFields = EDITABLE_FIELDS.filter(
    (f) => !f.kinds || f.kinds.includes(kind as ItemKind),
  )
  const sections = SECTION_ORDER.map((name) => ({
    name,
    fields: visibleFields.filter((f) => f.section === name),
  })).filter((s) => s.fields.length > 0)

  // Nested object, so it does not fit the flat field registry. Read-only for
  // now: the update endpoint replaces the whole object on merge, so a partial
  // edit would silently drop `paid_out` or rewrite `split_percent` — real money
  // on someone else's item. See docs/plans/rfc-0008/follow-ups.md.
  const consignment =
    shown.consignment && typeof shown.consignment === 'object'
      ? (shown.consignment as Record<string, unknown>)
      : null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={`Details for ${name}`}
    >
      <div
        className="relative w-full max-w-4xl h-[90vh] vault-panel rounded-2xl flex flex-col overflow-hidden border border-pine-700/50 shadow-2xl mx-4"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-pine-700/40 bg-pine-900/95 backdrop-blur px-5 py-4 rounded-t-2xl">
          <div className="min-w-0">
            <h2 className="text-base font-semibold text-pine-100 truncate">{name}</h2>
            <p className="text-[10px] text-pine-500 font-mono">{kind} &middot; {itemId}</p>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            {/* Send to Triage — the broadest reach available in one change:
                this modal is mounted by inventory, outgoing (Prep Queue), sell,
                show-prep and vault. An already-flagged item reads "In Triage"
                and offers to clear it rather than silently re-flagging, because
                a button that no-ops reads as a broken feature. */}
            {flagged ? (
              <button
                type="button"
                onClick={() => setTriagePanel((open) => !open)}
                disabled={saving}
                className="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-medium
                           text-amber-300 bg-amber-400/10 border border-amber-400/30
                           hover:bg-amber-400/20 transition-colors disabled:opacity-50"
              >
                <Flag size={12} /> In Triage
              </button>
            ) : (
              <button
                type="button"
                onClick={() => setTriagePanel((open) => !open)}
                disabled={saving}
                className="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-medium
                           text-pine-300 border border-pine-700/60 hover:text-amber-300
                           hover:border-amber-400/40 transition-colors disabled:opacity-50"
              >
                <Flag size={12} /> Send to Triage
              </button>
            )}
            <button
              type="button"
              onClick={onClose}
              className="p-1.5 rounded-md text-pine-400 hover:text-pine-200 hover:bg-pine-800 transition-colors"
              aria-label="Close modal"
            >
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Triage panel — note form when unflagged, clear action when flagged */}
        {triagePanel && (
          <div className="border-b border-pine-700/40 bg-pine-900/60 px-5 py-3 space-y-2">
            {flagged ? (
              <div className="flex items-center justify-between gap-3">
                <p className="text-[11px] text-pine-400">
                  {shown.review_reason
                    ? `In Triage — ${String(shown.review_reason)}`
                    : 'In Triage.'}
                </p>
                <button
                  type="button"
                  onClick={() => writeTriage(clearTriageBody(), false)}
                  disabled={saving}
                  className="px-2.5 py-1 rounded-md text-[11px] font-medium text-mint
                             border border-mint/30 hover:bg-mint/10 disabled:opacity-50"
                >
                  Clear review
                </button>
              </div>
            ) : (
              <>
                <label
                  htmlFor="triage-note"
                  className="block text-[10px] uppercase tracking-wider text-pine-500"
                >
                  Why does this need review? (optional)
                </label>
                <div className="flex gap-2">
                  <input
                    id="triage-note"
                    type="text"
                    value={triageNote}
                    onChange={(e) => setTriageNote(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') writeTriage(sendToTriageBody(triageNote), true)
                      // Stop the document-level Escape handler from closing the
                      // whole modal and discarding a typed note.
                      if (e.key === 'Escape') { e.stopPropagation(); setTriagePanel(false) }
                    }}
                    maxLength={500}
                    placeholder="e.g. set symbol looks wrong"
                    className="flex-1 min-w-0 bg-pine-900 border border-mint/30 rounded px-2 py-1
                               text-xs text-pine-100 focus:outline-none focus:border-mint/60"
                    autoFocus
                    disabled={saving}
                  />
                  <button
                    type="button"
                    onClick={() => writeTriage(sendToTriageBody(triageNote), true)}
                    disabled={saving}
                    className="px-3 py-1 rounded-md text-[11px] font-medium text-mint
                               border border-mint/30 hover:bg-mint/10 disabled:opacity-50"
                  >
                    Send
                  </button>
                </div>
              </>
            )}
          </div>
        )}

        {/* Undo — a misclick on a flag action is inevitable, and undo must clear
            the reason too or the item comes back unflagged still carrying the
            note that put it there. */}
        {triageUndo && (
          <div
            role="status"
            className="flex items-center justify-between gap-3 border-b border-amber-400/20
                       bg-amber-400/10 px-5 py-2 text-[11px] text-pine-100"
          >
            <span>Sent to Triage.</span>
            <button
              type="button"
              onClick={() => writeTriage(clearTriageBody(), false)}
              disabled={saving}
              className="flex items-center gap-1 text-mint hover:text-mint/80 disabled:opacity-50"
            >
              <Undo2 size={12} /> Undo
            </button>
          </div>
        )}

        <div className="flex-1 min-h-0 p-5 flex flex-col md:flex-row gap-6">
          {/* Left: Large Card Image */}
          <div className="flex-shrink-0 flex items-center justify-center md:h-full">
            {imageUrl ? (
              <img
                src={imageUrl}
                alt={adminItemName(shown as Parameters<typeof adminItemName>[0], 'Card')}
                className="h-64 md:h-full w-auto object-contain rounded-xl shadow-lg"
              />
            ) : (
              // Not <CardImage alt="No image" />: that component always labels
              // its fallback "No image for {alt}", which is meant for list rows
              // that need to say which card is missing an image. The detail
              // modal already names the card in its header, so its own fallback
              // is labeled exactly "No image".
              <div
                className="w-72 h-[25.75rem] rounded-xl bg-pine-800/60 border border-pine-700/40 flex items-center justify-center flex-shrink-0"
                aria-label="No image"
              >
                <svg
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  className="text-pine-600"
                >
                  <rect x="3" y="3" width="18" height="18" rx="2" />
                  <circle cx="8.5" cy="8.5" r="1.5" />
                  <path d="M21 15l-5-5L5 21" />
                </svg>
              </div>
            )}
          </div>

          {/* Right: Details */}
          <div className="flex-1 min-w-0 space-y-5 overflow-y-auto vault-scroll">
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
              costBasis={shown.cost_basis as string | undefined}
              acquiredAt={shown.acquired_at as string | undefined}
            />
          </section>

          {/* Editable Fields, grouped — the flat list is ~30 rows long */}
          {sections.map(({ name, fields }) => (
            <section key={name}>
              <h3 className="text-[11px] font-semibold uppercase tracking-wider text-pine-400 mb-2">
                {name}
              </h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {fields.map((field) => {
                  const value = shown[field.key]
                  const isEditing = editingField === field.key
                  const displayValue =
                    field.key === 'condition' && shown.condition != null
                      ? formatCondition(String(shown.condition), shown.condition_modifier as string | null | undefined)
                      : field.type === 'checkbox'
                        ? (value ? 'Yes' : 'No')
                        : value != null && String(value) !== ''
                          ? String(value)
                          : '—'

                  return (
                    <div
                      key={field.key}
                      className={`flex gap-2 px-3 py-2 rounded-lg bg-pine-800/30 border border-pine-700/20 ${
                        field.type === 'textarea'
                          ? 'sm:col-span-2 flex-col items-stretch'
                          : 'items-center'
                      }`}
                    >
                      <span className={`text-[10px] text-pine-500 uppercase tracking-wider flex-shrink-0 ${
                        field.type === 'textarea' ? '' : 'w-24'
                      }`}>
                        {field.label}
                      </span>
                      {isEditing ? (
                        <div className={`flex gap-1 flex-1 min-w-0 ${
                          field.type === 'textarea' ? 'items-start' : 'items-center'
                        }`}>
                          {field.type === 'select' && field.key === 'location' ? (
                            <select
                              value={editValue}
                              onChange={(e) => setEditValue(e.target.value)}
                              className="flex-1 min-w-0 bg-pine-900 border border-mint/30 rounded px-2 py-0.5 text-xs text-pine-100 focus:outline-none focus:border-mint/60"
                              autoFocus
                              disabled={saving}
                            >
                              {locationOptions.map((loc) => (
                                <option key={loc.value} value={loc.value}>{loc.label}</option>
                              ))}
                            </select>
                          ) : field.type === 'select' && field.key === 'condition' ? (
                            <select
                              value={editValue}
                              onChange={(e) => setEditValue(e.target.value)}
                              className="flex-1 min-w-0 bg-pine-900 border border-mint/30 rounded px-2 py-0.5 text-xs text-pine-100 focus:outline-none focus:border-mint/60"
                              autoFocus
                              disabled={saving}
                            >
                              {CONDITION_OPTIONS.map((c) => (
                                <option key={c} value={c}>{c}</option>
                              ))}
                            </select>
                          ) : field.type === 'textarea' ? (
                            // Deliberately no Enter-to-save: a note is multi-line
                            // free text, so Enter has to insert a newline. Save is
                            // the check button (issue #13 — the "tiny box" report).
                            <textarea
                              rows={4}
                              value={editValue}
                              onChange={(e) => setEditValue(e.target.value)}
                              // stopPropagation, or the event also reaches the
                              // document-level Escape handler and closes the WHOLE
                              // modal — discarding four rows of typed notes when
                              // the admin only meant to cancel this one field.
                              onKeyDown={(e) => {
                                if (e.key === 'Escape') { e.stopPropagation(); cancelEdit() }
                              }}
                              className="flex-1 min-w-0 bg-pine-900 border border-mint/30 rounded px-2 py-1 text-xs text-pine-100 focus:outline-none focus:border-mint/60 resize-y"
                              autoFocus
                              disabled={saving}
                            />
                          ) : field.type === 'checkbox' ? (
                            <input
                              type="checkbox"
                              checked={editValue === 'true'}
                              onChange={(e) => setEditValue(String(e.target.checked))}
                              className="h-3.5 w-3.5 accent-mint bg-pine-900 border border-mint/30 rounded"
                              autoFocus
                              disabled={saving}
                            />
                          ) : (
                            <input
                              type={
                                field.type === 'number' || field.type === 'decimal'
                                  ? 'number'
                                  : field.type === 'date'
                                    ? 'date'
                                    : 'text'
                              }
                              // Without this the browser's default step of 1
                              // marks every decimal (a $12.50 basis, a PSA 9.5)
                              // as a step mismatch.
                              step={
                                field.type === 'number' || field.type === 'decimal'
                                  ? 'any'
                                  : undefined
                              }
                              value={editValue}
                              onChange={(e) => setEditValue(e.target.value)}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') saveEdit()
                                // stopPropagation: without it the document-level
                                // Escape handler fires too and closes the modal
                                // as well as cancelling the field.
                                if (e.key === 'Escape') { e.stopPropagation(); cancelEdit() }
                              }}
                              maxLength={field.key === 'sticker_notes' ? 200 : undefined}
                              className="flex-1 min-w-0 bg-pine-900 border border-mint/30 rounded px-2 py-0.5 text-xs text-pine-100 focus:outline-none focus:border-mint/60"
                              autoFocus
                              disabled={saving}
                            />
                          )}
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
                        <div className="flex items-start gap-1 flex-1 min-w-0">
                          <span
                            className={`text-xs text-pine-200 flex-1 ${
                              field.type === 'textarea' ? 'whitespace-pre-wrap break-words' : 'truncate'
                            }`}
                          >
                            {field.type === 'number' && value != null ? (
                              <PriceDisplay value={displayValue} className="text-xs text-pine-200 font-mono" />
                            ) : (
                              displayValue
                            )}
                          </span>
                          {field.readOnly ? null : (
                            <button
                              type="button"
                              onClick={() => startEdit(field.key)}
                              className="p-0.5 text-pine-600 hover:text-pine-300 transition-opacity flex-shrink-0"
                              aria-label={`Edit ${field.label}`}
                            >
                              <Pencil size={11} />
                            </button>
                          )}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            </section>
          ))}

          {/* Consignment — read-only, see the note on `consignment` above */}
          {consignment && (
            <section>
              <h3 className="text-[11px] font-semibold uppercase tracking-wider text-pine-400 mb-2">
                Consignment
              </h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {[
                  { label: 'Consignor', value: String(consignment.consignor_id ?? '—') },
                  {
                    label: 'Our Cut',
                    // Stored as a 0-1 fraction ("0.05 = a 5% cut" per
                    // ConsignmentTerms), so render it as the percent an admin reads.
                    // `!= null` first: Number(null) is 0, which would render a
                    // missing split as a real "0.0%" cut.
                    value:
                      consignment.split_percent != null &&
                      Number.isFinite(Number(consignment.split_percent))
                        ? `${(Number(consignment.split_percent) * 100).toFixed(1)}%`
                        : '—',
                  },
                  {
                    label: 'Minimum Price',
                    value: consignment.minimum_price != null ? String(consignment.minimum_price) : '—',
                  },
                  { label: 'Paid Out', value: consignment.paid_out ? 'Yes' : 'No' },
                ].map(({ label, value }) => (
                  <div
                    key={label}
                    className="flex items-center gap-2 px-3 py-2 rounded-lg bg-pine-800/30 border border-pine-700/20"
                  >
                    <span className="text-[10px] text-pine-500 uppercase tracking-wider w-24 flex-shrink-0">
                      {label}
                    </span>
                    <span className="text-xs text-pine-200 truncate flex-1">{value}</span>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* Quick Info */}
          <section className="flex flex-wrap gap-3 text-[10px] text-pine-500 border-t border-pine-700/30 pt-3">
            {shown.card_id ? (
              <span>Card: <span className="text-pine-300 font-mono">{String(shown.card_id)}</span></span>
            ) : null}
            {/* `acquired_at` and the grading trio used to be repeated here; they
                now have real, editable rows in the sections above. */}
            <a
              href={
                shown.tcg_url
                  ? String(shown.tcg_url)
                  : `https://www.tcgplayer.com/search/pokemon/product?q=${encodeURIComponent(name)}&view=grid`
              }
              target="_blank"
              rel="noopener noreferrer"
              className="text-blue-400 hover:text-blue-300"
            >
              TCGplayer {shown.tcg_url ? 'Link' : 'Search'} ↗
            </a>
          </section>
          </div>
        </div>
      </div>
    </div>
  )
}
