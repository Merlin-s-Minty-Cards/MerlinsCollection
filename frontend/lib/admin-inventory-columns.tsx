/**
 * The admin inventory table's column registry — RFC 0008 §F5 (T6).
 *
 * The page used to build a hardcoded `Column<InventoryItem>[]` inline, which
 * meant the only fields an admin could ever see were the nine someone picked
 * once, and the filter panel offered fields (`card_number`, `artist`,
 * `set_name`) with no relationship at all to what was on screen.
 *
 * This module declares BOTH halves of that relationship in one place: every
 * displayable column (the superset of the backend's discriminated item union,
 * `models/inventory.py`), and every filter, each pointing at the column it
 * follows. `isFilterVisible` is the whole of the owner's Q9 decision — filters
 * follow the visible columns, plus a "show all filters" escape hatch.
 *
 * ## Two rules that are easy to break by accident
 *
 * 1. **`key` is persisted.** It ends up in an admin's `localStorage` under
 *    `COLUMN_STORAGE_KEY`. Renaming one silently retires that column for
 *    everyone who had it on. Bump the version in the storage key instead.
 * 2. **Registry order IS render order.** `toDataTableColumns` filters this
 *    array; it never reads the stored order. That is what stops columns
 *    rearranging themselves according to the sequence the boxes were ticked in.
 */

import type { ReactNode } from 'react'
import { Trash2 } from 'lucide-react'
import type { Column, EditSpec } from '@/components/admin/shared/DataTable'
import type { InlineEditCellType, SelectOption } from '@/components/admin/shared/InlineEditCell'
import CardImage, { TABLE_THUMB_SIZE, TABLE_THUMB_COLUMN } from '@/components/admin/shared/CardImage'
import StatusBadge from '@/components/admin/shared/StatusBadge'
import PriceDisplay from '@/components/admin/shared/PriceDisplay'
import OwnershipBadge from '@/components/admin/shared/OwnershipBadge'
import TriageRowAction from '@/components/admin/shared/TriageRowAction'
import type { TriageItem } from '@/lib/triage'
import { adminItemName } from '@/lib/admin-item-name'
import { CONDITION_OPTIONS as CONDITION_VALUES, formatCondition } from '@/lib/constants'
import { parseMoney } from '@/lib/money'

/** RFC 0022 — the `ItemStatus` values a status cell can be set to. */
const STATUS_OPTIONS: SelectOption[] = [
  { value: 'available', label: 'Available' },
  { value: 'sold', label: 'Sold' },
  { value: 'lost', label: 'Lost' },
  { value: 'on_hold', label: 'On Hold' },
  { value: 'consigned', label: 'Consigned' },
]

/** One inventory row as the admin search returns it (a full `model_dump`). */
export interface InventoryItem {
  item_id: string
  kind: string
  status: string
  card_id?: string
  display_name?: string
  condition_modifier?: string | null
  product_name?: string
  condition?: string
  location?: string
  cost_basis?: string
  current_market_value?: string
  sticker_price?: string
  sticker_notes?: string
  finish?: string
  language?: string
  notes?: string
  acquired_at?: string
  consignment?: Record<string, unknown> | null
  [key: string]: unknown
}

/**
 * Everything a cell needs from the page. This is why `render` takes two
 * arguments rather than the one a pure registry would: the Location and Sticker
 * cells are inline EDITORS, so they need the page's live edit state. Passing it
 * per-render (instead of closing over it in a factory) is what lets the column
 * array be rebuilt cheaply on every render — which it must be, or the editors
 * capture a stale `editValue`.
 */
export interface ColumnRenderContext {
  editingId: string | null
  editField: string | null
  editValue: string
  setEditValue: (value: string) => void
  startEdit: (item: InventoryItem, field: string) => void
  saveEdit: () => void
  cancelEdit: () => void
  locationOptions: { value: string; label: string }[]
  /** RFC 0022 T4a: `useShows()`'s options, for the `acquired_show_id` select. */
  showOptions?: { value: string; label: string }[]
  /** Mirrors `useCardImages().getImageUrl` exactly — it returns null, not undefined. */
  getImageUrl: (cardId?: string | null) => string | null
  onRefresh: () => void
  onDelete: (item: InventoryItem) => void
  /** `useCosigners()` id->name lookup. Undefined for an unassigned/unknown id. */
  consignorName: (consignorId: string | undefined | null) => string | undefined
  /**
   * RFC 0022 — the generic click-to-edit commit path every registry-driven
   * `edit` spec below calls: `PUT /admin/inventory/{id}` with `{[field]:
   * value}`, then the page's own refresh. Pages needing different behavior
   * on a specific column (Prep Queue's sticker_price patch-and-drop) override
   * that one column's `edit.save` after calling `toDataTableColumns` — this
   * default is what every OTHER column and every OTHER page gets for free.
   */
  saveField?: (item: InventoryItem, field: string, value: unknown) => Promise<void>
}

