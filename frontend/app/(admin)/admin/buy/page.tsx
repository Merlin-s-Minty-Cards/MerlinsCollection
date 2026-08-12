'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { ShoppingBag, Plus, X, Check, Banknote, CreditCard, Smartphone, DollarSign, Calendar, Search, AlertTriangle, ArrowLeft, PenLine, RefreshCw } from 'lucide-react'
import { useAdminApi, AdminApiError } from '@/lib/admin-api'
import { describeApiError, type ApiErrorDescription } from '@/lib/admin-error'
import { CONDITION_OPTIONS, parseCondition } from '@/lib/constants'
import { useLocations } from '@/lib/use-locations'
import { buyFormMode, buildBuyItemBody } from '@/lib/buy-form'
import { parseMoney } from '@/lib/money'
import { todayLocal } from '@/lib/dates'
import PriceDisplay from '@/components/admin/shared/PriceDisplay'
import ConfirmDialog from '@/components/admin/shared/ConfirmDialog'
import CardImage from '@/components/admin/shared/CardImage'
import CardPickerRow, { type PickerCard } from '@/components/admin/shared/CardPickerRow'
import MoneyInput from '@/components/admin/shared/MoneyInput'

interface BuyItem {
  name: string
  condition: string
  buy_price: string
  market_value: string
  set_name: string
  location: string
  card_number: string
  buy_pct: string
  image_url?: string | null
  is_catalog_match?: boolean
}

interface CatalogCard extends PickerCard {
  artist?: string
  prices?: Record<string, { market?: number | string | null }>
  [key: string]: unknown
}

