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
  // has none. RFC 0025: no longer read by {@link toPresentedCard} — the
  // customer tile renders `sticker_price`, not a catalog estimate — but the
  // field stays on the wire; nothing else in this file's contract removed it.
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
  /**
   * RFC 0025: the price the business actually sells the card at — what
   * {@link toPresentedCard} renders on the tile. A customer-visible item is
   * guaranteed to have one (`is_customer_visible` requires it); `null` here
   * would mean the caller is holding an item it should never have fetched.
   */
  sticker_price: string | null
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

/**
 * Dashboard header stats over the customer-visible cohort.
 *
 * RFC 0025 T5 removed `est_value` — the owner asked for the Est. value tile
 * removed from the dashboard, not merely relabeled. Do not re-add a value
 * field here; the backend's `InventorySummary` no longer sends one.
 */
export interface InventorySummary {
  cards_in_vault: number
  sets_tracked: number
}

export interface DisplayCardSummary {
  // Council r2 self-review M5: set_id, rarity, image_large and market_price
  // were on the wire with no reader on either display surface (DisplayPanel,
  // ChatPanel) -- market_price in particular duplicated the exact same
  // condition-adjusted figure already carried on DisplayedCard.listed_price
  // for a raw item. All four dropped. card_id survives even though its only
  // reader (a JP-badge `.startsWith('ja:')` inference) was replaced by
  // DisplayedCard.language below -- it's a reasonable identity field on its
  // own, unlike the other four.
  card_id: string
  name: string
  set_name: string
  number: string
  image_small: string
}

export interface DisplayedCard {
  item_id: string
  // Narrowed from 'raw' | 'graded' | 'sealed' | 'bulk' (RFC-0016 Council r2):
  // sealed/bulk are unreachable -- see DisplayedCard.kind's docstring in
  // backend models/chat.py for the full reasoning.
  kind: 'raw' | 'graded'
  card: DisplayCardSummary | null
  display_name: string | null
  listed_price: string | null
  current_market_value: string | null
  condition: string | null
  // finish dropped (Council r2 self-review M5): no reader on either display
  // surface.
  company: string | null
  grade: string | null
  grade_label: string | null
  cert_number: string | null
  // Council r2 (advisor-architect M4 / advisor-contrarian): the JP badge
  // used to be inferred from card.card_id.startsWith('ja:'), unavailable for
  // an uncatalogued item (card is null) -- an uncatalogued Japanese card
  // silently lost its badge. "EN" | "JP", independent of any catalog match.
  language: string | null
  // cert_image_url intentionally NOT a field here (RFC 0016 Council r1
  // checklist item 5): admin-scoped, provider-supplied, and only
  // scheme-validated on the backend — must not reach the customer wire.
}

export interface DisplayPanelState {
  // No `open` field (decision 23): open/closed is inferred purely from
  // whether `cards` is non-empty. The five panel-mutation tools were
  // collapsed into a single `set_display(item_ids)`; an empty list is the
  // explicit close primitive, so there's no incremental state left to
  // desynchronize from what `cards` itself says.
  cards: DisplayedCard[]
  truncated: boolean
}

export interface ChatResponse {
  reply: string
  artifacts?: DisplayedCard[]
  panel?: DisplayPanelState
  /**
   * The thread this exchange landed in — echoed back so a new thread's
   * implicitly-created id reaches the client.
   *
   * CAUTION: the backend sets this unconditionally, including when the write
   * that would have persisted the thread failed (it swallows that failure
   * rather than discard a paid-for Bedrock reply). So an id here is
   * well-formed but not proof the thread exists. Treat a later 404 as "this
   * thread is gone" and start a new one.
   */
  conversation_id?: string
  /** Server-derived thread title, from the first user message. */
  title?: string
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

/** What the caller carries between turns of one thread. */
export interface SendChatContext {
  /**
   * The thread this message belongs to. Omitted (or null) starts a new one —
   * the backend creates it implicitly and returns its id on the response.
   */
  conversationId?: string | null
  /** Stable item IDs of the currently-displayed cards; every other field is
   * discarded and re-hydrated by the backend. */
  panelItemIds?: string[]
}

/**
 * Send a chat message.
 *
 * RFC 0017: no `history` array goes up any more. The transcript is server-
 * owned and replayed from storage, which is what stops a client forging
 * assistant turns — so the client's whole job is carrying the thread id.
 */
export async function sendChat(
  message: string,
  context: SendChatContext = {},
  opts: RequestOptions = {},
): Promise<ChatResponse> {
  const body: Record<string, unknown> = { message }
  if (context.conversationId) body.conversation_id = context.conversationId
  if (context.panelItemIds) body.panel_item_ids = context.panelItemIds

  // Trailing slash matters: the backend route is /chat/ and a bare /chat
  // would cost a 307 round-trip.
  return apiFetch<ChatResponse>('/chat/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    token: opts.token,
  })
}