export interface InventoryColumnDef {
  /** Stable and PERSISTED — see the header note before renaming. */
  key: string
  /** Shown in the picker and as the table header. */
  label: string
  defaultVisible: boolean
  /** Backend `sort` support, per `_sort_admin_results`. */
  sortable?: boolean
  className?: string
  /** Always rendered, never offered in the picker (the row actions cell). */
  pinned?: boolean
  render: (item: InventoryItem, ctx: ColumnRenderContext) => ReactNode
  /**
   * Present ⇒ click-to-edit, built from `ctx` (so it can reach
   * `ctx.saveField`/option lists). Absent ⇒ `notEditable` is REQUIRED — the
   * totality test (T5) fails a column shipping neither, per CLAUDE.md's
   * "a parity test that diffs only key sets cannot catch an empty stub"
   * lesson: the reason string is what the test actually checks.
   */
  edit?: (ctx: ColumnRenderContext) => EditSpec<InventoryItem>
  /** Required when `edit` is absent. At least 10 characters — see above. */
  notEditable?: string
}

/** `''`/`null`/`undefined` all coerce to `null` on save — clearing a field is a real edit, not an error. Checkbox coerces to a real boolean. */
function coerceForSave(type: InlineEditCellType, raw: string): unknown {
  if (type === 'checkbox') return raw === 'true'
  return raw === '' ? null : raw
}

/** The common shape: read `item[field]` as a string, save through `ctx.saveField`. */
function fieldEdit(
  type: InlineEditCellType,
  field: string,
  options?: {
    options?: SelectOption[]
    undoLabel?: string
    value?: (item: InventoryItem) => string
  },
): (ctx: ColumnRenderContext) => EditSpec<InventoryItem> {
  return (ctx) => ({
    type,
    options: options?.options,
    value: options?.value ?? ((item) => {
      const v = item[field]
      return v == null ? '' : String(v)
    }),
    save: async (item, next) => {
      await ctx.saveField?.(item, field, coerceForSave(type, next))
    },
    undoLabel: options?.undoLabel,
  })
}

// --------------------------------------------------------------------------
// Cell helpers
// --------------------------------------------------------------------------

const EM_DASH = '—'

function text(value: unknown, className = 'text-xs text-pine-300'): ReactNode {
  const str = value == null || value === '' ? EM_DASH : String(value)
  return <span className={className}>{str}</span>
}

function money(value: unknown, className: string): ReactNode {
  return <PriceDisplay value={value as string | undefined} className={className} />
}

function yesNo(value: unknown): ReactNode {
  return <span className="text-xs text-pine-300">{value ? 'Yes' : 'No'}</span>
}

/** A long free-text field, clamped so one item's notes cannot own the row. */
function clamped(value: unknown): ReactNode {
  const str = value == null || value === '' ? EM_DASH : String(value)
  return (
    <span className="text-xs text-pine-300 truncate block max-w-[220px]" title={str}>
      {str}
    </span>
  )
}

// --------------------------------------------------------------------------
// The registry
// --------------------------------------------------------------------------

