'use client'

import { useCallback, useEffect, useState } from 'react'
import { Plus, X, Check, Eye, EyeOff, DollarSign, Calendar } from 'lucide-react'
import { useAdminApi, AdminApiError } from '@/lib/admin-api'
import SearchInput from '@/components/admin/shared/SearchInput'
import PriceDisplay from '@/components/admin/shared/PriceDisplay'
import ConfirmDialog from '@/components/admin/shared/ConfirmDialog'

interface TradeLeg {
  item_id?: string
  name: string
  card_number?: string
  set_name?: string
  market_value?: string | number
  value: string | number
}

interface TradeBalance {
  trade_id: string
  total_out_value: string
  total_in_value: string
  total_cost_basis: string
  cash_delta: string
  margin_pct: string | null
  is_balanced: boolean
}

interface InventoryItem {
  item_id: string
  display_name?: string
  product_name?: string
  current_market_value?: string
  condition?: string
  [key: string]: unknown
}

function todayISO() {
  return new Date().toISOString().split('T')[0]
}

export default function AdminTradePage() {
  const api = useAdminApi()

  const [tradeId, setTradeId] = useState<string | null>(null)
  const [outgoing, setOutgoing] = useState<TradeLeg[]>([])
  const [incoming, setIncoming] = useState<TradeLeg[]>([])
  const [cashAmount, setCashAmount] = useState('')
  const [cashDirection, setCashDirection] = useState<'we_pay' | 'they_pay'>('they_pay')
  const [balance, setBalance] = useState<TradeBalance | null>(null)
  const [counterparty, setCounterparty] = useState('')
  const [customerView, setCustomerView] = useState(false)
  const [tradeDate, setTradeDate] = useState(todayISO())

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

  // Fetch balance
  const fetchBalance = useCallback(async () => {
    if (!tradeId || !api.isAuthenticated) return
    try {
      const bal = await api.get<TradeBalance>(`/trades/${tradeId}/balance`)
      setBalance(bal)
    } catch { /* ignore */ }
  }, [tradeId, api])

  useEffect(() => { fetchBalance() }, [outgoing, incoming, cashAmount, fetchBalance])

  const addOutgoing = async (item: InventoryItem) => {
    if (!tradeId) return
    const value = item.current_market_value || '0'
    try {
      await api.post(`/trades/${tradeId}/outgoing`, {
        item_id: item.item_id,
        name: item.display_name || item.product_name || '',
        agreed_value: parseFloat(value),
      })
      setOutgoing((prev) => [...prev, { item_id: item.item_id, name: item.display_name || item.product_name || '', value }])
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
    } catch (err) {
      alert(err instanceof AdminApiError ? err.detail : 'Failed to remove')
    }
  }

  const updateOutgoingValue = async (idx: number, newValue: string) => {
    if (!tradeId) return
    const item = outgoing[idx]
    if (!item?.item_id) return
    try {
      await api.patch(`/trades/${tradeId}/outgoing/${item.item_id}`, {
        agreed_value: parseFloat(newValue),
      })
      setOutgoing((prev) => prev.map((leg, i) => i === idx ? { ...leg, value: newValue } : leg))
    } catch (err) {
      alert(err instanceof AdminApiError ? err.detail : 'Failed to update')
    }
  }

  // Bidirectional % ↔ value calculation for incoming form
  const handleIncomingValueChange = (newValue: string) => {
    const market = parseFloat(inForm.market_value)
    const val = parseFloat(newValue)
    let pct = ''
    if (market > 0 && val > 0) {
      pct = ((val / market) * 100).toFixed(0)
    }
    setInForm((f) => ({ ...f, value: newValue, percentage: pct }))
  }

  const handleIncomingPctChange = (newPct: string) => {
    const market = parseFloat(inForm.market_value)
    const pctNum = parseFloat(newPct)
    let val = ''
    if (market > 0 && pctNum > 0) {
      val = ((market * pctNum) / 100).toFixed(2)
    }
    setInForm((f) => ({ ...f, percentage: newPct, value: val }))
  }

  const addIncoming = async () => {
    if (!tradeId || !inForm.name.trim() || !inForm.value) return
    try {
      await api.post(`/trades/${tradeId}/incoming`, {
        name: inForm.name.trim(),
        card_number: inForm.card_number.trim() || undefined,
        set_name: inForm.set_name.trim() || undefined,
        market_value: inForm.market_value ? parseFloat(inForm.market_value) : undefined,
        agreed_value: parseFloat(inForm.value),
      })
      setIncoming((prev) => [...prev, {
        name: inForm.name.trim(),
        card_number: inForm.card_number.trim(),
        set_name: inForm.set_name.trim(),
        market_value: inForm.market_value,
        value: inForm.value,
      }])
      setInForm({ name: '', card_number: '', set_name: '', market_value: '', value: '', percentage: '' })
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

  const updateCash = async () => {
    if (!tradeId || !cashAmount) return
    try {
      await api.put(`/trades/${tradeId}/cash`, {
        amount: parseFloat(cashAmount),
        direction: cashDirection,
      })
      fetchBalance()
    } catch (err) {
      alert(err instanceof AdminApiError ? err.detail : 'Failed to set cash')
    }
  }

  const handleConfirm = async () => {
    if (!tradeId) return
    setConfirming(true)
    try {
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
    setIncoming([])
    setCashAmount('')
    setBalance(null)
    setCounterparty('')
    setConfirmed(false)
    setTradeDate(todayISO())
  }

  const outTotal = outgoing.reduce((s, i) => s + parseFloat(String(i.value || 0)), 0)
  const inTotal = incoming.reduce((s, i) => s + parseFloat(String(i.value || 0)), 0)

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
    <div className="p-6 lg:p-8 max-w-6xl">
      <header className="flex items-center justify-between mb-6">
        <div>
          <span className="font-mono text-[11px] uppercase tracking-[0.22em] text-spriggatito-300/70">Trade</span>
          <h1 className="text-xl font-semibold text-pine-100">Trade Calculator</h1>
        </div>
        <button
          type="button"
          onClick={() => setCustomerView((v) => !v)}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${customerView ? 'bg-amber-500/15 text-amber-400 border-amber-500/30' : 'text-pine-400 border-pine-700/40 hover:border-pine-600'}`}
        >
          {customerView ? <EyeOff size={13} /> : <Eye size={13} />}
          {customerView ? 'Admin View' : 'Customer View'}
        </button>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Outgoing (Our cards) */}
        <div className="space-y-3">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-red-400">Going Out (Ours)</h3>
          <SearchInput value={outSearch} onChange={setOutSearch} placeholder="Search our inventory…" />
          {outSearch && outResults.length > 0 && (
            <div className="vault-panel rounded-lg divide-y divide-pine-700/30 max-h-40 overflow-y-auto vault-scroll">
              {outResults.map((item) => (
                <button key={item.item_id} type="button" onClick={() => addOutgoing(item)} className="w-full flex items-center justify-between px-3 py-2 hover:bg-pine-800/50 text-left text-xs">
                  <span className="text-pine-100 truncate">{item.display_name || item.product_name}</span>
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
                  <div key={idx} className="flex items-center justify-between px-3 py-2">
                    <span className="text-xs text-pine-200 truncate flex-1">{item.name}</span>
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] text-pine-500">$</span>
                      <input
                        type="number"
                        step="0.01"
                        defaultValue={parseFloat(String(item.value)).toFixed(2)}
                        onBlur={(e) => {
                          const newVal = e.target.value
                          if (newVal && parseFloat(newVal) !== parseFloat(String(item.value))) {
                            updateOutgoingValue(idx, newVal)
                          }
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

        {/* Incoming (Their cards) */}
        <div className="space-y-3">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-mint">Coming In (Theirs)</h3>

          {/* Expanded incoming form with labels */}
          <div className="vault-panel rounded-xl p-3 space-y-2">
            <div className="grid grid-cols-6 gap-2">
              <div className="col-span-2">
                <label className="text-[10px] text-pine-400 uppercase tracking-wider block mb-0.5">Card Name</label>
                <input
                  value={inForm.name}
                  onChange={(e) => setInForm((f) => ({ ...f, name: e.target.value }))}
                  placeholder="Name"
                  className="vault-field w-full px-2 py-1.5 rounded-lg text-xs"
                />
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
                <input
                  type="number"
                  step="0.01"
                  value={inForm.market_value}
                  onChange={(e) => setInForm((f) => ({ ...f, market_value: e.target.value }))}
                  placeholder="$"
                  className="vault-field w-full px-2 py-1.5 rounded-lg text-xs"
                />
              </div>
              <div className="flex items-end gap-1">
                <div className="flex-1">
                  <label className="text-[10px] font-semibold text-mint uppercase tracking-wider block mb-0.5 bg-mint/10 rounded px-1 text-center">Value</label>
                  <input
                    type="number"
                    step="0.01"
                    value={inForm.value}
                    onChange={(e) => handleIncomingValueChange(e.target.value)}
                    placeholder="$"
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
                  <div key={idx} className="flex items-center justify-between px-3 py-2">
                    <div className="min-w-0 flex-1">
                      <span className="text-xs text-pine-200 truncate block">
                        {item.name}
                        {item.card_number && <span className="text-pine-500"> #{item.card_number}</span>}
                      </span>
                      {item.set_name && (
                        <span className="text-[10px] text-pine-500 truncate block">{item.set_name}</span>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
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
      </div>

      {/* Cash + Balance */}
      <div className="mt-6 vault-panel rounded-xl p-4">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 items-end">
          {/* Cash component */}
          <div className="space-y-2">
            <span className="text-[11px] text-pine-400 uppercase tracking-wider">Cash Component</span>
            <div className="flex gap-2">
              <select value={cashDirection} onChange={(e) => setCashDirection(e.target.value as 'we_pay' | 'they_pay')} className="vault-field px-2 py-1.5 rounded-lg text-xs">
                <option value="they_pay">They pay us</option>
                <option value="we_pay">We pay them</option>
              </select>
              <div className="relative flex-1">
                <DollarSign size={13} className="absolute left-2 top-1/2 -translate-y-1/2 text-pine-400" />
                <input type="number" step="0.01" value={cashAmount} onChange={(e) => setCashAmount(e.target.value)} onBlur={updateCash} className="vault-field w-full pl-7 pr-2 py-1.5 rounded-lg text-xs" placeholder="0.00" />
              </div>
            </div>
          </div>

          {/* Balance indicator */}
          <div className="text-center">
            <span className="text-[11px] text-pine-400 uppercase tracking-wider block mb-1">Balance</span>
            <div className="text-2xl font-mono font-semibold text-pine-100">
              {balance ? (() => {
                const out = parseFloat(balance.total_out_value)
                const inc = parseFloat(balance.total_in_value)
                const cash = parseFloat(balance.cash_delta)
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

          {/* Profit (admin only) — shows both $ and % */}
          {!customerView && (
            <div className="text-right">
              <span className="text-[11px] text-pine-400 uppercase tracking-wider block mb-1">Our Profit</span>
              {balance ? (() => {
                const totalIn = parseFloat(balance.total_in_value)
                const cashDelta = parseFloat(balance.cash_delta)
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
            disabled={outgoing.length === 0 && incoming.length === 0}
            className="px-4 py-2 rounded-lg text-xs font-medium bg-spriggatito-300/15 text-spriggatito-300 border border-spriggatito-300/30 hover:bg-spriggatito-300/25 disabled:opacity-40 transition-colors"
          >
            Confirm Trade
          </button>
        </div>
      </div>

      <ConfirmDialog
        open={showConfirm}
        title="Confirm Trade"
        description={`Execute trade: ${outgoing.length} card${outgoing.length !== 1 ? 's' : ''} out, ${incoming.length} card${incoming.length !== 1 ? 's' : ''} in${cashAmount ? ` + $${cashAmount} cash (${cashDirection === 'they_pay' ? 'they pay' : 'we pay'})` : ''}?`}
        confirmLabel="Execute Trade"
        loading={confirming}
        onConfirm={handleConfirm}
        onCancel={() => setShowConfirm(false)}
      />
    </div>
  )
}