const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })

/** Format a backend decimal string as USD, or a friendly fallback. */
export function formatPrice(value: number | string | null | undefined): string {
  if (value == null) return 'Price N/A'
  const parsed = typeof value === 'number' ? value : Number.parseFloat(value)
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

// ---- RFC 0019: Inventory Split Workspace ----
// Filter mode (InventoryItem[]) and chat mode (DisplayedCard[]) each have
// their own wire shape, but both render through the exact same
// CardPresentation component. PresentedCard is the one normalized shape a
// shared results grid (ResultsPane) can consume regardless of which mode
// produced it.

export interface PresentedCard {
  key: string
  title: string
  imageUrl?: string
  setName: string
  number?: string
  conditionLabel: string
  price: string
  isJapanese: boolean
}

/** Map a search-result item into the shared card-presentation shape. */
export function toPresentedCard(item: InventoryItem): PresentedCard {
  return {
    key: itemKey(item),
    title: itemTitle(item),
    imageUrl: item.card?.image_small ?? undefined,
    setName: item.card?.set_name ?? 'Unknown set',
    number: item.card?.number,
    conditionLabel: conditionLabel(item),
    // RFC 0025: the price the business actually sells the card at, not an
    // estimate. `_display_price` (backend) is the identical authority
    // already used for the price filter and the price sort — reading
    // `sticker_price` directly here, rather than re-deriving it from
    // `card.market_price`/`listed_price`, is what keeps this tile from ever
    // disagreeing with what a customer just filtered or sorted by (RFC 0025
    // follow-ups #7; this used to read the pre-RFC-0025 catalog-market
    // computation, which `is_customer_visible` no longer guarantees a
    // visible item even has).
    price: item.sticker_price ?? 'Price N/A',
    isJapanese: isJapanese(item),
  }
}

/**
 * Condition/grade label for a chat-displayed card. Consolidates what used to
 * be copy-pasted as `cardCondition` (DisplayPanel.tsx) and
 * `artifactCondition` (ChatPanel.tsx) — both retired by RFC 0019 in favor of
 * this single implementation.
 */
function displayedCardCondition(card: DisplayedCard): string {
  if (card.condition) return card.condition
  if (card.kind === 'graded') {
    if (card.grade_label) return card.grade_label
    const slabGrade = [card.company, card.grade].filter(Boolean).join(' ')
    if (slabGrade) return slabGrade
  }
  return 'N/A'
}

/** Map a chat-displayed card into the shared card-presentation shape. */
export function displayedCardToPresentedCard(card: DisplayedCard): PresentedCard {
  return {
    key: card.item_id,
    title: card.display_name || card.card?.name || 'Unknown card',
    imageUrl: card.card?.image_small || undefined,
    setName: card.card?.set_name ?? 'Unknown set',
    number: card.card?.number,
    conditionLabel: displayedCardCondition(card),
    // listed_price is the RESOLVED, condition-adjusted price (mirrors
    // routers/inventory.py::_display_price) and must win over
    // current_market_value, a separate, potentially stale pass-through
    // (RFC-0016 Council r2 self-review) — preserved unchanged here.
    price: card.listed_price ?? card.current_market_value ?? 'Price N/A',
    isJapanese: card.language === 'JP',
  }
}