export const INVENTORY_COLUMNS: InventoryColumnDef[] = [
  {
    key: '_image',
    label: 'Image',
    defaultVisible: false,
    className: TABLE_THUMB_COLUMN,
    notEditable: 'Card art, resolved from card_id — not a stored value of its own.',
    render: (item, ctx) => (
      <CardImage
        imageUrl={ctx.getImageUrl(item.card_id)}
        alt={adminItemName(item, 'card')}
        size={TABLE_THUMB_SIZE}
      />
    ),
  },
  {
    key: 'display_name',
    label: 'Name',
    defaultVisible: true,
    sortable: true,
    className: 'min-w-[180px]',
    render: (item) => (
      <span className="text-pine-100 font-medium truncate block max-w-[260px]">
        {adminItemName(item)}
      </span>
    ),
    // Composite: falls back override -> display_name -> product_name via
    // adminItemName. Editing this cell would leave "which field did that
    // write?" ambiguous, and CLAUDE.md is explicit that display_name_override
    // is editable ONLY from Triage.
    notEditable: 'Composite name — edit display_name_override from the Triage page.',
  },
  {
    key: 'status',
    label: 'Status',
    defaultVisible: true,
    sortable: true,
    render: (item) => <StatusBadge status={item.status} />,
    edit: fieldEdit('select', 'status', { options: STATUS_OPTIONS, undoLabel: 'Status' }),
  },
  {
    key: 'kind',
    label: 'Kind',
    defaultVisible: true,
    sortable: true,
    render: (item) => <span className="text-xs capitalize text-pine-300">{item.kind}</span>,
    // The discriminated-union tag: raw/graded/sealed/bulk carry entirely
    // different required fields, so changing it in place is a data migration,
    // not an edit.
    notEditable: 'Changing kind would leave required fields for the new kind unset. Delete and re-add instead.',
  },
  {
    key: 'condition',
    label: 'Cond',
    defaultVisible: true,
    // Sorts by ORDINAL RANK on the backend (NM > LP+ > LP > LP- > MP > HP > DMG),
    // not alphabetically — which used to render an LP+ and an LP- identically.
    sortable: true,
    render: (item) => (
      // Joined with the modifier, not the bare tier: T2 went to real trouble
      // making the backend emit and filter LP+/LP-, and this table was the one
      // surface that still rendered an LP+ and an LP- card identically.
      <span className="text-xs font-mono text-pine-300">
        {item.condition ? formatCondition(item.condition, item.condition_modifier) : EM_DASH}
      </span>
    ),
    // The combined display string ("LP+") is what the backend's
    // `_split_combined_condition` expects under the `condition` key — it
    // expands it into condition + condition_modifier itself.
    edit: fieldEdit('select', 'condition', {
      options: CONDITION_VALUES.map((v) => ({ value: v, label: v })),
      value: (item) => (item.condition ? formatCondition(item.condition, item.condition_modifier) : ''),
    }),
  },
  {
    key: 'location',
    label: 'Location',
    defaultVisible: true,
    sortable: true,
    render: (item) => <span className="text-xs text-pine-300 capitalize">{item.location ?? EM_DASH}</span>,
    edit: (ctx) => ({
      type: 'select',
      options: ctx.locationOptions,
      value: (item) => item.location ?? '',
      save: async (item, next) => {
        await ctx.saveField?.(item, 'location', next || null)
      },
      undoLabel: 'Location',
    }),
  },
  {
    key: 'cost_basis',
    label: 'Price Paid',
    defaultVisible: true,
    sortable: true,
    className: 'text-right',
    render: (item) => money(item.cost_basis, 'text-xs text-pine-300'),
    edit: fieldEdit('money', 'cost_basis', { undoLabel: 'Cost basis' }),
  },
  {
    key: 'current_market_value',
    label: 'Market',
    defaultVisible: true,
    sortable: true,
    className: 'text-right',
    render: (item) => money(item.current_market_value, 'text-xs text-mint'),
    notEditable: 'Denormalized nightly by refresh_inventory_market_values; a hand edit is overwritten on the next run.',
  },
  {
    key: 'sticker_price',
    label: 'Sticker',
    defaultVisible: true,
    sortable: true,
    className: 'text-right',
    render: (item) => {
      const sticker = item.sticker_price as string | undefined
      const stickerNotes = item.sticker_notes as string | undefined
      return (
        <span className="text-xs text-amber-400/80 font-mono flex items-center gap-1 justify-end">
          {sticker ? `$${parseFloat(sticker).toFixed(2)}` : EM_DASH}
          {stickerNotes && <span className="text-[8px] text-pine-500" title={stickerNotes}>*</span>}
        </span>
      )
    },
    edit: fieldEdit('money', 'sticker_price', { undoLabel: 'Sticker price' }),
  },
  {
    key: 'consignment',
    label: 'Ownership',
    defaultVisible: true,
    // Sorts by PRESENCE on the backend — "consigned or owned" is the question this
    // column asks, and ConsignmentTerms is not a comparable value.
    sortable: true,
    render: (item) => <OwnershipBadge consigned={item.consignment != null} />,
    notEditable: 'Nested object; split % and consignor move together. Edit via the Cosigners link form or CardDetailModal.',
  },
  {
    key: 'consignor_name',
    label: 'Consignor',
    // Was `false` — which is also why the Consignor FILTER never appeared by
    // default: `isFilterVisible` gates a filter on its own column being
    // visible, so an off-by-default column silently hid a filter that
    // otherwise looked fully wired.
    defaultVisible: true,
    // Backend orders by the RESOLVED NAME via a router-supplied id->name map —
    // see services/inventory_sort.py's CONSIGNOR_NAME_FIELD docstring for why
    // this couldn't be a plain per-item extractor like every other column.
    sortable: true,
    render: (item, ctx) => {
      const id = (item.consignment as { consignor_id?: string } | null)?.consignor_id
      return text(ctx.consignorName(id))
    },
    // Same nested-object reason as `consignment` above — this column is a
    // resolved NAME, not a raw field, and reassigning the consignor without
    // touching split_percent would need a merge the backend's shallow-merge
    // PUT does not do.
    notEditable: 'Derived from consignment.consignor_id. Edit via the Cosigners link form or CardDetailModal.',
  },

  // --- Off by default: the fields that existed but were never displayable ---
  {
    key: 'needs_review',
    label: 'Review',
    defaultVisible: false,
    sortable: true,
    render: (item) => yesNo(item.needs_review),
    edit: fieldEdit('checkbox', 'needs_review'),
  },
  {
    key: 'review_reason', label: 'Review Reason', defaultVisible: false, sortable: true,
    render: (i) => clamped(i.review_reason),
    edit: fieldEdit('textarea', 'review_reason'),
  },
  {
    key: 'reviewed_at', label: 'Reviewed', defaultVisible: false, sortable: true,
    render: (i) => text(i.reviewed_at, 'text-xs font-mono text-pine-400'),
    notEditable: 'Server-stamped accountability field — a client claim about who reviewed this is not evidence.',
  },
  {
    key: 'card_id', label: 'Card ID', defaultVisible: false, sortable: true,
    render: (i) => text(i.card_id, 'text-xs font-mono text-pine-400'),
    notEditable: 'Re-pointing a card is a confirmed action with a before/after diff. Use Triage re-point.',
  },
  {
    key: 'language', label: 'Language', defaultVisible: false, sortable: true, render: (i) => text(i.language),
    edit: fieldEdit('select', 'language', { options: [{ value: 'EN', label: 'EN' }, { value: 'JP', label: 'JP' }] }),
  },
  {
    key: 'finish', label: 'Finish', defaultVisible: false, sortable: true, render: (i) => text(i.finish),
    edit: fieldEdit('select', 'finish', {
      options: [
        { value: 'normal', label: 'Normal' },
        { value: 'holofoil', label: 'Holofoil' },
        { value: 'reverseHolofoil', label: 'Reverse Holofoil' },
      ],
    }),
  },
  {
    key: 'factory_sealed', label: 'Factory Sealed', defaultVisible: false, sortable: true,
    render: (i) => yesNo(i.factory_sealed),
    edit: fieldEdit('checkbox', 'factory_sealed'),
  },
  {
    key: 'company', label: 'Grading Co.', defaultVisible: false, sortable: true, render: (i) => text(i.company),
    edit: fieldEdit('select', 'company', {
      options: [{ value: 'PSA', label: 'PSA' }, { value: 'BGS', label: 'BGS' }, { value: 'CGC', label: 'CGC' }, { value: 'SGC', label: 'SGC' }],
    }),
  },
  {
    key: 'grade', label: 'Grade', defaultVisible: false, sortable: true,
    render: (i) => text(i.grade, 'text-xs font-mono text-pine-300'),
    edit: fieldEdit('text', 'grade'),
  },
  {
    key: 'cert_number', label: 'Cert #', defaultVisible: false, sortable: true,
    render: (i) => text(i.cert_number, 'text-xs font-mono text-pine-400'),
    edit: fieldEdit('text', 'cert_number'),
  },
  {
    key: 'product_type', label: 'Product Type', defaultVisible: false, sortable: true, render: (i) => text(i.product_type),
    edit: fieldEdit('select', 'product_type', {
      options: opts(['booster_box', 'etb', 'bundle', 'booster_pack', 'collection_box', 'other']),
    }),
  },
  {
    key: 'description', label: 'Description', defaultVisible: false, sortable: true,
    render: (i) => clamped(i.description),
    edit: fieldEdit('textarea', 'description'),
  },
  {
    key: 'market_value_at_purchase',
    label: 'Market at Purchase',
    defaultVisible: false,
    sortable: true,
    className: 'text-right',
    render: (i) => money(i.market_value_at_purchase, 'text-xs text-pine-300'),
    edit: fieldEdit('money', 'market_value_at_purchase'),
  },
  {
    key: 'listed_price',
    label: 'Listed Price',
    defaultVisible: false,
    sortable: true,
    className: 'text-right',
    render: (i) => money(i.listed_price, 'text-xs text-pine-300'),
    edit: fieldEdit('money', 'listed_price', { undoLabel: 'Listed price' }),
  },
  {
    key: 'sticker_notes', label: 'Sticker Notes', defaultVisible: false, sortable: true,
    render: (i) => clamped(i.sticker_notes),
    edit: fieldEdit('textarea', 'sticker_notes'),
  },
  {
    key: 'acquired_at', label: 'Acquired', defaultVisible: false, sortable: true,
    render: (i) => text(i.acquired_at, 'text-xs font-mono text-pine-300'),
    edit: fieldEdit('date', 'acquired_at'),
  },
  {
    key: 'acquired_show_id', label: 'Acquired Show', defaultVisible: false, sortable: true,
    render: (i) => text(i.acquired_show_id, 'text-xs font-mono text-pine-400'),
    edit: (ctx) => ({
      type: 'select',
      options: ctx.showOptions ?? [],
      value: (item) => (item.acquired_show_id as string | undefined) ?? '',
      save: async (item, next) => {
        await ctx.saveField?.(item, 'acquired_show_id', next || null)
      },
    }),
  },
  {
    key: 'notes', label: 'Notes', defaultVisible: false, sortable: true, render: (i) => clamped(i.notes),
    edit: fieldEdit('textarea', 'notes'),
  },
  {
    key: 'value_note', label: 'Value Note', defaultVisible: false, sortable: true,
    render: (i) => clamped(i.value_note),
    edit: fieldEdit('textarea', 'value_note'),
  },
  {
    key: 'display_name_override', label: 'Name Override', defaultVisible: false, sortable: true,
    render: (i) => clamped(i.display_name_override),
    notEditable: 'Editable only from the Triage page — the modal’s Display Name row edits display_name instead.',
  },
  // Deliberately NOT an <a href>. `tcg_url` is admin-typed free text, and a
  // `javascript:` value in an href on a list page is a stored-XSS sink that
  // fires on one click. The detail modal is the place that links out.
  {
    key: 'tcg_url', label: 'TCGplayer URL', defaultVisible: false, sortable: true,
    render: (i) => clamped(i.tcg_url),
    edit: fieldEdit('url', 'tcg_url'),
  },
  {
    key: 'lineage_id', label: 'Lineage ID', defaultVisible: false, sortable: true,
    render: (i) => text(i.lineage_id, 'text-xs font-mono text-pine-400'),
    notEditable: 'Trade-lineage identity, written only by the trade confirm path.',
  },
  {
    key: 'predecessor_item_id', label: 'Predecessor', defaultVisible: false, sortable: true,
    render: (i) => text(i.predecessor_item_id, 'text-xs font-mono text-pine-400'),
    notEditable: 'Trade-lineage identity, written only by the trade confirm path.',
  },
  {
    key: 'item_id', label: 'Item ID', defaultVisible: false, sortable: true,
    render: (i) => text(i.item_id, 'text-xs font-mono text-pine-400'),
    notEditable: 'Primary identity key — never reassignable.',
  },

  {
    key: '_actions',
    label: '',
    // `pinned` outranks this; the flag is false only so `defaultVisible` keeps
    // meaning exactly "on by default IN THE PICKER", which this is not in.
    defaultVisible: false,
    pinned: true,
    className: 'w-20',
    notEditable: 'Row action buttons, not a data cell.',
    render: (item, ctx) => (
      <div className="flex items-center gap-1 justify-end">
        {/* Spotting a bad card mid-workflow is the use case, so this flags
            in one click rather than routing through the detail modal. */}
        <TriageRowAction item={item as TriageItem} onChanged={ctx.onRefresh} />
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); ctx.onDelete(item) }}
          className="p-1.5 rounded text-pine-500 hover:text-red-400 hover:bg-red-500/10 transition-colors"
          title="Delete"
        >
          <Trash2 size={14} />
        </button>
      </div>
    ),
  },
]

