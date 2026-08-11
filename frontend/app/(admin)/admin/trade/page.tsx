'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { Plus, X, Check, Eye, EyeOff, DollarSign, Calendar, Banknote, CreditCard, Smartphone, Search, AlertTriangle, RefreshCw } from 'lucide-react'
import { useAdminApi, AdminApiError } from '@/lib/admin-api'
import { describeApiError, type ApiErrorDescription } from '@/lib/admin-error'
import CardImage, { TABLE_THUMB_SIZE } from '@/components/admin/shared/CardImage'
import CardPickerRow, { type PickerCard } from '@/components/admin/shared/CardPickerRow'
import { useCardImages } from '@/lib/use-card-images'
import SearchInput from '@/components/admin/shared/SearchInput'
import PriceDisplay from '@/components/admin/shared/PriceDisplay'
import ConfirmDialog from '@/components/admin/shared/ConfirmDialog'
import { availableModes, canConfirmBasis, type BasisMode } from '@/lib/trade-basis'
import { buildIncomingLegBody } from '@/lib/trade-incoming-form'
import MoneyInput from '@/components/admin/shared/MoneyInput'
import { formatMoneyInput, parseMoney } from '@/lib/money'
import { adminItemName } from '@/lib/admin-item-name'

interface TradeLeg {
  item_id?: string
  /**
   * The CATALOG card, for art on the staged row. Absent on a manually-typed
   * incoming leg (no catalog match) and on sealed/bulk stock — both render the
   * placeholder, which is the honest answer.
   */
  card_id?: string | null
  name: string
  card_number?: string
  set_name?: string
  market_value?: string | number
  value: string | number
}

interface CashComponent {
  direction: 'we_pay' | 'they_pay'
  amount: string
  payment_method: 'cash' | 'venmo' | 'zelle' | 'card'
}

interface TradeBalance {
  trade_id: string
  total_out_value: string
  total_in_value: string
  total_cost_basis: string
  cash_delta: string
  cash_components_net?: string
  margin_pct: string | null
  is_balanced: boolean
  basis_mode: BasisMode
  has_cash: boolean
  projected_basis_pool: string | null
  basis_mode_error: string | null
}

interface InventoryItem {
  item_id: string
  display_name?: string
  product_name?: string
  current_market_value?: string
  condition?: string
  [key: string]: unknown
}

interface IncomingCatalogCard extends PickerCard {
  prices?: Record<string, { market?: number | string | null }>
  [key: string]: unknown
}

const PAYMENT_METHOD_OPTIONS = [
  { value: 'cash', icon: Banknote, label: 'Cash' },
  { value: 'venmo', icon: Smartphone, label: 'Venmo' },
  { value: 'zelle', icon: DollarSign, label: 'Zelle' },
  { value: 'card', icon: CreditCard, label: 'Card' },
] as const

function todayISO() {
  return new Date().toISOString().split('T')[0]
}

