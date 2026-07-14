// Typed client for the FastAPI backend's inventory endpoints — implemented via TDD.
// The BACKEND owns this contract (backend/src/merlins_collection/routers/):
//   GET /inventory/search  → { items: InventoryItem[], total: number }
//   POST /chat/            → { reply: string }
// Decimal fields (prices, grades) arrive as JSON *strings*; each item carries
// an optional catalog `card` summary for display (null when not yet synced).
import { apiFetch } from './api'

export type Condition = 'NM' | 'LP' | 'MP' | 'HP' | 'DMG'
export type GradingCompany = 'PSA' | 'BGS' | 'CGC' | 'SGC'

/** Catalog data joined onto a search result for display. */
export interface CardSummary {
  card_id: string
  name: string
  set_id: string
  set_name: string
  number: string
  rarity: string | null
  image_small: string | null
}

interface ItemBase {
  card_id: string
  quantity: number
  /** Decimal serialized as a string, e.g. "250.00". */
  listed_price: string
  current_market_value: string | null
  acquired_at: string
  card: CardSummary | null
}

export interface RawInventoryItem extends ItemBase {
  kind: 'raw'
  finish: string
  condition: Condition
}

export interface GradedInventoryItem extends ItemBase {
  kind: 'graded'
  company: GradingCompany
  /** Decimal serialized as a string, e.g. "9.5". */
  grade: string
  cert_number: string
}

export type InventoryItem = RawInventoryItem | GradedInventoryItem

export interface InventorySearchResult {
  items: InventoryItem[]
  total: number
}

/** Flat filter params the FastAPI `/inventory/search` endpoint accepts. */
export interface InventoryFilters {
  name?: string
  set_id?: string
  rarity?: string
  condition?: string
  min_price?: string
  max_price?: string
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

/** Display name for an item: catalog name, or the card id if not yet synced. */
export function itemTitle(item: InventoryItem): string {
  return item.card?.name ?? item.card_id
}

/** Condition badge text: raw grade ("NM") or slab label ("PSA 9.5"). */
export function conditionLabel(item: InventoryItem): string {
  return item.kind === 'raw' ? item.condition : `${item.company} ${item.grade}`
}

/**
 * Stable unique key for a result tile. card_id alone is NOT unique — the same
 * card can appear as multiple raw finishes/conditions and graded slabs.
 */
export function itemKey(item: InventoryItem): string {
  return item.kind === 'raw'
    ? `${item.card_id}:raw:${item.finish}:${item.condition}`
    : `${item.card_id}:graded:${item.company}:${item.grade}:${item.cert_number}`
}