/** Every column an admin can toggle — i.e. everything but the actions cell. */
export const TOGGLEABLE_COLUMNS = INVENTORY_COLUMNS.filter((c) => !c.pinned)

export const DEFAULT_VISIBLE_COLUMN_KEYS = INVENTORY_COLUMNS
  .filter((c) => c.defaultVisible && !c.pinned)
  .map((c) => c.key)

/**
 * Build the `Column[]` DataTable actually renders.
 *
 * Order comes from the registry, never from `visible` — see rule 2 up top.
 * Pinned columns ignore `visible` entirely.
 */
export function toDataTableColumns(
  visible: Set<string>,
  ctx: ColumnRenderContext,
): Column<InventoryItem>[] {
  return INVENTORY_COLUMNS
    .filter((c) => c.pinned || visible.has(c.key))
    .map((c) => ({
      key: c.key,
      label: c.label,
      sortable: c.sortable,
      className: c.className,
      render: (item: InventoryItem) => c.render(item, ctx),
      edit: c.edit?.(ctx),
    }))
}

// --------------------------------------------------------------------------
// Persistence
// --------------------------------------------------------------------------

/**
 * Versioned on purpose. Bumping the suffix retires every saved list rather than
 * resurrecting a broken shape after a registry change — cheaper and safer than
 * writing a migration for a preference.
 */