export default function AdminBuyPage() {
  const api = useAdminApi()
  const { options: locationOptions } = useLocations()

  // Session
  const [buyId, setBuyId] = useState<string | null>(null)
  const [items, setItems] = useState<BuyItem[]>([])
  const [paymentMethod, setPaymentMethod] = useState('cash')
  const [counterparty, setCounterparty] = useState('')
  const [notes, setNotes] = useState('')
  const [buyDate, setBuyDate] = useState(todayLocal())

  // Card name search (catalog lookup)
  const [nameSearch, setNameSearch] = useState('')
  const [catalogResults, setCatalogResults] = useState<CatalogCard[]>([])
  const [searchingCatalog, setSearchingCatalog] = useState(false)
  const [selectedCard, setSelectedCard] = useState<CatalogCard | null>(null)
  const [catalogSearchDone, setCatalogSearchDone] = useState(false)
  // Described, not a bare boolean — see the note in lib/admin-error.ts.
  const [catalogError, setCatalogError] = useState<ApiErrorDescription | null>(null)
  // Which search is current. A catalog search can take seconds, so several are
  // in flight at once while the owner types and they do NOT come back in the
  // order they were sent — without this, the response for "Pik" can land last
  // and replace the results for "Pikachu".
  const searchSeqRef = useRef(0)

  // Manual mode toggle
  const [manualMode, setManualMode] = useState(false)

  // Form for adding
  const [form, setForm] = useState<BuyItem>({
    name: '',
    condition: 'NM',
    buy_price: '',
    market_value: '',
    set_name: '',
    location: 'toploader',
    card_number: '',
    buy_pct: '',
    image_url: null,
  })

  // Compute current form mode
  const mode = buyFormMode(selectedCard, manualMode)

  // Search catalog for card name dropdown
  const searchCatalog = useCallback(async (q: string) => {
    if (!q.trim() || !api.isAuthenticated) {
      setCatalogResults([])
      setCatalogSearchDone(false)
      setCatalogError(null)
      return
    }
    const seq = ++searchSeqRef.current
    setSearchingCatalog(true)
    setCatalogError(null)
    try {
      const res = await api.get<{ items: CatalogCard[]; total: number }>('/market/search', { name: q })
      if (seq !== searchSeqRef.current) return
      setCatalogResults(res.items.slice(0, 12))
      setCatalogSearchDone(true)
    } catch (err) {
      if (seq !== searchSeqRef.current) return
      // `catalogSearchDone` stays false so the "unknown card" notice cannot
      // fire: a request that threw is not evidence the catalog lacks the card,
      // and showing it as one is what made this impossible to diagnose.
      setCatalogResults([])
      setCatalogSearchDone(false)
      setCatalogError(describeApiError(err))
    } finally {
      if (seq === searchSeqRef.current) setSearchingCatalog(false)
    }
  }, [api])

  useEffect(() => {
    if (!nameSearch.trim()) {
      setCatalogResults([])
      setCatalogError(null)
      return
    }
    const timeout = setTimeout(() => searchCatalog(nameSearch), 300)
    return () => clearTimeout(timeout)
  }, [nameSearch, searchCatalog])

  // Select a catalog card to pre-fill form
  const selectCatalogCard = (card: CatalogCard) => {
    setSelectedCard(card)
    setManualMode(false)
    setCatalogSearchDone(false)
    // Extract best market price from prices dict
    let marketPrice = ''
    if (card.prices) {
      for (const finish of Object.values(card.prices)) {
        if (finish?.market) {
          marketPrice = String(finish.market)
          break
        }
      }
    }
    setForm((f) => ({
      ...f,
      name: card.name,
      set_name: card.set_name || card.set_id || '',
      card_number: card.number || '',
      market_value: marketPrice,
      image_url: card.images?.small || null,
      // Recalculate buy_price if percentage is set
      // `marketPrice` came off a catalog card (a server number), `buy_pct` is
      // a bounded percent — neither can be comma-grouped, but the money side
      // goes through parseMoney anyway so one rule covers the whole file.
      buy_price: f.buy_pct && marketPrice
        ? ((parseFloat(f.buy_pct) / 100) * (parseMoney(marketPrice) ?? 0)).toFixed(2)
        : f.buy_price,
    }))
    setNameSearch('')
    setCatalogResults([])
  }

  // Bidirectional percentage calculation. Both money fields are typed by a
  // human, so every read of them goes through parseMoney — parseFloat('1,300')
  // is 1 and never NaN, which would quietly recompute the percentage off a
  // number 1300× too small. `buy_pct` is a bounded percent and stays parseFloat.
  const updateBuyPrice = (price: string) => {
    setForm((f) => {
      const newForm = { ...f, buy_price: price }
      const priceNum = parseMoney(price)
      const marketNum = parseMoney(f.market_value)
      if (priceNum !== null && marketNum) {
        newForm.buy_pct = ((priceNum / marketNum) * 100).toFixed(0)
      } else {
        newForm.buy_pct = ''
      }
      return newForm
    })
  }

  const updateBuyPct = (pct: string) => {
    setForm((f) => {
      const newForm = { ...f, buy_pct: pct }
      const marketNum = parseMoney(f.market_value)
      if (pct && marketNum !== null) {
        newForm.buy_price = ((parseFloat(pct) / 100) * marketNum).toFixed(2)
      } else {
        newForm.buy_price = ''
      }
      return newForm
    })
  }

  const updateMarketValue = (mv: string) => {
    setForm((f) => {
      const newForm = { ...f, market_value: mv }
      const marketNum = parseMoney(mv)
      if (f.buy_pct && marketNum !== null) {
        newForm.buy_price = ((parseFloat(f.buy_pct) / 100) * marketNum).toFixed(2)
      }
      return newForm
    })
  }

  // Confirm
  const [showConfirm, setShowConfirm] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [confirmed, setConfirmed] = useState(false)
  const [confirmResult, setConfirmResult] = useState<{ items_created: number; total_cost: string } | null>(null)

  // Create session on mount
  useEffect(() => {
    if (!api.isAuthenticated || buyId) return
    api.post<{ buy_id: string }>('/purchases', { payment_method: 'cash' }).then((res) => {
      setBuyId(res.buy_id)
    })
  }, [api.isAuthenticated]) // eslint-disable-line react-hooks/exhaustive-deps

  const addItem = async () => {
    // `=== null`, never falsiness: parseMoney('0') is 0, and a free card is a
    // real thing at a buy table (a throw-in, a bulk lot).
    const buyPrice = parseMoney(form.buy_price)
    const marketRaw = form.market_value.trim()
    const marketValue = marketRaw === '' ? null : parseMoney(marketRaw)
    if (!buyId || !form.name.trim() || buyPrice === null) return
    // A market value that was typed but cannot be read must block the add, not
    // silently become null — that would look like "no market value known".
    if (marketRaw !== '' && marketValue === null) return
    try {
      const body = buildBuyItemBody(
        {
          name: form.name.trim(),
          ...parseCondition(form.condition),
          buy_price: buyPrice,
          market_value: marketValue,
          set_name: form.set_name || null,
          location: form.location,
          number: form.card_number || null,
        },
        selectedCard,
        manualMode,
      )
      await api.post(`/purchases/${buyId}/items`, body)
      // Store the CANONICAL amounts in the cart, not the raw text: the totals
      // and the per-row percentage below read these back, and '1,300' would
      // reduce to 1 in every one of them.
      setItems((prev) => [...prev, {
        ...form,
        buy_price: String(buyPrice),
        market_value: marketValue === null ? '' : String(marketValue),
        is_catalog_match: !!selectedCard,
      }])
      setForm({ name: '', condition: 'NM', buy_price: '', market_value: '', set_name: '', location: 'toploader', card_number: '', buy_pct: '', image_url: null })
      setSelectedCard(null)
      setManualMode(false)
      setCatalogSearchDone(false)
    } catch (err) {
      alert(err instanceof AdminApiError ? err.detail : 'Failed to add item')
    }
  }

  const removeItem = async (idx: number) => {
    if (!buyId) return
    try {
      await api.del(`/purchases/${buyId}/items/${idx}`)
      setItems((prev) => prev.filter((_, i) => i !== idx))
    } catch (err) {
      alert(err instanceof AdminApiError ? err.detail : 'Failed to remove item')
    }
  }

  const handleConfirm = async () => {
    if (!buyId) return
    setConfirming(true)
    try {
      await api.patch(`/purchases/${buyId}`, {
        payment_method: paymentMethod,
        counterparty: counterparty || null,
        notes: notes || null,
        purchase_date: buyDate || null,
      })
      const result = await api.post<{ items_created: number; total_cost: string }>(`/purchases/${buyId}/confirm`)
      setConfirmResult(result)
      setConfirmed(true)
      setShowConfirm(false)
    } catch (err) {
      alert(err instanceof AdminApiError ? err.detail : 'Failed to confirm purchase')
    } finally {
      setConfirming(false)
    }
  }

  const startNew = () => {
    setBuyId(null)
    setItems([])
    setCounterparty('')
    setNotes('')
    setConfirmed(false)
    setConfirmResult(null)
    setSelectedCard(null)
    setManualMode(false)
    setBuyDate(todayLocal())
  }

  // Safe: `addItem` normalises both amounts through parseMoney before an item
  // ever reaches this array, so these are canonical numeric strings — not the
  // raw text a human typed, which is what they used to be.
  const totalCost = items.reduce((sum, i) => sum + parseFloat(i.buy_price || '0'), 0)
  const totalMarket = items.reduce((sum, i) => sum + parseFloat(i.market_value || '0'), 0)
  // confirmResult comes back from the server, so parseFloat is safe on it.
  const avgBuyPct = totalMarket > 0 ? ((totalCost / totalMarket) * 100).toFixed(0) : '—'

  if (confirmed && confirmResult) {
    return (
      <div className="p-6 lg:p-8 max-w-3xl">
        <div className="vault-panel rounded-xl p-8 text-center">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-full bg-spriggatito-400/15 text-spriggatito-400 mb-4">
            <Check size={28} />
          </div>
          <h2 className="text-lg font-semibold text-pine-100 mb-1">Purchase Confirmed</h2>
          <p className="text-sm text-pine-300 mb-4">
            {confirmResult.items_created} item{confirmResult.items_created !== 1 ? 's' : ''} added to inventory for{' '}
            <span className="text-spriggatito-400 font-mono">${parseFloat(confirmResult.total_cost).toFixed(2)}</span>
          </p>
          <button type="button" onClick={startNew} className="px-4 py-2 rounded-lg text-xs font-medium bg-mint/15 text-mint border border-mint/30 hover:bg-mint/25 transition-colors">
            Start New Purchase
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="p-6 lg:p-8 max-w-6xl">
      <header className="mb-6">
        <span className="font-mono text-[11px] uppercase tracking-[0.22em] text-spriggatito-400/70">Buy</span>
        <h1 className="text-xl font-semibold text-pine-100">New Purchase</h1>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* LEFT: Purchasing Cart */}
        <div className="lg:col-span-4">
          <div className="vault-panel rounded-xl overflow-hidden">
            <div className="px-4 py-3 border-b border-pine-700/40 flex items-center gap-2">
              <ShoppingBag size={16} className="text-spriggatito-400" />
              <span className="text-sm font-medium text-pine-100">Purchasing ({items.length})</span>
            </div>

            {items.length === 0 ? (
              <div className="p-6 text-center text-xs text-pine-500">
                Add cards you&apos;re buying using the form
              </div>
            ) : (
              <div className="divide-y divide-pine-700/25 max-h-[420px] overflow-y-auto vault-scroll">
                {items.map((item, idx) => {
                  // Safe: `addItem` stores canonical amounts, never raw text.
                  const buyPct = item.market_value && parseFloat(item.market_value) > 0
                    ? ((parseFloat(item.buy_price) / parseFloat(item.market_value)) * 100).toFixed(0)
                    : null
                  return (
                    <div key={idx} className="flex items-center justify-between px-4 py-2.5">
                      <div className="flex items-center gap-2 min-w-0 flex-1">
                        {item.image_url && (
                          <CardImage imageUrl={item.image_url} alt={item.name} size="md" />
                        )}
                        <div className="min-w-0 flex-1">
                          <div className="text-xs text-pine-100 truncate flex items-center gap-1.5">
                            {item.name}
                            {!item.is_catalog_match && (
                              <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded bg-amber-500/10 border border-amber-500/20 text-[9px] text-amber-400 font-medium flex-shrink-0">
                                <AlertTriangle size={9} />
                                Unknown
                              </span>
                            )}
                          </div>
                          <div className="text-[10px] text-pine-400">
                            {item.condition} {item.set_name && `· ${item.set_name}`}
                            {item.card_number && ` · #${item.card_number}`}
                            {item.market_value && <> &middot; MV: <PriceDisplay value={item.market_value} className="text-[10px] text-pine-400 inline" /></>}
                            {buyPct && <> &middot; <span className="text-pine-300 font-mono">{buyPct}%</span></>}
                          </div>
                        </div>
                      </div>
                      <div className="flex items-center gap-3">
                        <span className="text-sm font-mono text-spriggatito-400">${parseFloat(item.buy_price).toFixed(2)}</span>
                        <button type="button" onClick={() => removeItem(idx)} className="p-1 rounded text-pine-500 hover:text-red-400 transition-colors">
                          <X size={14} />
                        </button>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}

            {items.length > 0 && (
              <div className="px-4 py-3 border-t border-pine-700/40 bg-pine-800/20 space-y-3">
                <div className="flex items-center justify-between">
                  <div className="text-xs text-pine-400">
                    Total Cost: <span className="font-mono text-spriggatito-400">${totalCost.toFixed(2)}</span>
                    {totalMarket > 0 && <> &middot; Avg Buy %: <span className="font-mono text-pine-200">{avgBuyPct}%</span></>}
                  </div>
                </div>
                {/* Transaction Date — directly above Confirm */}
                <label className="block">
                  <span className="text-[11px] text-pine-400 uppercase tracking-wider flex items-center gap-1">
                    <Calendar size={11} /> Transaction Date
                  </span>
                  <input
                    type="date"
                    value={buyDate}
                    onChange={(e) => setBuyDate(e.target.value)}
                    className="vault-field w-full mt-1 px-2.5 py-1.5 rounded-lg text-xs"
                  />
                </label>
                <button type="button" onClick={() => setShowConfirm(true)} className="w-full px-4 py-2 rounded-lg text-sm font-medium bg-spriggatito-400/15 text-spriggatito-400 border border-spriggatito-400/30 hover:bg-spriggatito-400/25 transition-colors">
                  Confirm Purchase
                </button>
              </div>
            )}
          </div>
        </div>

        {/* CENTER: Add Card Form */}
        <div className="lg:col-span-5 space-y-4">
          <div className="vault-panel rounded-xl p-4 space-y-3">
            <h3 className="text-xs font-semibold text-pine-200 uppercase tracking-wider">Add Card</h3>

            {/* Searchable Card Name — always visible in search & manual modes */}
            {mode !== 'catalog' && (
              <div className="relative">
                <label className="block">
                  <span className="text-[11px] text-pine-400">Card Name</span>
                  <div className="relative mt-1">
                    <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-pine-400 pointer-events-none" />
                    <input
                      value={nameSearch || form.name}
                      onChange={(e) => {
                        const val = e.target.value
                        setNameSearch(val)
                        setForm((f) => ({ ...f, name: val }))
                      }}
                      className="vault-field w-full pl-8 pr-3 py-1.5 rounded-lg text-sm"
                      placeholder={mode === 'manual' ? 'Card name…' : 'Search catalog or type name…'}
                      autoComplete="off"
                    />
                  </div>
                </label>

                {/* Catalog search dropdown — only in search mode.
                    Capped tall enough for ~5 candidates: scanning five cards at
                    a glance IS the workflow at a buy table. */}
                {mode === 'search' && catalogResults.length > 0 && (
                  <div className="absolute z-20 left-0 right-0 mt-1 vault-panel rounded-lg border border-pine-700/50 max-h-[28rem] overflow-y-auto vault-scroll shadow-xl">
                    {catalogResults.map((card) => (
                      <CardPickerRow
                        key={card.card_id}
                        card={card}
                        onSelect={selectCatalogCard}
                      />
                    ))}
                    {searchingCatalog && (
                      <div className="px-3 py-2 text-[10px] text-pine-500">Searching&hellip;</div>
                    )}
                  </div>
                )}

                {/* Search failed — deliberately distinct from "no matches" */}
                {mode === 'search' && catalogError && !searchingCatalog && (
                  <div className="mt-1.5 space-y-2">
                    <div className="flex items-start gap-1.5 px-2 py-1.5 rounded-lg bg-red-500/10 border border-red-500/20">
                      <AlertTriangle size={12} className="text-red-400 flex-shrink-0 mt-px" />
                      <span className="text-[10px] text-red-400">
                        {catalogError.message}
                      </span>
                    </div>
                    {catalogError.retryable && (
                      <button
                        type="button"
                        onClick={() => searchCatalog(nameSearch || form.name)}
                        className="flex items-center gap-1.5 text-[11px] text-pine-300 hover:text-spriggatito-400 transition-colors"
                      >
                        <RefreshCw size={12} />
                        Retry
                      </button>
                    )}
                  </div>
                )}

                {/* Unknown card warning + Enter manually button — search mode only */}
                {mode === 'search' && !selectedCard && catalogSearchDone && catalogResults.length === 0 && !searchingCatalog && form.name.trim().length >= 3 && (
                  <div className="mt-1.5 space-y-2">
                    <div className="flex items-center gap-1.5 px-2 py-1.5 rounded-lg bg-amber-500/10 border border-amber-500/20">
                      <AlertTriangle size={12} className="text-amber-400 flex-shrink-0" />
                      <span className="text-[10px] text-amber-400">
                        Unknown card &mdash; not found in catalog. You can still add it manually.
                      </span>
                    </div>
                    <button
                      type="button"
                      onClick={() => setManualMode(true)}
                      className="flex items-center gap-1.5 text-[11px] text-pine-300 hover:text-spriggatito-400 transition-colors"
                    >
                      <PenLine size={12} />
                      Enter manually instead
                    </button>
                  </div>
                )}
              </div>
            )}

            {/* Catalog mode: show selected card identity as read-only */}
            {mode === 'catalog' && selectedCard && (
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-[11px] text-pine-400">Selected Card</span>
                  <button
                    type="button"
                    onClick={() => {
                      setSelectedCard(null)
                      setForm((f) => ({ ...f, name: '', set_name: '', card_number: '', market_value: '', image_url: null }))
                    }}
                    className="text-[10px] text-pine-500 hover:text-pine-300 transition-colors"
                  >
                    Change
                  </button>
                </div>
                <div className="px-3 py-2 rounded-lg bg-pine-800/40 border border-pine-700/30">
                  <p className="text-xs text-pine-100 font-medium">{form.name}</p>
                  <p className="text-[10px] text-pine-400 mt-0.5">
                    {form.set_name && <>{form.set_name}</>}
                    {form.card_number && <> &middot; #{form.card_number}</>}
                    {form.market_value && <> &middot; MV: ${form.market_value}</>}
                  </p>
                </div>
              </div>
            )}

            {/* Manual mode: back to search button */}
            {mode === 'manual' && (
              <button
                type="button"
                onClick={() => setManualMode(false)}
                className="flex items-center gap-1 text-[11px] text-pine-400 hover:text-spriggatito-400 transition-colors"
              >
                <ArrowLeft size={12} />
                Back to search
              </button>
            )}

            {/* Fields shown in catalog and manual modes */}
            {mode !== 'search' && (
              <>
                {/* Set/Card# — editable in manual, read-only text shown above in catalog */}
                {mode === 'manual' && (
                  <div className="grid grid-cols-2 gap-2">
                    <label>
                      <span className="text-[11px] text-pine-400">Set</span>
                      <input value={form.set_name} onChange={(e) => setForm((f) => ({ ...f, set_name: e.target.value }))} className="vault-field w-full mt-1 px-2.5 py-1.5 rounded-lg text-xs" placeholder="Set name" />
                    </label>
                    <label>
                      <span className="text-[11px] text-pine-400">Card #</span>
                      <input value={form.card_number} onChange={(e) => setForm((f) => ({ ...f, card_number: e.target.value }))} className="vault-field w-full mt-1 px-2.5 py-1.5 rounded-lg text-xs" placeholder="e.g. 006/165" />
                    </label>
                  </div>
                )}
                <div className="grid grid-cols-2 gap-2">
                  <label>
                    <span className="text-[11px] text-pine-400">Condition</span>
                    <select value={form.condition} onChange={(e) => setForm((f) => ({ ...f, condition: e.target.value }))} className="vault-field w-full mt-1 px-2.5 py-1.5 rounded-lg text-xs">
                      {CONDITION_OPTIONS.map((c) => <option key={c} value={c}>{c}</option>)}
                    </select>
                  </label>
                  <label>
                    <span className="text-[11px] text-pine-400">Location</span>
                    <select value={form.location} onChange={(e) => setForm((f) => ({ ...f, location: e.target.value }))} className="vault-field w-full mt-1 px-2.5 py-1.5 rounded-lg text-xs">
                      {locationOptions.map((loc) => <option key={loc.value} value={loc.value}>{loc.label}</option>)}
                    </select>
                  </label>
                </div>
                {/* Market value — editable in manual, read-only in catalog (shown in the identity block) */}
                {mode === 'manual' && (
                  <label className="block">
                    <span className="text-[11px] text-pine-400">Market Value ($)</span>
                    <MoneyInput
                      label="Market Value"
                      value={form.market_value}
                      onChange={(raw) => updateMarketValue(raw)}
                      placeholder="0.00"
                      className="vault-field w-full mt-1 px-2.5 py-1.5 rounded-lg text-xs"
                    />
                  </label>
                )}
                <div className="grid grid-cols-5 gap-2 items-end">
                  <label className="col-span-2">
                    <span className="text-[11px] text-pine-400">Buy Price ($)</span>
                    <MoneyInput
                      label="Buy Price"
                      value={form.buy_price}
                      onChange={(raw) => updateBuyPrice(raw)}
                      placeholder="0.00"
                      className="vault-field w-full mt-1 px-2.5 py-1.5 rounded-lg text-xs"
                    />
                  </label>
                  <div className="flex items-center justify-center pb-1">
                    <span className="text-[10px] text-pine-500">or</span>
                  </div>
                  <label className="col-span-2">
                    <span className="text-[11px] text-pine-400">Buy %</span>
                    <div className="relative mt-1">
                      <input type="number" step="1" min="0" max="100" value={form.buy_pct} onChange={(e) => updateBuyPct(e.target.value)} className="vault-field w-full px-2.5 py-1.5 pr-7 rounded-lg text-xs" placeholder="60" />
                      <span className="absolute right-2 top-1/2 -translate-y-1/2 text-[10px] text-pine-500">%</span>
                    </div>
                  </label>
                </div>
                <button
                  type="button"
                  onClick={addItem}
                  // `=== null`, not falsiness — a $0 buy price is legitimate.
                  disabled={!form.name.trim() || parseMoney(form.buy_price) === null}
                  className="w-full flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium bg-spriggatito-400/15 text-spriggatito-400 border border-spriggatito-400/30 hover:bg-spriggatito-400/25 disabled:opacity-40 transition-colors"
                >
                  <Plus size={14} />
                  Add to Purchase
                </button>
              </>
            )}
          </div>
        </div>

        {/* RIGHT: Image Preview + Session Meta */}
        <div className="lg:col-span-3 flex flex-col items-center">
          <div className="vault-panel rounded-xl p-4 w-full flex flex-col items-center justify-center min-h-[280px]">
            {selectedCard && form.image_url ? (
              <>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={form.image_url}
                  alt={form.name}
                  className="rounded-lg border border-pine-700/40 max-h-[220px] w-auto object-contain shadow-lg"
                />
                <div className="mt-3 text-center">
                  <p className="text-xs text-pine-100 font-medium">{selectedCard.name}</p>
                  <p className="text-[10px] text-pine-400">
                    {selectedCard.set_name || selectedCard.set_id}
                    {selectedCard.number && ` · #${selectedCard.number}`}
                  </p>
                  {selectedCard.rarity && (
                    <p className="text-[10px] text-pine-500 mt-0.5">{selectedCard.rarity}</p>
                  )}
                </div>
              </>
            ) : (
              <div className="text-center">
                <div className="inline-flex items-center justify-center w-16 h-22 rounded-lg bg-pine-800/40 border border-pine-700/30 mb-3">
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-pine-600">
                    <rect x="3" y="3" width="18" height="18" rx="2" />
                    <circle cx="8.5" cy="8.5" r="1.5" />
                    <path d="M21 15l-5-5L5 21" />
                  </svg>
                </div>
                <p className="text-[11px] text-pine-500">Search for a card name to see its image</p>
                <p className="text-[10px] text-pine-600 mt-0.5">Visual confirmation before purchase</p>
              </div>
            )}
          </div>

          {/* Session meta: seller, payment, notes */}
          <div className="vault-panel rounded-xl p-4 space-y-3 w-full mt-4">
            <label className="block">
              <span className="text-[11px] text-pine-400 uppercase tracking-wider">Seller</span>
              <input value={counterparty} onChange={(e) => setCounterparty(e.target.value)} placeholder="Name (optional)" className="vault-field w-full mt-1 px-2.5 py-1.5 rounded-lg text-xs" />
            </label>
            <div>
              <span className="text-[11px] text-pine-400 uppercase tracking-wider">Payment</span>
              <div className="flex flex-wrap gap-2 mt-1">
                {[
                  { value: 'cash', icon: Banknote, label: 'Cash' },
                  { value: 'card', icon: CreditCard, label: 'Card' },
                  { value: 'venmo', icon: Smartphone, label: 'Venmo' },
                  { value: 'zelle', icon: DollarSign, label: 'Zelle' },
                ].map(({ value, icon: Icon, label }) => (
                  <button key={value} type="button" onClick={() => setPaymentMethod(value)} className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${paymentMethod === value ? 'bg-spriggatito-400/15 text-spriggatito-400 border-spriggatito-400/30' : 'text-pine-400 border-pine-700/40 hover:border-pine-600'}`}>
                    <Icon size={13} />
                    {label}
                  </button>
                ))}
              </div>
            </div>
            <label className="block">
              <span className="text-[11px] text-pine-400 uppercase tracking-wider">Notes</span>
              <textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                rows={2}
                className="vault-field w-full mt-1 px-2.5 py-1.5 rounded-lg text-xs resize-none"
                placeholder="Optional notes&hellip;"
              />
            </label>
          </div>
        </div>
      </div>

      <ConfirmDialog
        open={showConfirm}
        title="Confirm Purchase"
        description={`Buy ${items.length} card${items.length !== 1 ? 's' : ''} for $${totalCost.toFixed(2)}${buyDate !== todayLocal() ? ` (dated ${buyDate})` : ''}?`}
        confirmLabel="Complete Purchase"
        loading={confirming}
        onConfirm={handleConfirm}
        onCancel={() => setShowConfirm(false)}
      />
    </div>
  )
}
