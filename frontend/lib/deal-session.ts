import { adminItemName } from './admin-item-name'
import type { DealMode, DealInventoryItem } from '@/components/admin/deal/DealSearchPanel'
import type { IncomingLeg } from './trade-incoming-form'

export type { DealMode }

/**
 * The subset of `useAdminApi()`'s return value this module needs. Typed
 * locally rather than imported from `lib/admin-api` so this file stays a
 * plain module — no `'use client'`, no hook — and can be unit tested without
 * rendering anything.
 */
export interface AdminApi {
  get<T = unknown>(path: string, params?: Record<string, unknown>): Promise<T>
  post<T = unknown>(path: string, body?: unknown): Promise<T>
  put<T = unknown>(path: string, body?: unknown): Promise<T>
  patch<T = unknown>(path: string, body?: unknown): Promise<T>
  del<T = unknown>(path: string, params?: Record<string, unknown>): Promise<T>
}

export interface CashComponent {
  direction: 'we_pay' | 'they_pay'
  amount: number
  payment_method: 'cash' | 'venmo' | 'zelle' | 'card'
}

export interface ConfirmMeta {
  counterparty?: string | null
  notes?: string | null
  /** `YYYY-MM-DD`, from `todayLocal()` — never built with `new Date()`. */
  date?: string | null
  payment_method?: string
  /** trade only */
  basis_mode?: 'transfer' | 'split' | 'manual'
  /** trade, manual mode only */
  manual_basis?: string
}

export interface ConfirmResult {
  /** Trade's commit path — what T13's graded-price verification reads back. */
  item_ids?: string[]
  [key: string]: unknown
}

export interface DealSessionApi {
  create(): Promise<string>
  addIncoming(id: string, leg: IncomingLeg): Promise<void>
  addOutgoing(id: string, item: DealInventoryItem, value: number): Promise<void>
  removeIncoming(id: string, index: number): Promise<void>
  /**
   * Takes the leg's real `item_id`, never a positional index. An adapter
   * that tracked index -> item_id in a local Map lost that map whenever
   * `sessionApiFor`'s memo re-ran with a fresh `api` identity (e.g. a
   * next-auth token refresh mid-deal), silently no-opping remove/update
   * while the page's own state still showed the row gone or edited.
   */
  removeOutgoing(id: string, itemId: string): Promise<void>
  /**
   * Patch a staged outgoing leg's negotiated price to the session, so a
   * price the operator edits on screen is the price Confirm actually sends
   * — not just the price the row happened to start with (RFC 0011 T15 fix
   * round 1). Keyed by `item_id`, for the same reason as `removeOutgoing`.
   */
  updateOutgoing(id: string, itemId: string, value: number): Promise<void>
  setCash(id: string, components: CashComponent[]): Promise<void>
  confirm(id: string, meta: ConfirmMeta): Promise<ConfirmResult>
  supports: { incoming: boolean; outgoing: boolean; costBasisMode: boolean }
}

/**
 * Which session API a mode drives.
 *
 * The three endpoints stay separate (RFC 0011 decision 16) because they are the
 * highest-risk money paths in the repo — RFC 0010 T0 exists because a partial write in
 * one of them created real inventory and then reported "Nothing was created". Merging
 * the UI is a large enough change on its own; this adapter is what keeps the page from
 * growing a `if (mode === 'buy')` at every call site, which is how three code paths
 * come back in disguise.
 */
export function sessionApiFor(mode: DealMode, api: AdminApi): DealSessionApi {
  if (mode === 'buy') return buyApi(api)
  if (mode === 'sell') return sellApi(api)
  return tradeApi(api)
}