export const COLUMN_STORAGE_KEY = 'admin-inventory-columns-v1'

const REGISTRY_KEYS = new Set(INVENTORY_COLUMNS.map((c) => c.key))

/**
 * The saved column choice, or the defaults.
 *
 * Every failure mode here resolves to "show the defaults", because this runs on
 * mount and anything that throws blanks the page. That covers: no browser
 * (SSR), storage disabled by policy (Safari private mode throws on ACCESS, not
 * just on a bad read), unparseable JSON, valid JSON of the wrong shape, keys
 * retired since the list was written, and a list where nothing survives
 * validation at all.
 */
export function loadVisibleColumnKeys(): string[] {
  if (typeof window === 'undefined') return DEFAULT_VISIBLE_COLUMN_KEYS

  let raw: string | null = null
  try {
    raw = window.localStorage.getItem(COLUMN_STORAGE_KEY)
  } catch {
    return DEFAULT_VISIBLE_COLUMN_KEYS
  }
  if (raw === null) return DEFAULT_VISIBLE_COLUMN_KEYS

  let parsed: unknown
  try {
    parsed = JSON.parse(raw)
  } catch {
    return DEFAULT_VISIBLE_COLUMN_KEYS
  }
  if (!Array.isArray(parsed)) return DEFAULT_VISIBLE_COLUMN_KEYS

  const saved = new Set(parsed.filter((k): k is string => typeof k === 'string' && REGISTRY_KEYS.has(k)))
  // Registry order, not saved order.
  const keys = TOGGLEABLE_COLUMNS.filter((c) => saved.has(c.key)).map((c) => c.key)
  // A table with no columns is worse than a reset one — this is what a registry
  // rewrite without a version bump looks like from the reader's side.
  return keys.length > 0 ? keys : DEFAULT_VISIBLE_COLUMN_KEYS
}

/** Persist the choice. Never throws: this is called straight from a checkbox. */
export function saveVisibleColumnKeys(keys: string[]): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(COLUMN_STORAGE_KEY, JSON.stringify(keys))
  } catch {
    // Quota exceeded, or storage disabled. The choice still applies for this
    // session; losing it on reload beats taking the page down over a checkbox.
  }
}

