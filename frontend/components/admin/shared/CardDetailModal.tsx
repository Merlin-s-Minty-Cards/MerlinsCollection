'use client'

import { useCallback, useEffect, useState } from 'react'
import { X, Pencil, Check, XCircle, Flag, Undo2, Lock } from 'lucide-react'
import { useAdminApi, AdminApiError } from '@/lib/admin-api'
import { clearTriageBody, sendToTriageBody } from '@/lib/triage'
import { CONDITION_OPTIONS, parseCondition, formatCondition } from '@/lib/constants'
import { useCardImages } from '@/lib/use-card-images'
import { useLocations } from '@/lib/use-locations'
import { useCosigners } from '@/lib/use-cosigners'
import PriceDisplay from './PriceDisplay'
import PriceChart from './PriceChart'
import HandValuedBadge from './HandValuedBadge'
import CosignorPicker from './CosignorPicker'
import MoneyInput from './MoneyInput'
import { isHandValued } from '@/lib/valuation'
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
  // Same id->name lookup the inventory table already uses (`ctx.consignorName`
  // in admin-inventory-columns.tsx) — the read-only Consignor row below used to
  // render the raw `consignor_id`, an opaque ULID no admin can read at a glance.
  const { options: cosignorOptions } = useCosigners()
  const consignorName = useCallback(
    (consignorId: string | undefined | null) =>
      cosignorOptions.find((o) => o.value === consignorId)?.label,
    [cosignorOptions],
  )
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
  // Send to Vault (RFC 0022 T7). `vaultPanel` is the confirm step shown ONLY
  // when already in the vault ("In Vault" -> offer to return to available);
  // sending TO the vault has no note to type, so that click writes directly,
  // matching the RFC's "one button, nothing else" scope. `vaultUndo` holds
  // the PREVIOUS status to restore, or `null` when no undo toast is showing.
  const [vaultPanel, setVaultPanel] = useState(false)
  const [vaultUndo, setVaultUndo] = useState<string | null>(null)
  // Consignment assign/unassign (RFC 0012 C3). `consignorPanel` is the
  // inline assign form, matching `triagePanel`'s disclosure pattern.
  const [consignorPanel, setConsignorPanel] = useState(false)
  const [pendingConsignorId, setPendingConsignorId] = useState<string | null>(null)
  const [consignorSaving, setConsignorSaving] = useState(false)
  const [consignorError, setConsignorError] = useState<string | null>(null)
  // Collapsed "advanced" overrides (RFC 0012 §C.2) — both optional, both
  // left out of the link body entirely when blank so the server's own
  // defaults (from the consignor's `payout_percent`) still apply.
  // `splitPercentAdvanced` gates the disclosure itself.
  const [splitPercentAdvanced, setSplitPercentAdvanced] = useState(false)
  const [splitPercentInput, setSplitPercentInput] = useState('')
  const [minimumPriceInput, setMinimumPriceInput] = useState('')
  const [minimumPriceParsed, setMinimumPriceParsed] = useState<number | null>(null)
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
    setConsignorPanel(false)
    setPendingConsignorId(null)
    setConsignorError(null)
    setSplitPercentAdvanced(false)
    setSplitPercentInput('')
    setMinimumPriceInput('')
    setMinimumPriceParsed(null)
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

  // Send to Vault (RFC 0022 T7): PUT { status } through the same partial-
  // update endpoint every other write here uses — no new endpoint. The
  // SERVER's `status` is the single answer once the response lands (mirrors
  // `writeTriage`'s own comment above): `shown`/`inVault` below are derived
  // from `current`, never a local optimistic flag that could disagree.
  const writeVault = useCallback(
    async (nextStatus: string, previousStatus: string | null) => {
      if (!item) return
      setSaving(true)
      setError(null)
      try {
        const updated = asItem(await api.put(`/inventory/${item.item_id}`, { status: nextStatus }))
        if (updated) setCurrent(updated)
        setVaultPanel(false)
        setVaultUndo(previousStatus)
        onUpdated?.(updated ?? undefined)
      } catch (err) {
        setError(err instanceof AdminApiError ? (err.detail ?? 'Update failed') : 'Update failed')
      } finally {
        setSaving(false)
      }
    },
    [api, item, onUpdated],
  )

  // Consignment assign/unassign (RFC 0012 C3). Declared here, alongside the
  // other write handlers and above the early `return null` below, so the
  // Rules of Hooks are not broken — the derived `consignment` read-only
  // object (used by the render section further down) is computed AFTER that
  // early return, so `unassignConsignor` reads `shown.consignment` directly
  // (the same source that local is derived from) rather than closing over
  // that later local. Neither endpoint returns a full item (see the module
  // docstring on `onUpdated`), so both call `onUpdated()` with no argument on
  // success — a refetch is the parent's job, the same "something changed,
  // but I cannot tell you what" shape.
  const assignConsignor = useCallback(async () => {
    if (!item || !pendingConsignorId) return
    setConsignorSaving(true)
    setConsignorError(null)
    try {
      // Both overrides are OPTIONAL and left out of the body entirely when
      // blank — `cosigners.py:221` defaults `split_percent` from the
      // consignor's own `payout_percent` and treats an absent
      // `minimum_price` as no override, so omitting the key (rather than
      // sending an empty string) is what lets those server-side defaults
      // still apply.
      const payload: Record<string, unknown> = { item_ids: [item.item_id] }
      const trimmedSplit = splitPercentInput.trim()
      if (trimmedSplit !== '') {
        // The admin types a PERCENT (e.g. `20` for 20%), matching
        // cosigners/page.tsx:251's convention exactly — divide by 100 before
        // sending. `split_percent` is a bounded percent, not money (no
        // thousands separator is possible), so a plain numeric parse with an
        // explicit range check is correct here, not MoneyInput/parseMoney.
        const splitPercentTyped = Number(trimmedSplit)
        if (!Number.isFinite(splitPercentTyped) || splitPercentTyped < 0 || splitPercentTyped > 100) {
          setConsignorError('Split % must be a number between 0 and 100.')
          setConsignorSaving(false)
          return
        }
        payload.split_percent = splitPercentTyped / 100
      }
      // `!== null`, never falsiness: `parseMoney('0')` is `0`, and a
      // legitimate $0 minimum price is a real answer a consignor can set.
      if (minimumPriceParsed !== null) payload.minimum_price = String(minimumPriceParsed)
      await api.post(`/cosigners/${pendingConsignorId}/link`, payload)
      setConsignorPanel(false)
      setPendingConsignorId(null)
      setSplitPercentAdvanced(false)
      setSplitPercentInput('')
      setMinimumPriceInput('')
      setMinimumPriceParsed(null)
      onUpdated?.()
    } catch (e) {
      setConsignorError(e instanceof AdminApiError ? e.message : 'Could not assign consignor.')
    } finally {
      setConsignorSaving(false)
    }
  }, [api, item, pendingConsignorId, splitPercentInput, minimumPriceParsed, onUpdated])

  const unassignConsignor = useCallback(async () => {
    const shownConsignment =
      shown?.consignment && typeof shown.consignment === 'object'
        ? (shown.consignment as Record<string, unknown>)
        : null
    if (!item || !shownConsignment) return
    setConsignorSaving(true)
    setConsignorError(null)
    try {
      await api.del(`/cosigners/${String(shownConsignment.consignor_id)}/assets/${item.item_id}`)
      onUpdated?.()
    } catch (e) {
      setConsignorError(e instanceof AdminApiError ? e.message : 'Could not unassign consignor.')
    } finally {
      setConsignorSaving(false)
    }
  }, [api, item, shown, onUpdated])

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
  // Same derivation rule as `flagged`: the SERVER's status is the answer,
  // never a local flag the header could disagree with.
  const inVault = shown.status === 'on_hold'

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
        // Wider than it was, and wider again on a large display (RFC 0010 T6).
        // `max-w-4xl` was 896px however big the screen, so zooming in shrank the
        // available CSS pixels without the modal ever getting proportionally
        // more room to give back.
        className="relative w-full max-w-6xl xl:max-w-7xl h-[92vh] vault-panel rounded-2xl flex flex-col overflow-hidden border border-pine-700/50 shadow-2xl mx-4"
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
            {/* Send to Vault (RFC 0022 T7) — same reach as Send to Triage,
                the five pages that mount this modal. "In Vault" offers to
                return the item to available rather than silently re-writing
                on_hold, mirroring the Triage button's own no-op-reads-broken
                reasoning. */}
            {inVault ? (
              <button
                type="button"
                onClick={() => setVaultPanel((open) => !open)}
                disabled={saving}
                className="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-medium
                           text-sky-300 bg-sky-400/10 border border-sky-400/30
                           hover:bg-sky-400/20 transition-colors disabled:opacity-50"
              >
                <Lock size={12} /> In Vault
              </button>
            ) : (
              <button
                type="button"
                onClick={() => writeVault('on_hold', String(shown.status ?? ''))}
                disabled={saving}
                className="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-medium
                           text-pine-300 border border-pine-700/60 hover:text-sky-300
                           hover:border-sky-400/40 transition-colors disabled:opacity-50"
              >
                <Lock size={12} /> Send to Vault
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

        {/* Vault panel — the confirm step for returning an on_hold item to
            available. Sending TO the vault has no note to type, so it writes
            directly from the header button above with no panel at all. */}
        {vaultPanel && inVault && (
          <div className="border-b border-pine-700/40 bg-pine-900/60 px-5 py-3 flex items-center justify-between gap-3">
            <p className="text-[11px] text-pine-400">In Vault (on hold).</p>
            <button
              type="button"
              onClick={() => writeVault('available', null)}
              disabled={saving}
              className="px-2.5 py-1 rounded-md text-[11px] font-medium text-mint
                         border border-mint/30 hover:bg-mint/10 disabled:opacity-50"
            >
              Return to available
            </button>
          </div>
        )}

        {/* Undo — same affordance as the Triage row action: a mis-click on
            Send to Vault pulls a card out of customer-visible stock, and this
            is the cheap way back without a confirm dialog in the way. */}
        {vaultUndo !== null && (
          <div
            role="status"
            className="flex items-center justify-between gap-3 border-b border-sky-400/20
                       bg-sky-400/10 px-5 py-2 text-[11px] text-pine-100"
          >
            <span>Sent to Vault.</span>
            <button
              type="button"
              onClick={() => writeVault(vaultUndo, null)}
              disabled={saving}
              className="flex items-center gap-1 text-mint hover:text-mint/80 disabled:opacity-50"
            >
              <Undo2 size={12} /> Undo
            </button>
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
          {/* Left: Large Card Image
              Bounded and SHRINKABLE (RFC 0010 T6). It was `flex-shrink-0` at
              `md:h-full`, so a 5:7 card claimed ~0.71 x 90vh of width and never
              yielded any of it — the details column got whatever was left, which
              is the owner's "shoves the text to the side".
              The `min()` is what behaves at both extremes: a percentage alone
              lets the image grow without limit on a wide display, a rem cap
              alone lets it dominate a narrow one. */}
          {/* `shrink-0 md:shrink` and not a bare removal: below `md` this is a
              COLUMN, where shrinking squashes the art vertically on a short
              viewport — a layout that was never the bug. It yields only in the
              side-by-side layout, which is the one being fixed. */}
          <div className="shrink-0 md:shrink flex items-center justify-center min-w-0 md:h-full md:max-w-[min(34%,20rem)]">
            {imageUrl ? (
              <img
                src={imageUrl}
                alt={adminItemName(shown as Parameters<typeof adminItemName>[0], 'Card')}
                // `max-w-full` is what makes the column's cap actually bite —
                // `w-auto` off `h-full` would otherwise overflow it. `max-h-full`
                // stops a tall image defeating the cap the other way.
                className="h-64 md:h-full w-auto max-w-full max-h-full object-contain rounded-xl shadow-lg"
              />
            ) : (
              // Not <CardImage alt="No image" />: that component always labels
              // its fallback "No image for {alt}", which is meant for list rows
              // that need to say which card is missing an image. The detail
              // modal already names the card in its header, so its own fallback
              // is labeled exactly "No image".
              // Sized exactly like the real image rather than pinned at a fixed
              // w-72 (RFC 0010 T6): a placeholder that cannot shrink makes the
              // layout correct only for cards that HAVE art — and the unlinked
              // cards most likely to be opened for repair are the ones that
              // don't. `aspect-[5/7]` keeps real card proportions off the height.
              <div
                className="h-64 md:h-full w-auto aspect-[5/7] max-w-full max-h-full rounded-xl bg-pine-800/60 border border-pine-700/40 flex items-center justify-center"
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
              {/* RFC 0010 T16 — the marker sits with the Pricing rows, not in
                  the header, because it is a claim about THESE numbers: on an
                  unlinked item they are a person's judgement no sync will
                  revisit, on a linked one they are a provider figure the next
                  sync overwrites. Identical-looking numbers meaning opposite
                  things is what makes an admin stop trusting the panel. */}
              <div className="flex flex-wrap items-center gap-2 mb-2">
                <h3 className="text-[11px] font-semibold uppercase tracking-wider text-pine-400">
                  {name}
                </h3>
                {name === 'Pricing' && isHandValued(shown) && (
                  <HandValuedBadge explain />
                )}
              </div>
              {/* CONTAINER-driven, not viewport-driven (RFC 0010 T6).
                  `sm:grid-cols-2` keyed off the viewport, so the grid stayed
                  two-up however narrow this COLUMN was squeezed — and zoom
                  changes the container without changing the breakpoint the way
                  you would expect, so no `sm:`/`md:` variant can fix it.
                  auto-fit collapses to one column whenever a cell would be
                  under 17rem, at any zoom, with nothing to tune.
                  The inner `min()` is load-bearing: a bare `minmax(17rem,1fr)`
                  forces a 17rem track even when the container is narrower than
                  17rem, which overflows horizontally — worse than the squeeze
                  this replaces. Tailwind container queries would express this
                  more directly but the plugin is not installed (tailwind 3.4,
                  `plugins: []`). */}
              <div className="grid grid-cols-[repeat(auto-fit,minmax(min(17rem,100%),1fr))] gap-2">
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
                    // `flex-wrap` is how the value STACKS under its label in a
                    // cramped cell without a container query: paired with the
                    // editor's `min-w-[…]` floor below, it drops to its own line
                    // exactly when it no longer fits beside the label — which is
                    // the difference between a usable input and the owner's
                    // "characters go into the factory sealed label" (the input
                    // never moved; it was crushed to near-zero width).
                    //
                    // `col-span-full`, NOT `sm:col-span-2`: viewport-keyed like
                    // the grid was, and on a grid that has collapsed to one
                    // column a span of 2 creates an IMPLICIT second column —
                    // breaking the exact narrow case this task exists to fix.
                    <div
                      key={field.key}
                      className={`flex flex-wrap gap-2 px-3 py-2 rounded-lg bg-pine-800/30 border border-pine-700/20 ${
                        field.type === 'textarea'
                          ? 'col-span-full flex-col items-stretch'
                          : 'items-center'
                      }`}
                    >
                      <span className={`text-[10px] text-pine-500 uppercase tracking-wider flex-shrink-0 ${
                        field.type === 'textarea' ? '' : 'w-24'
                      }`}>
                        {field.label}
                      </span>
                      {isEditing ? (
                        // A FLOOR, not `min-w-0`: an editor allowed to shrink to
                        // nothing is the reported bug. At 8rem the input is
                        // still readable, and the cell's `flex-wrap` turns that
                        // floor into a stack rather than an overflow. The inner
                        // `min()` keeps it honest if the cell itself is under
                        // 8rem, for the same reason the grid template has one.
                        <div className={`flex gap-1 flex-1 min-w-[min(8rem,100%)] ${
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

          {/* Consignment — read-only rows, plus assign/unassign controls (RFC
              0012 C3) calling the cosigner endpoints directly. See the note
              on `consignment` above for why the rows themselves stay
              read-only rather than routing through the generic field editor. */}
          <section>
            <h3 className="text-[11px] font-semibold uppercase tracking-wider text-pine-400 mb-2">
              Consignment
            </h3>
            {consignment ? (
              <>
                {/* Same container-driven template as the field sections above —
                    this grid had the identical viewport-keyed squeeze, and a
                    consigned card is someone else's money to read accurately. */}
                <div className="grid grid-cols-[repeat(auto-fit,minmax(min(17rem,100%),1fr))] gap-2">
                  {[
                    {
                      label: 'Consignor',
                      // Resolved to a NAME when the id is in the assignable
                      // list; falls back to the raw id (e.g. a since-archived
                      // consignor, invisible to useCosigners() by design) so
                      // the row is never blank for an item that IS consigned.
                      value: consignorName(consignment.consignor_id as string | undefined)
                        ?? String(consignment.consignor_id ?? '—'),
                    },
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
                <button
                  type="button"
                  disabled={consignorSaving}
                  onClick={unassignConsignor}
                  className="mt-2 text-[11px] text-red-400 hover:text-red-300 disabled:opacity-50"
                >
                  Unassign consignor
                </button>
              </>
            ) : consignorPanel ? (
              <div className="flex flex-col gap-2">
                <CosignorPicker value={pendingConsignorId} onChange={setPendingConsignorId} />
                {/* Collapsed "advanced" overrides (RFC 0012 §C.2) — the
                    endpoint already defaults split_percent from the
                    consignor's payout_percent and treats minimum_price as
                    optional, so these stay tucked away rather than demanded
                    up front. */}
                {splitPercentAdvanced ? (
                  <div className="flex flex-col gap-2 rounded-lg border border-pine-700/40 bg-pine-900/40 p-2">
                    <label
                      htmlFor="consignor-split-percent"
                      className="text-[10px] uppercase tracking-wider text-pine-500"
                    >
                      Split % override (percent, e.g. 20 for a 20% cut)
                    </label>
                    <input
                      id="consignor-split-percent"
                      type="text"
                      inputMode="decimal"
                      value={splitPercentInput}
                      onChange={(e) => setSplitPercentInput(e.target.value)}
                      placeholder="defaults from consignor"
                      className="vault-field w-full rounded-lg px-3 py-2 text-sm"
                    />
                    {/* Money, so it goes through MoneyInput per the repo's
                        money-input rule — never parseFloat, never
                        type="number". */}
                    <MoneyInput
                      label="Minimum price override"
                      value={minimumPriceInput}
                      onChange={(raw, parsed) => {
                        setMinimumPriceInput(raw)
                        setMinimumPriceParsed(parsed)
                      }}
                      placeholder="no override"
                    />
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={() => setSplitPercentAdvanced(true)}
                    className="self-start text-[11px] text-pine-400 hover:text-pine-100"
                  >
                    Advanced: split % / minimum price override
                  </button>
                )}
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    disabled={consignorSaving || !pendingConsignorId}
                    onClick={assignConsignor}
                    className="rounded-lg border border-mint/30 bg-mint/15 px-3 py-1.5 text-xs font-medium text-mint disabled:opacity-50"
                  >
                    Save
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setConsignorPanel(false)
                      setPendingConsignorId(null)
                      setConsignorError(null)
                      setSplitPercentAdvanced(false)
                      setSplitPercentInput('')
                      setMinimumPriceInput('')
                      setMinimumPriceParsed(null)
                    }}
                    className="text-[11px] text-pine-400 hover:text-pine-100"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => setConsignorPanel(true)}
                className="text-[11px] text-mint hover:text-mint/80"
              >
                Assign consignor
              </button>
            )}
            {/* Section-level, not nested in one branch of the ternary above —
                final-review Fix 3 (Important). `consignorError` is set on
                BOTH assign and unassign failure, but an unassign only fires
                from the "has consignment" branch, which used to have no
                error output at all: the DELETE would fail with nothing
                visible to the admin. Rendering it here means it shows
                regardless of which of the three branches is active. */}
            {consignorError && <p role="status" className="text-xs text-red-300">{consignorError}</p>}
          </section>

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