export default function AdminTradePage() {
  const api = useAdminApi()

  const [tradeId, setTradeId] = useState<string | null>(null)
  const [outgoing, setOutgoing] = useState<TradeLeg[]>([])
  // Per-leg text for the outgoing value editors, keyed by item id. The editor
  // was uncontrolled before; a money field has to own its text so a half-typed
  // "1," is not thrown away on the next render.
  const [outDrafts, setOutDrafts] = useState<Record<string, string>>({})
  const [incoming, setIncoming] = useState<TradeLeg[]>([])
  const [cashComponents, setCashComponents] = useState<CashComponent[]>([])
  const [balance, setBalance] = useState<TradeBalance | null>(null)
  const [counterparty, setCounterparty] = useState('')
  const [customerView, setCustomerView] = useState(false)
  const [tradeDate, setTradeDate] = useState(todayISO())

  // Vendor mode toggle

  // Basis mode
  const [basisMode, setBasisMode] = useState<BasisMode>('transfer')
  const [manualBasis, setManualBasis] = useState('')

  // Search for outgoing items
  const [outSearch, setOutSearch] = useState('')
  const [outResults, setOutResults] = useState<InventoryItem[]>([])

  // Incoming form — expanded fields
  const [inForm, setInForm] = useState({
    name: '',
    card_number: '',
    set_name: '',
    market_value: '',
    value: '',
    percentage: '',
  })

  // Catalog lookup for the incoming-leg Name field
  const [incomingCatalogResults, setIncomingCatalogResults] = useState<IncomingCatalogCard[]>([])
  const [searchingIncomingCatalog, setSearchingIncomingCatalog] = useState(false)
  const [selectedIncomingCard, setSelectedIncomingCard] = useState<IncomingCatalogCard | null>(null)
  // The described failure, not a bare boolean: "it failed" cannot tell an
  // unreachable server from a 500, and guessing at that in the copy is what
  // sent the last investigation at the network instead of the task role.
  const [incomingCatalogError, setIncomingCatalogError] =
    useState<ApiErrorDescription | null>(null)
  // Bumping this re-runs the search effect for the name already typed.
  const [incomingRetryNonce, setIncomingRetryNonce] = useState(0)
  // Which search is current — see the Buy page for why: a slow catalog search
  // means several are in flight and they do not resolve in order.
  const incomingSearchSeqRef = useRef(0)

  // Art for both staged legs, batched in one request. Always on: a trade is
  // the one flow where cards move in BOTH directions at once, and the staged
  // lists are the last look before the swap is committed.
  const { getImageUrl } = useCardImages([
    ...incoming.map((i) => i.card_id),
    ...outgoing.map((o) => o.card_id),
  ])

  // Confirm
  const [showConfirm, setShowConfirm] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [confirmed, setConfirmed] = useState(false)

  // Create session
  useEffect(() => {
    if (!api.isAuthenticated || tradeId) return
    api.post<{ trade_id: string }>('/trades', {}).then((res) => {
      setTradeId(res.trade_id)
    })
  }, [api.isAuthenticated]) // eslint-disable-line react-hooks/exhaustive-deps

  // Search outgoing
  useEffect(() => {
    if (!outSearch.trim() || !api.isAuthenticated) { setOutResults([]); return }
    const timeout = setTimeout(async () => {
      try {
        const res = await api.get<{ items: InventoryItem[] }>('/inventory/search', { name: outSearch, status: 'available' })
        const ids = new Set(outgoing.map((o) => o.item_id))
        setOutResults(res.items.filter((i) => !ids.has(i.item_id)).slice(0, 8))
      } catch { setOutResults([]) }
    }, 300)
    return () => clearTimeout(timeout)
  }, [outSearch, api.isAuthenticated]) // eslint-disable-line react-hooks/exhaustive-deps

  // Search catalog for incoming-leg name autofill (round7-handoff §"set not
  // auto filling for coming in"). Skipped once a card is selected so the
  // resulting name-fill doesn't immediately re-trigger its own search.
  useEffect(() => {
    if (!inForm.name.trim() || !api.isAuthenticated || selectedIncomingCard) {
      setIncomingCatalogResults([])
      setIncomingCatalogError(null)
      return
    }
    const timeout = setTimeout(async () => {
      const seq = ++incomingSearchSeqRef.current
      setSearchingIncomingCatalog(true)
      setIncomingCatalogError(null)
      try {
        const res = await api.get<{ items: IncomingCatalogCard[] }>('/market/search', { name: inForm.name })
        if (seq !== incomingSearchSeqRef.current) return
        setIncomingCatalogResults(res.items.slice(0, 8))
      } catch (err) {
        if (seq !== incomingSearchSeqRef.current) return
        setIncomingCatalogResults([])
        setIncomingCatalogError(describeApiError(err))
      } finally {
        if (seq === incomingSearchSeqRef.current) setSearchingIncomingCatalog(false)
      }
    }, 300)
    return () => clearTimeout(timeout)
  }, [inForm.name, selectedIncomingCard, api.isAuthenticated, incomingRetryNonce]) // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch balance
  const fetchBalance = useCallback(async () => {
    if (!tradeId || !api.isAuthenticated) return
    try {
      const bal = await api.get<TradeBalance>(`/trades/${tradeId}/balance`)
      setBalance(bal)
      setBasisMode(bal.basis_mode ?? 'transfer')
    } catch { /* ignore */ }
  }, [tradeId, api])

  useEffect(() => { fetchBalance() }, [outgoing, incoming, cashComponents, fetchBalance])

  const addOutgoing = async (item: InventoryItem) => {
    if (!tradeId) return
    // Server-sent decimal string, not typed by anyone — parseFloat is safe.
    const value = item.current_market_value || '0'
    try {
      await api.post(`/trades/${tradeId}/outgoing`, {
        item_id: item.item_id,
        name: adminItemName(item, ''),
        agreed_value: parseFloat(value),
      })
      setOutgoing((prev) => [...prev, {
        item_id: item.item_id,
        card_id: typeof item.card_id === 'string' ? item.card_id : null,
        name: adminItemName(item, ''),
        value,
      }])
      setOutSearch('')
      setOutResults([])
    } catch (err) {
      alert(err instanceof AdminApiError ? err.detail : 'Failed to add')
    }
  }

  const removeOutgoing = async (idx: number) => {
    if (!tradeId) return
    const item = outgoing[idx]
    if (!item?.item_id) return
    try {
      await api.del(`/trades/${tradeId}/outgoing/${item.item_id}`)
      setOutgoing((prev) => prev.filter((_, i) => i !== idx))
      // Drop the leg's draft too: the map is keyed by item id, so re-adding the
      // same card would otherwise resurrect whatever was typed the first time.
      setOutDrafts((d) => {
        const next = { ...d }
        delete next[item.item_id as string]
        return next
      })
    } catch (err) {
      alert(err instanceof AdminApiError ? err.detail : 'Failed to remove')
    }
  }

  const updateOutgoingValue = async (idx: number, newValue: string) => {
    if (!tradeId) return
    const item = outgoing[idx]
    if (!item?.item_id) return
    // `=== null`, not falsiness: a $0 leg is legitimate in a trade.
    const parsed = parseMoney(newValue)
    if (parsed === null) return
    try {
      await api.patch(`/trades/${tradeId}/outgoing/${item.item_id}`, {
        agreed_value: parsed,
      })
      setOutgoing((prev) => prev.map((leg, i) => i === idx ? { ...leg, value: String(parsed) } : leg))
    } catch (err) {
      alert(err instanceof AdminApiError ? err.detail : 'Failed to update')
    }
  }

  // Bidirectional % ↔ value calculation for the incoming form. Both amounts are
  // typed by a human, so parseMoney; `percentage` is a bounded percent and
  // stays parseFloat.
  const handleIncomingValueChange = (newValue: string) => {
    const market = parseMoney(inForm.market_value) ?? 0
    const val = parseMoney(newValue) ?? 0
    let pct = ''
    if (market > 0 && val > 0) {
      pct = ((val / market) * 100).toFixed(0)
    }
    setInForm((f) => ({ ...f, value: newValue, percentage: pct }))
  }

  const handleIncomingPctChange = (newPct: string) => {
    const market = parseMoney(inForm.market_value) ?? 0
    const pctNum = parseFloat(newPct)
    let val = ''
    if (market > 0 && pctNum > 0) {
      val = ((market * pctNum) / 100).toFixed(2)
    }
    setInForm((f) => ({ ...f, percentage: newPct, value: val }))
  }

  const selectIncomingCatalogCard = (card: IncomingCatalogCard) => {
    setSelectedIncomingCard(card)
    let marketPrice = ''
    if (card.prices) {
      for (const finish of Object.values(card.prices)) {
        if (finish?.market) { marketPrice = String(finish.market); break }
      }
    }
    setInForm((f) => ({
      ...f,
      name: card.name,
      set_name: card.set_name || card.set_id || '',
      card_number: card.number || '',
      market_value: marketPrice,
    }))
    setIncomingCatalogResults([])
  }

  const addIncoming = async () => {
    // `=== null`, not falsiness — a $0 leg is legitimate in a trade.
    if (!tradeId || !inForm.name.trim() || parseMoney(inForm.value) === null) return
    // A market value that was typed but cannot be read blocks the add rather
    // than being silently dropped from the body.
    if (inForm.market_value.trim() !== '' && parseMoney(inForm.market_value) === null) return
    try {
      const body = buildIncomingLegBody(inForm, selectedIncomingCard)
      await api.post(`/trades/${tradeId}/incoming`, body)
      setIncoming((prev) => [...prev, {
        name: inForm.name.trim(),
        // Only set when the admin picked a catalog match — a hand-typed leg
        // has no card behind it and must not borrow one.
        card_id: selectedIncomingCard?.card_id ?? null,
        card_number: inForm.card_number.trim(),
        set_name: inForm.set_name.trim(),
        market_value: inForm.market_value,
        value: inForm.value,
      }])
      setInForm({ name: '', card_number: '', set_name: '', market_value: '', value: '', percentage: '' })
      setSelectedIncomingCard(null)
      setIncomingCatalogResults([])
    } catch (err) {
      alert(err instanceof AdminApiError ? err.detail : 'Failed to add')
    }
  }

  const removeIncoming = async (idx: number) => {
    if (!tradeId) return
    try {
      await api.del(`/trades/${tradeId}/incoming/${idx}`)
      setIncoming((prev) => prev.filter((_, i) => i !== idx))
    } catch (err) {
      alert(err instanceof AdminApiError ? err.detail : 'Failed to remove')
    }
  }

  // Multi-asset cash components
  const addCashComponent = () => {
    setCashComponents((prev) => [...prev, { direction: 'they_pay', amount: '', payment_method: 'cash' }])
  }

  const updateCashComponent = (idx: number, updates: Partial<CashComponent>) => {
    setCashComponents((prev) => prev.map((c, i) => i === idx ? { ...c, ...updates } : c))
  }

  const removeCashComponent = (idx: number) => {
    setCashComponents((prev) => prev.filter((_, i) => i !== idx))
  }

  const syncCashComponents = async () => {
    if (!tradeId) return
    // Filter out empty amounts
    // Filter out empty and unreadable amounts. parseMoney, not parseFloat:
    // `1,300` would otherwise pass the `> 0` test as 1 and be sent as 1.
    const validComponents = cashComponents
      .map((c) => ({ ...c, parsed: parseMoney(c.amount) }))
      .filter((c) => c.parsed !== null && c.parsed > 0)
      .map((c) => ({
        direction: c.direction,
        amount: c.parsed as number,
        payment_method: c.payment_method,
      }))
    try {
      await api.put(`/trades/${tradeId}/cash`, {
        cash_components: validComponents,
      })
      fetchBalance()
    } catch (err) {
      alert(err instanceof AdminApiError ? err.detail : 'Failed to update cash')
    }
  }

  // Basis mode sync
  const syncBasisMode = async (mode: BasisMode) => {
    if (!tradeId) return
    try {
      await api.patch(`/trades/${tradeId}`, { basis_mode: mode })
      fetchBalance()
    } catch (err) {
      alert(err instanceof AdminApiError ? err.detail : 'Failed to update basis mode')
    }
  }

  const syncManualBasis = async (value: string) => {
    if (!tradeId) return
    // This used to send the raw text straight through — no parse at all, safe
    // only while the field was type="number" and could not hold a comma.
    const parsed = parseMoney(value)
    if (parsed === null) return
    try {
      await api.patch(`/trades/${tradeId}`, { manual_basis: String(parsed) })
      fetchBalance()
    } catch (err) {
      alert(err instanceof AdminApiError ? err.detail : 'Failed to update manual basis')
    }
  }

  const handleConfirm = async () => {
    if (!tradeId) return
    setConfirming(true)
    try {
      // Sync cash before confirming
      await syncCashComponents()
      await api.patch(`/trades/${tradeId}`, {
        counterparty: counterparty || null,
        trade_date: tradeDate || null,
      })
      await api.post(`/trades/${tradeId}/confirm`)
      setConfirmed(true)
      setShowConfirm(false)
    } catch (err) {
      alert(err instanceof AdminApiError ? err.detail : 'Failed to confirm')
    } finally {
      setConfirming(false)
    }
  }

  const startNew = () => {
    setTradeId(null)
    setOutgoing([])
    setOutDrafts({})
    setIncoming([])
    setCashComponents([])
    setBalance(null)
    setCounterparty('')
    setConfirmed(false)
    setTradeDate(todayISO())
    setBasisMode('transfer')
    setManualBasis('')
    setSelectedIncomingCard(null)
    setIncomingCatalogResults([])
  }

  // Every one of these reads a value that reached state from a typed field, so
  // all three go through parseMoney — parseFloat would make each total wrong by
  // three orders of magnitude on a comma, and never NaN enough to notice.
  const outTotal = outgoing.reduce((s, i) => s + (parseMoney(String(i.value ?? '0')) ?? 0), 0)
  const inTotal = incoming.reduce((s, i) => s + (parseMoney(String(i.value ?? '0')) ?? 0), 0)
  const cashNet = cashComponents.reduce((s, c) => {
    const amt = parseMoney(c.amount || '0') ?? 0
    return s + (c.direction === 'they_pay' ? amt : -amt)
  }, 0)

  if (confirmed) {
    return (
      <div className="p-6 lg:p-8 max-w-3xl">
        <div className="vault-panel rounded-xl p-8 text-center">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-full bg-spriggatito-300/15 text-spriggatito-300 mb-4">
            <Check size={28} />
          </div>
          <h2 className="text-lg font-semibold text-pine-100 mb-1">Trade Confirmed</h2>
          <p className="text-sm text-pine-300 mb-4">Trade executed successfully.</p>
          <button type="button" onClick={startNew} className="px-4 py-2 rounded-lg text-xs font-medium bg-mint/15 text-mint border border-mint/30 hover:bg-mint/25 transition-colors">
            Start New Trade
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="p-6 lg:p-8 max-w-7xl">
      <header className="flex items-center justify-between mb-6">
        <div>
          <span className="font-mono text-[11px] uppercase tracking-[0.22em] text-spriggatito-300/70">Trade</span>
          <h1 className="text-xl font-semibold text-pine-100">Trade Calculator</h1>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setCustomerView((v) => !v)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${customerView ? 'bg-amber-500/15 text-amber-400 border-amber-500/30' : 'text-pine-400 border-pine-700/40 hover:border-pine-600'}`}
          >
            {customerView ? <EyeOff size={13} /> : <Eye size={13} />}
            {customerView ? 'Admin View' : 'Customer View'}
          </button>
        </div>
      </header>

      {/* Basis mode selector — the live cost-basis control, rendered
          unconditionally by design (Round 3 OWNER RULING 2026-08-04). */}
      <div className="mb-4 vault-panel rounded-xl p-3">
        <div className="flex items-center gap-4 flex-wrap">
          <span className="text-[11px] text-pine-400 uppercase tracking-wider font-medium">Cost Basis Mode</span>
          <div className="flex items-center gap-1">
            {availableModes(balance?.has_cash ?? false).map(({ mode, disabled, reason }) => (
              <button
                key={mode}
                type="button"
                disabled={disabled}
                title={reason ?? undefined}
                onClick={() => {
                  setBasisMode(mode)
                  syncBasisMode(mode)
                }}
                className={`px-3 py-1 rounded-lg text-xs font-medium border transition-colors ${
                  basisMode === mode
                    ? 'bg-spriggatito-300/15 text-spriggatito-300 border-spriggatito-300/30'
                    : 'text-pine-400 border-pine-700/40 hover:border-pine-600'
                } disabled:opacity-40 disabled:cursor-not-allowed`}
              >
                {mode.charAt(0).toUpperCase() + mode.slice(1)}
              </button>
            ))}
          </div>
          {balance?.projected_basis_pool !== undefined && balance.projected_basis_pool !== null && (
            <span className="text-[10px] text-pine-300 ml-auto font-mono">
              Incoming cost basis: ${balance.projected_basis_pool}
            </span>
          )}
        </div>
        {basisMode === 'manual' && (
          <div className="mt-2 flex items-center gap-2">
            <label className="text-[10px] text-pine-400 uppercase tracking-wider">Total cost basis</label>
            <div className="relative flex flex-col">
              <DollarSign size={10} className="absolute left-1.5 top-2.5 -translate-y-1/2 text-pine-500" />
              <MoneyInput
                label="Total cost basis"
                value={manualBasis}
                onChange={(raw) => setManualBasis(raw)}
                onBlur={() => syncManualBasis(manualBasis)}
                onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
                className="vault-field w-28 pl-5 pr-2 py-1 rounded-lg text-xs font-mono"
                placeholder="0.00"
              />
            </div>
          </div>
        )}
        {balance?.basis_mode_error && (
          <div className="mt-2 text-[10px] text-amber-400">
            {balance.basis_mode_error}
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* LEFT: Coming In (Their cards) */}
        <div className="space-y-3">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-mint">Coming In (Theirs)</h3>

          {/* Incoming form */}
          <div className="vault-panel rounded-xl p-3 space-y-2">
            <div className="grid grid-cols-6 gap-2">
              <div className="col-span-2 relative">
                <label className="text-[10px] text-pine-400 uppercase tracking-wider block mb-0.5">Card Name</label>
                <div className="relative">
                  <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-pine-500 pointer-events-none" />
                  <input
                    value={inForm.name}
                    onChange={(e) => {
                      const val = e.target.value
                      setInForm((f) => ({ ...f, name: val }))
                      if (selectedIncomingCard) setSelectedIncomingCard(null)
                    }}
                    placeholder="Name"
                    className="vault-field w-full pl-6 pr-2 py-1.5 rounded-lg text-xs"
                    autoComplete="off"
                  />
                </div>
                {!selectedIncomingCard && incomingCatalogResults.length > 0 && (
                  <div className="absolute z-20 left-0 right-0 mt-1 vault-panel rounded-lg border border-pine-700/50 max-h-[28rem] overflow-y-auto vault-scroll shadow-xl">
                    {incomingCatalogResults.map((card) => (
                      <CardPickerRow
                        key={card.card_id}
                        card={card}
                        onSelect={selectIncomingCatalogCard}
                      />
                    ))}
                    {searchingIncomingCatalog && (
                      <div className="px-3 py-2 text-[10px] text-pine-500">Searching&hellip;</div>
                    )}
                  </div>
                )}
                {/* Search failed — deliberately distinct from "no match" */}
                {!selectedIncomingCard && incomingCatalogError && !searchingIncomingCatalog && (
                  <div className="mt-1 space-y-1">
                    <div className="flex items-start gap-1.5 text-[10px] text-red-400">
                      <AlertTriangle size={11} className="flex-shrink-0 mt-px" />
                      <span>{incomingCatalogError.message}</span>
                    </div>
                    {incomingCatalogError.retryable && (
                      <button
                        type="button"
                        onClick={() => setIncomingRetryNonce((n) => n + 1)}
                        className="flex items-center gap-1 text-[10px] text-pine-300 hover:text-mint transition-colors"
                      >
                        <RefreshCw size={10} />
                        Retry
                      </button>
                    )}
                  </div>
                )}
                {!selectedIncomingCard && !incomingCatalogError && !searchingIncomingCatalog && incomingCatalogResults.length === 0 && inForm.name.trim().length >= 3 && (
                  <div className="mt-1 flex items-center gap-1.5 text-[10px] text-amber-400">
                    <AlertTriangle size={11} className="flex-shrink-0" />
                    No catalog match — fields below can still be filled in manually.
                  </div>
                )}
              </div>
              <div>
                <label className="text-[10px] text-pine-400 uppercase tracking-wider block mb-0.5">Number</label>
                <input
                  value={inForm.card_number}
                  onChange={(e) => setInForm((f) => ({ ...f, card_number: e.target.value }))}
                  placeholder="#"
                  className="vault-field w-full px-2 py-1.5 rounded-lg text-xs"
                />
              </div>
              <div>
                <label className="text-[10px] text-pine-400 uppercase tracking-wider block mb-0.5">Set</label>
                <input
                  value={inForm.set_name}
                  onChange={(e) => setInForm((f) => ({ ...f, set_name: e.target.value }))}
                  placeholder="Set"
                  className="vault-field w-full px-2 py-1.5 rounded-lg text-xs"
                />
              </div>
              <div>
                <label className="text-[10px] text-pine-400 uppercase tracking-wider block mb-0.5">Market</label>
                <MoneyInput
                  label="Incoming market value"
                  value={inForm.market_value}
                  onChange={(raw) => setInForm((f) => ({ ...f, market_value: raw }))}
                  placeholder="$"
                  className="vault-field w-full px-2 py-1.5 rounded-lg text-xs"
                />
              </div>
              <div className="flex items-end gap-1">
                <div className="flex-1">
                  <label className="text-[10px] font-semibold text-mint uppercase tracking-wider block mb-0.5 bg-mint/10 rounded px-1 text-center">Value</label>
                  <MoneyInput
                    value={inForm.value}
                    onChange={(raw) => handleIncomingValueChange(raw)}
                    placeholder="$"
                    // Three inputs on this row share the "$" placeholder, so
                    // the visible label has to be carried to the a11y tree too.
                    label="Trade-in value"
                    className="vault-field w-full px-2 py-1.5 rounded-lg text-xs"
                  />
                </div>
              </div>
            </div>
            <div className="flex items-end gap-2">
              <div className="w-20">
                <label className="text-[10px] font-semibold text-mint uppercase tracking-wider block mb-0.5 bg-mint/10 rounded px-1 text-center">%</label>
                <input
                  type="number"
                  step="1"
                  value={inForm.percentage}
                  onChange={(e) => handleIncomingPctChange(e.target.value)}
                  placeholder="%"
                  className="vault-field w-full px-2 py-1.5 rounded-lg text-xs"
                />
              </div>
              <button
                type="button"
                onClick={addIncoming}
                disabled={!inForm.name.trim() || !inForm.value}
                // Icon-only control: without a name it reads as just "button".
                aria-label="Add incoming card"
                className="p-1.5 rounded-lg bg-mint/15 text-mint border border-mint/30 disabled:opacity-40 hover:bg-mint/25 transition-colors"
              >
                <Plus size={14} />
              </button>
            </div>
          </div>

          {/* Incoming list */}
          <div className="vault-panel rounded-xl overflow-hidden">
            {incoming.length === 0 ? (
              <div className="p-4 text-center text-xs text-pine-500">No items coming in yet</div>
            ) : (
              <div className="divide-y divide-pine-700/25">
                {incoming.map((item, idx) => (
                  <div key={idx} className="flex items-center gap-2.5 px-3 py-2">
                    <CardImage
                      imageUrl={getImageUrl(item.card_id)}
                      alt={item.name}
                      size={TABLE_THUMB_SIZE}
                    />
                    <div className="min-w-0 flex-1">
                      <span className="text-xs text-pine-200 truncate block">
                        {item.name}
                        {item.card_number && <span className="text-pine-500"> #{item.card_number}</span>}
                      </span>
                      {item.set_name && (
                        <span className="text-[10px] text-pine-500 truncate block">{item.set_name}</span>
                      )}
                    </div>
                    <div className="flex items-center gap-2 flex-shrink-0">
                      <PriceDisplay value={item.value} className="text-xs text-mint" />
                      <button type="button" onClick={() => removeIncoming(idx)} className="p-1 text-pine-500 hover:text-red-400"><X size={12} /></button>
                    </div>
                  </div>
                ))}
              </div>
            )}
            <div className="px-3 py-2 border-t border-pine-700/30 text-right text-xs text-pine-400">
              In: <span className="font-mono text-mint">${inTotal.toFixed(2)}</span>
            </div>
          </div>
        </div>

        {/* RIGHT: Going Out (Our cards) */}
        <div className="space-y-3">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-red-400">Going Out (Ours)</h3>
          <SearchInput value={outSearch} onChange={setOutSearch} placeholder="Search our inventory…" />
          {outSearch && outResults.length > 0 && (
            <div className="vault-panel rounded-lg divide-y divide-pine-700/30 max-h-40 overflow-y-auto vault-scroll">
              {outResults.map((item) => (
                <button key={item.item_id} type="button" onClick={() => addOutgoing(item)} className="w-full flex items-center justify-between px-3 py-2 hover:bg-pine-800/50 text-left text-xs">
                  <span className="text-pine-100 truncate">{adminItemName(item)}</span>
                  <span className="text-pine-400 ml-2"><PriceDisplay value={item.current_market_value} className="text-[10px] inline" /></span>
                </button>
              ))}
            </div>
          )}
          <div className="vault-panel rounded-xl overflow-hidden">
            {outgoing.length === 0 ? (
              <div className="p-4 text-center text-xs text-pine-500">No items going out yet</div>
            ) : (
              <div className="divide-y divide-pine-700/25">
                {outgoing.map((item, idx) => (
                  <div key={idx} className="flex items-center gap-2.5 px-3 py-2">
                    <CardImage
                      imageUrl={getImageUrl(item.card_id)}
                      alt={item.name}
                      size={TABLE_THUMB_SIZE}
                    />
                    <span className="text-xs text-pine-200 truncate flex-1 min-w-0">{item.name}</span>
                    <div className="flex items-center gap-2 flex-shrink-0">
                      <span className="text-[10px] text-pine-500">$</span>
                      <MoneyInput
                        label={`Outgoing value for ${item.name}`}
                        // Controlled now: MoneyInput has to own its text so a
                        // half-typed "1," survives the render, which is why the
                        // drafts map exists instead of the old defaultValue.
                        value={outDrafts[item.item_id ?? String(idx)] ?? formatMoneyInput(parseMoney(String(item.value)) ?? 0)}
                        onChange={(raw) => setOutDrafts((d) => ({ ...d, [item.item_id ?? String(idx)]: raw }))}
                        onBlur={() => {
                          const draft = outDrafts[item.item_id ?? String(idx)]
                          if (draft === undefined) return
                          const parsed = parseMoney(draft)
                          if (parsed === null || parsed === parseMoney(String(item.value))) return
                          updateOutgoingValue(idx, draft)
                        }}
                        onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
                        className="vault-field w-20 px-1.5 py-0.5 rounded text-xs text-right text-red-400 font-mono"
                      />
                      <button type="button" onClick={() => removeOutgoing(idx)} className="p-1 text-pine-500 hover:text-red-400"><X size={12} /></button>
                    </div>
                  </div>
                ))}
              </div>
            )}
            <div className="px-3 py-2 border-t border-pine-700/30 text-right text-xs text-pine-400">
              Out: <span className="font-mono text-red-400">${outTotal.toFixed(2)}</span>
            </div>
          </div>
        </div>
      </div>

      {/* Cash Components + Balance */}
      <div className="mt-6 vault-panel rounded-xl p-4">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {/* Multi-asset cash components */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-[11px] text-pine-400 uppercase tracking-wider">Cash Components</span>
              <button
                type="button"
                onClick={addCashComponent}
                className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-pine-800/60 text-pine-300 border border-pine-700/40 hover:border-pine-600 transition-colors"
              >
                <Plus size={10} /> Add
              </button>
            </div>
            {cashComponents.length === 0 ? (
              <p className="text-[10px] text-pine-500">No cash in this trade</p>
            ) : (
              <div className="space-y-1.5">
                {cashComponents.map((comp, idx) => (
                  <div key={idx} className="flex items-center gap-1.5">
                    <select
                      value={comp.direction}
                      onChange={(e) => updateCashComponent(idx, { direction: e.target.value as CashComponent['direction'] })}
                      className="vault-field px-1.5 py-1 rounded text-[10px] w-[80px]"
                    >
                      <option value="they_pay">They pay</option>
                      <option value="we_pay">We pay</option>
                    </select>
                    <select
                      value={comp.payment_method}
                      onChange={(e) => updateCashComponent(idx, { payment_method: e.target.value as CashComponent['payment_method'] })}
                      className="vault-field px-1.5 py-1 rounded text-[10px] w-[72px]"
                    >
                      {PAYMENT_METHOD_OPTIONS.map((opt) => (
                        <option key={opt.value} value={opt.value}>{opt.label}</option>
                      ))}
                    </select>
                    <div className="relative flex-1">
                      <DollarSign size={10} className="absolute left-1.5 top-1/2 -translate-y-1/2 text-pine-500" />
                      <MoneyInput
                        label={`Cash amount ${idx + 1}`}
                        value={comp.amount}
                        onChange={(raw) => updateCashComponent(idx, { amount: raw })}
                        onBlur={syncCashComponents}
                        className="vault-field w-full pl-5 pr-1.5 py-1 rounded text-[10px] font-mono"
                        placeholder="0.00"
                      />
                    </div>
                    <button type="button" onClick={() => { removeCashComponent(idx); syncCashComponents() }} className="p-0.5 text-pine-500 hover:text-red-400">
                      <X size={10} />
                    </button>
                  </div>
                ))}
              </div>
            )}
            {cashComponents.length > 0 && (
              <div className="text-[10px] text-pine-400 pt-1 border-t border-pine-700/20">
                Net cash: <span className={`font-mono ${cashNet >= 0 ? 'text-mint' : 'text-red-400'}`}>
                  {cashNet >= 0 ? '+' : ''}${cashNet.toFixed(2)}
                </span>
              </div>
            )}
          </div>

          {/* Balance indicator */}
          <div className="text-center flex flex-col justify-center">
            <span className="text-[11px] text-pine-400 uppercase tracking-wider block mb-1">Balance</span>
            <div className="text-2xl font-mono font-semibold text-pine-100">
              {balance ? (() => {
                // Every figure below comes off the server's balance response.
                const out = parseFloat(balance.total_out_value)
                const inc = parseFloat(balance.total_in_value)
                const cash = balance.cash_components_net ? parseFloat(balance.cash_components_net) : parseFloat(balance.cash_delta)
                const net = inc + cash - out
                return `${net >= 0 ? '+' : ''}$${net.toFixed(2)}`
              })() : '$0.00'}
            </div>
            {balance && (
              <span className={`text-[10px] ${balance.is_balanced ? 'text-mint' : 'text-amber-400'}`}>
                {balance.is_balanced ? 'Balanced' : 'Unbalanced'}
              </span>
            )}
          </div>

          {/* Profit (admin only) */}
          {!customerView && (
            <div className="text-right flex flex-col justify-center">
              <span className="text-[11px] text-pine-400 uppercase tracking-wider block mb-1">Our Profit</span>
              {balance ? (() => {
                const totalIn = parseFloat(balance.total_in_value)
                const cashDelta = balance.cash_components_net ? parseFloat(balance.cash_components_net) : parseFloat(balance.cash_delta)
                const costBasis = parseFloat(balance.total_cost_basis)
                const dollarProfit = totalIn + cashDelta - costBasis
                const pctProfit = balance.margin_pct ? parseFloat(balance.margin_pct) : null
                const color = dollarProfit >= 0 ? 'text-mint' : 'text-red-400'
                return (
                  <div>
                    <div className={`text-lg font-mono ${color}`}>
                      {dollarProfit >= 0 ? '+' : ''}${dollarProfit.toFixed(2)}
                    </div>
                    {pctProfit !== null && (
                      <div className={`text-xs font-mono ${color}`}>
                        {pctProfit >= 0 ? '+' : ''}{pctProfit.toFixed(1)}%
                      </div>
                    )}
                  </div>
                )
              })() : (
                <div className="text-lg font-mono text-pine-500">—</div>
              )}
            </div>
          )}
        </div>

        {/* Date + Counterparty + Confirm */}
        <div className="mt-4 flex items-center gap-3">
          <div className="relative">
            <Calendar size={13} className="absolute left-2 top-1/2 -translate-y-1/2 text-pine-400" />
            <input
              type="date"
              value={tradeDate}
              onChange={(e) => setTradeDate(e.target.value)}
              className="vault-field pl-7 pr-2 py-1.5 rounded-lg text-xs w-36"
            />
          </div>
          <input value={counterparty} onChange={(e) => setCounterparty(e.target.value)} placeholder="Trading with (name)" className="vault-field flex-1 px-2.5 py-1.5 rounded-lg text-xs" />
          <button
            type="button"
            onClick={() => setShowConfirm(true)}
            disabled={(outgoing.length === 0 && incoming.length === 0) || !canConfirmBasis(basisMode, balance?.has_cash ?? false, manualBasis)}
            className="px-4 py-2 rounded-lg text-xs font-medium bg-spriggatito-300/15 text-spriggatito-300 border border-spriggatito-300/30 hover:bg-spriggatito-300/25 disabled:opacity-40 transition-colors"
          >
            Confirm Trade
          </button>
        </div>
      </div>

      <ConfirmDialog
        open={showConfirm}
        title="Confirm Trade"
        description={`Execute trade: ${outgoing.length} card${outgoing.length !== 1 ? 's' : ''} out, ${incoming.length} card${incoming.length !== 1 ? 's' : ''} in${cashComponents.length > 0 ? ` + ${cashComponents.length} cash component${cashComponents.length !== 1 ? 's' : ''}` : ''}?`}
        confirmLabel="Execute Trade"
        loading={confirming}
        onConfirm={handleConfirm}
        onCancel={() => setShowConfirm(false)}
      />
    </div>
  )
}