// --------------------------------------------------------------------------
// Filters
// --------------------------------------------------------------------------

/**
 * The control a field deserves. Mirrors `FieldKind` in
 * `backend/services/inventory_filters.py` CHARACTER FOR CHARACTER — these
 * strings are the wire contract, not a display label.
 */
export type FilterKind = 'text' | 'select' | 'range' | 'dateRange' | 'presence'

/** What a filter does to its field. Mirrors the backend `FilterOp` exactly. */
export type FilterOp = 'contains' | 'eq' | 'gte' | 'lte' | 'isnull' | 'notnull'

/** Where a `select` gets its options when they are not a static list. */
export type FilterOptionSource = 'locations' | 'shows' | 'sets' | 'cosigners'

export interface InventoryFilterDef {
  /** The page's state key for this filter, and its key in `FilterValues`. */
  id: string
  /** Accessible name of the control, and the label used in the hidden notice. */
  label: string
  /**
   * The column this filter follows. `null` means the filter has no column at
   * all — see the note on the catalog filters below.
   */
  columnKey: string | null
  /** Which control to render, and which operators are legal for it. */
  kind: FilterKind
  /** The backend field name. Defaults to `columnKey` when omitted. */
  field?: string
  /**
   * The operator this entry sends. Required on `range` and `dateRange`, where
   * the two bounds are two entries over one column — `gte` and `lte`. Derived
   * from `kind` for everything else.
   */
  op?: FilterOp
  /** For `kind: 'select'` — a static list of choices. */
  options?: { value: string; label: string }[]
  /** For `kind: 'select'` — a list the page fetches rather than declares. */
  optionSource?: FilterOptionSource
  /**
   * The pre-existing named parameter this filter sends INSTEAD of the generic
   * `filter=` triple. See `buildFilterParams` for why four of them must stay.
   */
  legacyParam?: string
}

/** `['a', 'b_c']` → `[{value: 'a', label: 'a'}, {value: 'b_c', label: 'b c'}]`. */
function opts(values: readonly string[]): { value: string; label: string }[] {
  return values.map((v) => ({ value: v, label: v.replace(/_/g, ' ') }))
}

const YES_NO = [
  { value: 'true', label: 'Yes' },
  { value: 'false', label: 'No' },
]

/**
 * Every filter the page offers, each bound to the column it follows.
 *
 * **The registry is TOTAL** (RFC 0011 T4): every column but `_image` and
 * `_actions` has at least one entry, and `admin-inventory-columns.test.ts` fails
 * the moment a new column arrives without one. It covered twelve of
 * thirty-three before, which is how the panel ended up offering fields
 * (`card_number`, `artist`) with no relationship to what was on screen.
 *
 * `set_id` / `card_number` / `artist` are bound to `null` deliberately. They
 * filter on catalog fields, and the ordinary admin search response carries no
 * catalog join (`_attach_catalog_cards` is scoped to `triage=true`), so a Set or
 * Artist column would render an em dash on every row. Rather than ship three
 * permanently-empty columns, they are filter-only — which under the rule below
 * means they live behind "show all filters", and any one of them left active is
 * called out by the hidden-filter notice.
 *
 * The Set filter sends `set_id`, not the `set_name` substring it used to (T8).
 * Names are not unique across languages — "Base Set" is both `en:base1` and
 * `ja:base1` — so a substring cannot express the selection the combobox makes.
 *
 * **Every `kind` here must match `FILTERABLE_FIELDS` on the backend**, because
 * the kind picks the operator and the backend 422s an operator its own kind
 * does not allow. `only ever emits ops the backend registry accepts` is the test
 * that catches a drift, but it can only compare against a hand-copied table —
 * check `services/inventory_filters.py` when adding a field.
 */