function buyApi(api: AdminApi): DealSessionApi {
  return {
    supports: { incoming: true, outgoing: false, costBasisMode: false },
    async create() {
      const res = await api.post<{ buy_id: string }>('/purchases', { payment_method: 'cash' })
      return res.buy_id
    },
    async addIncoming(id, leg) {
      // `POST /admin/purchases/{id}/items` accepts the same graded fields
      // `/trades/{id}/incoming` does (`kind`, `company`, `grade`,
      // `cert_number`, `grade_label`) — see `_GRADED_REQUIRED_FIELDS` in
      // `routers/admin/purchases.py`. Dropping them here silently downgraded
      // every graded Buy-mode leg to raw NM (final-review Critical 1).
      await api.post(`/purchases/${id}/items`, {
        name: leg.name,
        kind: leg.kind,
        condition: leg.kind === 'raw' ? (leg.condition ?? 'NM') : null,
        condition_modifier: null,
        buy_price: leg.agreed_value,
        market_value: null,
        set_name: leg.set_name ?? null,
        location: leg.location,
        number: leg.card_number ?? null,
        card_id: leg.card_id,
        manual_entry: leg.card_id === null,
        company: leg.kind === 'graded' ? leg.company : null,
        grade: leg.kind === 'graded' ? leg.grade : null,
        cert_number: leg.kind === 'graded' ? leg.cert_number : null,
        grade_label: leg.kind === 'graded' ? leg.grade_label : null,
      })
    },
    async addOutgoing() {
      throw new Error('A buy session has no outgoing leg')
    },
    async removeIncoming(id, index) {
      await api.del(`/purchases/${id}/items/${index}`)
    },
    async removeOutgoing() {
      throw new Error('A buy session has no outgoing leg')
    },
    async updateOutgoing() {
      throw new Error('A buy session has no outgoing leg')
    },
    async setCash() {
      // A buy takes one payment method, not a component list — the first
      // component (if any) is folded into `confirm`'s payment_method instead.
    },
    async confirm(id, meta) {
      await api.patch(`/purchases/${id}`, {
        payment_method: meta.payment_method ?? 'cash',
        counterparty: meta.counterparty ?? null,
        notes: meta.notes ?? null,
        purchase_date: meta.date ?? null,
      })
      return api.post<ConfirmResult>(`/purchases/${id}/confirm`)
    },
  }
}

function sellApi(api: AdminApi): DealSessionApi {
  return {
    supports: { incoming: false, outgoing: true, costBasisMode: false },
    async create() {
      const res = await api.post<{ sell_id: string }>('/sales', { payment_method: 'cash' })
      return res.sell_id
    },
    async addIncoming() {
      throw new Error('A sell session has no incoming leg')
    },
    async addOutgoing(id, item, value) {
      await api.post(`/sales/${id}/items`, {
        item_id: item.item_id,
        name: adminItemName(item, ''),
        agreed_price: value,
        original_price: item.current_market_value ?? null,
      })
    },
    async removeIncoming() {
      throw new Error('A sell session has no incoming leg')
    },
    async removeOutgoing(id, itemId) {
      await api.del(`/sales/${id}/items/${itemId}`)
    },
    async updateOutgoing(id, itemId, value) {
      await api.patch(`/sales/${id}/items/${itemId}`, { agreed_price: value })
    },
    async setCash() {
      // Same as buy — one payment method, carried through `confirm`.
    },
    async confirm(id, meta) {
      await api.patch(`/sales/${id}`, {
        payment_method: meta.payment_method ?? 'cash',
        counterparty: meta.counterparty ?? null,
        notes: meta.notes ?? null,
        sale_date: meta.date ?? null,
      })
      return api.post<ConfirmResult>(`/sales/${id}/confirm`)
    },
  }
}

function tradeApi(api: AdminApi): DealSessionApi {
  return {
    supports: { incoming: true, outgoing: true, costBasisMode: true },
    async create() {
      const res = await api.post<{ trade_id: string }>('/trades', {})
      return res.trade_id
    },
    async addIncoming(id, leg) {
      // The keys already mirror T13's `POST /admin/trades/{id}/incoming`
      // exactly (see `lib/trade-incoming-form.ts`), so the leg is sent as-is.
      await api.post(`/trades/${id}/incoming`, leg)
    },
    async addOutgoing(id, item, value) {
      await api.post(`/trades/${id}/outgoing`, {
        item_id: item.item_id,
        name: adminItemName(item, ''),
        agreed_value: value,
      })
    },
    async removeIncoming(id, index) {
      await api.del(`/trades/${id}/incoming/${index}`)
    },
    async removeOutgoing(id, itemId) {
      await api.del(`/trades/${id}/outgoing/${itemId}`)
    },
    async updateOutgoing(id, itemId, value) {
      await api.patch(`/trades/${id}/outgoing/${itemId}`, { agreed_value: value })
    },
    async setCash(id, components) {
      await api.put(`/trades/${id}/cash`, { cash_components: components })
    },
    async confirm(id, meta) {
      if (meta.basis_mode) {
        await api.patch(`/trades/${id}`, { basis_mode: meta.basis_mode })
      }
      if (meta.manual_basis !== undefined) {
        await api.patch(`/trades/${id}`, { manual_basis: meta.manual_basis })
      }
      await api.patch(`/trades/${id}`, {
        counterparty: meta.counterparty ?? null,
        trade_date: meta.date ?? null,
      })
      return api.post<ConfirmResult>(`/trades/${id}/confirm`)
    },
  }
}
