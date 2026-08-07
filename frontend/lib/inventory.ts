// Typed client for the FastAPI backend's inventory endpoints — implemented via TDD.
// The BACKEND owns this contract (backend/src/merlins_collection/routers/):
//   GET /inventory/search  → { items: InventoryItem[], total: number }
//   POST /chat/            → { reply: string }
// Decimal fields (prices, grades) arrive as JSON *strings*; each item carries
// an optional catalog `card` summary for display (null when not yet synced).
import { apiFetch } from './api'

export type Condition = 'NM' | 'LP' | 'MP' | 'HP' | 'DMG'
export type ConditionModifier = '+' | '-'
export type GradingCompany = 'PSA' | 'BGS' | 'CGC' | 'SGC'
export type SealedProductType =
  | 'booster_box'
  | 'etb'
  | 'bundle'
  | 'booster_pack'
  | 'collection_box'
  | 'other'

/** Catalog data joined onto a search result for display. */
export interface CardSummary {
  card_id: string
  name: string
  set_id: string
  set_name: string
  number: string
  rarity: string | null
  image_small: string | null
  // Live pokemontcg.io market price for a matched card; null when the catalog
  // has none, in which case the tile falls back to the sheet's listed price.
  market_price: string | null
}

export type Language = 'EN' | 'JP'

interface ItemBase {
  /** Per-unit identity (the stable key). Post Database-Redesign; not card_id. */
  item_id: string
  /** Optional now: absent for sealed products and unmatched cards. */
  card_id?: string | null
  /** Decimal serialized as a string, e.g. "250.00" (null when unpriced). */
  listed_price: string | null
  current_market_value: string | null
  acquired_at: string
  /**
   * Print language (EN/JP). Optional on the wire for backward-compatibility —
   * a missing value means English (a JP print is a different, differently
   * priced card). Read it via {@link isJapanese}, which defaults absent → EN.
   */
  language?: Language
  card: CardSummary | null
  /**
   * Sanitized name+number fallback the backend derives from an unmatched item's
   * identity text (e.g. "Dragonair #181"). Present only when there is no catalog
   * card; carries no internal notes/cost/location. Ranks above the raw ULID in
   * {@link itemTitle}.
   */
  display_name?: string | null
  /**
   * An admin-typed name that OUTRANKS the catalog name — the only thing that
   * does. Set on a Japanese card whose catalog row is in Japanese script so a
   * customer sees a name they can read; absent (the normal case) means the
   * catalog name renders unchanged. Editing it never touches `card_id`, so it
   * cannot break the item's catalog link. Read it via {@link itemTitle}.
   */
  display_name_override?: string | null
}

export interface RawInventoryItem extends ItemBase {
  kind: 'raw'
  finish: string
  condition: Condition
  /** +/- nuance on the tier (an LP+ is an LP, but nicer). */
  condition_modifier?: ConditionModifier | null
  factory_sealed?: boolean
}

export interface GradedInventoryItem extends ItemBase {
  kind: 'graded'
  company: GradingCompany
  /** Decimal serialized as a string, e.g. "9.5". */
  grade: string
  cert_number: string
}

/** A sealed product (booster box / ETB / …). No catalog card, no condition. */
export interface SealedInventoryItem extends ItemBase {
  kind: 'sealed'
  product_name: string
  product_type: SealedProductType
}

export type InventoryItem =
  | RawInventoryItem
  | GradedInventoryItem
  | SealedInventoryItem

export interface InventorySearchResult {
  items: InventoryItem[]
  total: number
  /**
   * How many otherwise-matching cards the price range excluded purely because
   * they have no price on file. They stay excluded — a card with no known price
   * cannot honestly be claimed to be under $500 — but the UI surfaces the count
   * so they are not dropped invisibly. Always 0 when no price bound was sent.
   */
  hidden_no_price: number
}

/** Flat filter params the FastAPI `/inventory/search` endpoint accepts. */
export interface InventoryFilters {
  name?: string
  set_id?: string
  rarity?: string
  condition?: string
  min_price?: string
  max_price?: string
  /** 'EN' | 'JP'; omitted (or '') means "all languages" (no filter). */
  language?: string
  /** Sort order: newest, oldest, price_desc, price_asc, name_asc, name_desc. */
  sort?: string
}

/** A set option from the facets endpoint. */
export interface FacetSet {
  id: string
  name: string
}

/** Distinct filterable values present among customer-visible inventory. */
export interface InventoryFacets {
  sets: FacetSet[]
  rarities: string[]
  conditions: string[]
  languages: string[]
}