export const INVENTORY_FILTERS: InventoryFilterDef[] = [
  // --- The nine that predate T4, keeping their named parameters -------------
  { id: 'search', label: 'Name', columnKey: 'display_name', kind: 'text', legacyParam: 'name' },
  {
    id: 'status', label: 'Status', columnKey: 'status', kind: 'select', legacyParam: 'status',
    options: opts(['available', 'sold', 'lost', 'on_hold', 'consigned']),
  },
  {
    id: 'kind', label: 'Kind', columnKey: 'kind', kind: 'select', legacyParam: 'kind',
    options: opts(['raw', 'graded', 'sealed', 'bulk']),
  },
  {
    id: 'condition', label: 'Condition', columnKey: 'condition', kind: 'select',
    legacyParam: 'condition', options: opts(CONDITION_VALUES),
  },
  {
    id: 'location', label: 'Location', columnKey: 'location', kind: 'select',
    legacyParam: 'location', optionSource: 'locations',
  },
  {
    id: 'minPrice', label: 'Min $', columnKey: 'current_market_value', kind: 'range',
    op: 'gte', legacyParam: 'min_price',
  },
  {
    id: 'maxPrice', label: 'Max $', columnKey: 'current_market_value', kind: 'range',
    op: 'lte', legacyParam: 'max_price',
  },
  {
    id: 'ownership', label: 'Ownership', columnKey: 'consignment', kind: 'select',
    legacyParam: 'ownership',
    // `cosigned`, not `consigned`. The backend accepts exactly 'owned' and
    // 'cosigned' and 400s anything else; this option sent the other spelling,
    // so picking it took the list down rather than filtering it.
    options: [{ value: 'owned', label: 'Owned' }, { value: 'cosigned', label: 'Cosigned' }],
  },
  {
    id: 'needsReview', label: 'Needs Review', columnKey: 'needs_review', kind: 'select',
    legacyParam: 'needs_review',
    options: [{ value: 'true', label: 'Flagged' }, { value: 'false', label: 'Clear' }],
  },

  // --- T4: the twenty-two columns that had no filter at all ----------------
  {
    id: 'costBasisMin', label: 'Price Paid Min', columnKey: 'cost_basis',
    kind: 'range', op: 'gte',
  },
  {
    id: 'costBasisMax', label: 'Price Paid Max', columnKey: 'cost_basis',
    kind: 'range', op: 'lte',
  },
  {
    id: 'stickerPriceMin', label: 'Sticker Min', columnKey: 'sticker_price',
    kind: 'range', op: 'gte',
  },
  {
    id: 'stickerPriceMax', label: 'Sticker Max', columnKey: 'sticker_price',
    kind: 'range', op: 'lte',
  },
  {
    id: 'listedPriceMin', label: 'Listed Min', columnKey: 'listed_price',
    kind: 'range', op: 'gte',
  },
  {
    id: 'listedPriceMax', label: 'Listed Max', columnKey: 'listed_price',
    kind: 'range', op: 'lte',
  },
  {
    id: 'marketAtPurchaseMin', label: 'Market at Purchase Min',
    columnKey: 'market_value_at_purchase', kind: 'range', op: 'gte',
  },
  {
    id: 'marketAtPurchaseMax', label: 'Market at Purchase Max',
    columnKey: 'market_value_at_purchase', kind: 'range', op: 'lte',
  },
  { id: 'gradeMin', label: 'Grade Min', columnKey: 'grade', kind: 'range', op: 'gte' },
  { id: 'gradeMax', label: 'Grade Max', columnKey: 'grade', kind: 'range', op: 'lte' },

  { id: 'acquiredFrom', label: 'Acquired From', columnKey: 'acquired_at', kind: 'dateRange', op: 'gte' },
  { id: 'acquiredTo', label: 'Acquired To', columnKey: 'acquired_at', kind: 'dateRange', op: 'lte' },
  { id: 'reviewedFrom', label: 'Reviewed From', columnKey: 'reviewed_at', kind: 'dateRange', op: 'gte' },
  { id: 'reviewedTo', label: 'Reviewed To', columnKey: 'reviewed_at', kind: 'dateRange', op: 'lte' },

  {
    id: 'language', label: 'Language', columnKey: 'language', kind: 'select',
    options: opts(['EN', 'JP', 'FR', 'DE', 'ES', 'IT', 'PT', 'KO', 'ZH']),
  },
  {
    id: 'finish', label: 'Finish', columnKey: 'finish', kind: 'select',
    // The INTERNAL finish vocabulary, which is what the item stores —
    // `services/tcgdex._map_finish` is the only thing that speaks TCGdex's
    // hyphenated spelling.
    options: [
      { value: 'normal', label: 'Normal' },
      { value: 'holofoil', label: 'Holofoil' },
      { value: 'reverseHolofoil', label: 'Reverse Holofoil' },
    ],
  },
  {
    id: 'factorySealed', label: 'Factory Sealed', columnKey: 'factory_sealed',
    kind: 'select', options: YES_NO,
  },
  {
    id: 'company', label: 'Grading Co.', columnKey: 'company', kind: 'select',
    options: opts(['PSA', 'BGS', 'CGC', 'SGC']),
  },
  {
    id: 'productType', label: 'Product Type', columnKey: 'product_type', kind: 'select',
    // A closed `SealedProductType` enum on the backend, which is why this is a
    // dropdown and not the text box the task doc first sketched: a `contains`
    // on a SELECT field is a 422, not a wider match.
    options: opts(['booster_box', 'etb', 'bundle', 'booster_pack', 'collection_box', 'other']),
  },
  {
    id: 'acquiredShow', label: 'Acquired Show', columnKey: 'acquired_show_id',
    // A SELECT sourced from GET /admin/shows, on the same reasoning that makes
    // Location a dropdown: the values are a managed list, and a substring match
    // across show names is not a question anyone has.
    kind: 'select', optionSource: 'shows',
  },

  // Card ID is a PRESENCE control, not a text box. Nobody types `en:sv3pt5-158`
  // from memory; the question actually asked at this column is "which of my
  // cards are unlinked", and that is one dropdown.
  { id: 'cardIdPresence', label: 'Card link', columnKey: 'card_id', kind: 'presence' },
  {
    id: 'nameOverridePresence', label: 'Name Override', columnKey: 'display_name_override',
    kind: 'presence',
  },

  { id: 'reviewReason', label: 'Review Reason', columnKey: 'review_reason', kind: 'text' },
  { id: 'certNumber', label: 'Cert #', columnKey: 'cert_number', kind: 'text' },
  { id: 'description', label: 'Description', columnKey: 'description', kind: 'text' },
  { id: 'stickerNotes', label: 'Sticker Notes', columnKey: 'sticker_notes', kind: 'text' },
  { id: 'notes', label: 'Notes', columnKey: 'notes', kind: 'text' },
  { id: 'valueNote', label: 'Value Note', columnKey: 'value_note', kind: 'text' },
  { id: 'tcgUrl', label: 'TCGplayer URL', columnKey: 'tcg_url', kind: 'text' },
  { id: 'lineageId', label: 'Lineage ID', columnKey: 'lineage_id', kind: 'text' },
  { id: 'predecessor', label: 'Predecessor', columnKey: 'predecessor_item_id', kind: 'text' },
  { id: 'itemId', label: 'Item ID', columnKey: 'item_id', kind: 'text' },

  // --- Column-less: catalog joins, see the note above ----------------------
  {
    id: 'setId', label: 'Set', columnKey: null, kind: 'select', legacyParam: 'set_id',
    optionSource: 'sets',
  },
  { id: 'cardNumber', label: 'Card #', columnKey: null, kind: 'text', legacyParam: 'card_number' },
  { id: 'artist', label: 'Artist', columnKey: null, kind: 'text', legacyParam: 'artist' },
  {
    id: 'consignor', label: 'Consignor', columnKey: 'consignor_name', kind: 'select',
    legacyParam: 'consignor_id', optionSource: 'cosigners',
  },
]

/**
 * The owner's Q9 decision, entire: filters follow the visible columns, plus an
 * escape hatch that reveals all of them.
 */
export function isFilterVisible(
  filter: InventoryFilterDef,
  visible: Set<string>,
  showAllFilters: boolean,
): boolean {
  if (showAllFilters) return true
  return filter.columnKey !== null && visible.has(filter.columnKey)
}

// --------------------------------------------------------------------------
// Turning the panel's values into a query
// --------------------------------------------------------------------------

/** Filter id → the raw string the control holds. `''` means unset. */
export type FilterValues = Record<string, string>

/** The op a filter sends, given its kind and (for presence) its value. */
function opFor(def: InventoryFilterDef, value: string): FilterOp | null {
  if (def.kind === 'presence') {
    if (value === 'has') return 'notnull'
    if (value === 'missing') return 'isnull'
    return null
  }
  if (def.op) return def.op
  return def.kind === 'select' ? 'eq' : 'contains'
}

/**
 * The value as the backend wants it, or `null` to send nothing.
 *
 * A `range` bound goes through `parseMoney`, NEVER `parseFloat` — the owner
 * types `1,300`, `parseFloat` reads that as `1`, and `1` is not `NaN` so it
 * passes every guard on the way to the wire. An unparseable bound sends
 * nothing rather than a 422: the value changes on every keystroke, so `1,`
 * exists for as long as it takes to type the next digit, and a 422 there blanks
 * the whole list mid-type.
 */
function wireValue(def: InventoryFilterDef, value: string): string | null {
  if (def.kind === 'presence') return ''
  if (def.kind !== 'range') return value
  const parsed = parseMoney(value)
  // `=== null`, never falsiness: `0` is a real bound (a free throw-in card).
  return parsed === null ? null : String(parsed)
}

/**
 * Split the panel's values into named params and generic `filter=` triples.
 *
 * Two spellings, ONE evaluator on the backend (RFC 0011 T3). A filter carrying
 * `legacyParam` keeps sending it — four of those do something on the server a
 * plain field comparison cannot (`name` searches notes too, `condition` splits
 * `LP+` into tier and modifier, `min_price` falls back to cost when no market
 * figure is known, and the catalog filters join the catalog). Re-expressing
 * those as `filter=` would silently narrow what they match.
 *
 * Returns `filters` as an ARRAY because the parameter is repeatable:
 * `?filter=notes:contains:foil&filter=cost_basis:gte:100`.
 */
export function buildFilterParams(
  values: FilterValues,
): { params: Record<string, string>; filters: string[] } {
  const params: Record<string, string> = {}
  const filters: string[] = []

  for (const def of INVENTORY_FILTERS) {
    const raw = values[def.id] ?? ''
    if (raw === '') continue

    // Normalised FIRST, so a legacy money param gets the same comma handling as
    // a generic one. `min_price` is a `Decimal` query param on the backend and
    // 422s on "1,300" exactly like `cost_basis:gte:` would.
    const value = wireValue(def, raw)
    if (value === null) continue

    if (def.legacyParam) {
      params[def.legacyParam] = value
      continue
    }

    const field = def.field ?? def.columnKey
    const op = opFor(def, raw)
    if (!field || op === null) continue
    filters.push(`${field}:${op}:${value}`)
  }

  return { params, filters }
}