/** Dashboard header stats over the customer-visible cohort. `est_value` is a
 *  backend Decimal serialized as a string (format it with {@link formatPrice}). */
export interface InventorySummary {
  cards_in_vault: number
  est_value: string
  sets_tracked: number
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface ChatResponse {
  reply: string
}

export interface RequestOptions {
  /** Cognito access token, forwarded as a bearer header. */
  token?: string
}

const FILTER_KEYS: (keyof InventoryFilters)[] = [
  'name',
  'set_id',
  'rarity',
  'condition',
  'min_price',
  'max_price',
  'language',
  'sort',
]

/** Build a flat, URL-encoded query string from filters, omitting empty fields. */
export function buildSearchQuery(filters: InventoryFilters): string {
  const params = new URLSearchParams()
  for (const key of FILTER_KEYS) {
    const value = filters[key]
    if (value !== undefined && value !== null && String(value).trim() !== '') {
      params.set(key, String(value))
    }
  }
  return params.toString()
}

/** Search the inventory via the FastAPI backend (filter mode). */
export async function searchInventory(
  filters: InventoryFilters,
  opts: RequestOptions = {},
): Promise<InventorySearchResult> {
  const query = buildSearchQuery(filters)
  const path = query ? `/inventory/search?${query}` : '/inventory/search'
  return apiFetch<InventorySearchResult>(path, { token: opts.token })
}

/** Fetch the authenticated dashboard summary (same cohort as the search). */
export async function getInventorySummary(
  opts: RequestOptions = {},
): Promise<InventorySummary> {
  return apiFetch<InventorySummary>('/inventory/summary', { token: opts.token })
}

/** Fetch distinct filter options from the DB (Phase 13 — no hardcoded values). */
export async function getInventoryFacets(
  opts: RequestOptions = {},
): Promise<InventoryFacets> {
  return apiFetch<InventoryFacets>('/inventory/facets', { token: opts.token })
}

/** Send a chat message (with prior turns) to the Bedrock-backed endpoint. */
export async function sendChat(
  message: string,
  history: ChatMessage[],
  opts: RequestOptions = {},
): Promise<ChatResponse> {
  // Trailing slash matters: the backend route is /chat/ and a bare /chat
  // would cost a 307 round-trip.
  return apiFetch<ChatResponse>('/chat/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, history }),
    token: opts.token,
  })
}

const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })

/** Format a backend decimal string as USD, or a friendly fallback. */
export function formatPrice(value: string | null | undefined): string {
  if (value == null) return 'Price N/A'
  const parsed = Number.parseFloat(value)
  return Number.isNaN(parsed) ? 'Price N/A' : usd.format(parsed)
}

const PRODUCT_TYPE_LABELS: Record<SealedProductType, string> = {
  booster_box: 'Booster Box',
  etb: 'Elite Trainer Box',
  bundle: 'Bundle',
  booster_pack: 'Booster Pack',
  collection_box: 'Collection Box',
  other: 'Sealed',
}

/**
 * Display name for a tile: an admin's `display_name_override` beats everything
 * — including a sealed product's own name — since correcting what the customer
 * reads is the whole point of it. With no override (the normal case): a sealed
 * product's own name, else the catalog name, then the backend's sanitized
 * name+number fallback, then the card id, and only the item id ULID as a last
 * resort when nothing else is present.
 *
 * The override is checked with a trim rather than `??` because `??` passes an
 * empty string straight through, which would render a NAMELESS tile.
 */
export function itemTitle(item: InventoryItem): string {
  const override = item.display_name_override?.trim()
  if (override) return override
  if (item.kind === 'sealed') return item.product_name
  return item.card?.name ?? item.display_name ?? item.card_id ?? item.item_id
}

/**
 * Condition/type badge: raw grade with its +/- modifier ("LP+"), slab label
 * ("PSA 9.5"), or a human-readable product type for a sealed product.
 */
export function conditionLabel(item: InventoryItem): string {
  if (item.kind === 'raw') return `${item.condition}${item.condition_modifier ?? ''}`
  if (item.kind === 'graded') return `${item.company} ${item.grade}`
  return PRODUCT_TYPE_LABELS[item.product_type] ?? 'Sealed'
}

/** Stable unique key for a result tile — item_id is the per-unit identity. */
export function itemKey(item: InventoryItem): string {
  return item.item_id
}

/** True for a Japanese print. A missing language defaults to English. */
export function isJapanese(item: InventoryItem): boolean {
  return item.language === 'JP'
}
