'use client'

import { useCallback, useEffect, useState } from 'react'
import { ArrowRightLeft, Plus, X, Check, Eye, EyeOff, DollarSign } from 'lucide-react'
import { useAdminApi, AdminApiError } from '@/lib/admin-api'
import SearchInput from '@/components/admin/shared/SearchInput'
import PriceDisplay from '@/components/admin/shared/PriceDisplay'
import ConfirmDialog from '@/components/admin/shared/ConfirmDialog'

interface TradeLeg {
  item_id?: string
  name: string
  value: string | number
}

interface TradeBalance {
  outgoing_total: string
  incoming_total: string
  cash_component: string | null
  cash_direction: string | null
  balance: string
  our_margin_pct?: string | null
}

interface InventoryItem {
  item_id: string
  display_name?: string
  product_name?: string
  current_market_value?: string
  condition?: string
  [key: string]: unknown
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

  // Search for outgoing items
  const [outSearch, setOutSearch] = useState('')
  const [outResults, setOutResults] = useState<InventoryItem[]>([])

  // Incoming form
  const [inForm, setInForm] = useState({ name: '', value: '' })

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
        value: parseFloat(value),
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
    try {
      await api.del(`/trades/${tradeId}/outgoing/${idx}`)
      setOutgoing((prev) => prev.filter((_, i) => i !== idx))
    } catch (err) {
      alert(err instanceof AdminApiError ? err.detail : 'Failed to remove')
    }
  }

  const addIncoming = async () => {
    if (!tradeId || !inForm.name.trim() || !inForm.value) return
    try {
      await api.post(`/trades/${tradeId}/incoming`, {
        name: inForm.name.trim(),
        value: parseFloat(inForm.value),
      })
      setIncoming((prev) => [...prev, { name: inForm.name.trim(), value: inForm.value }])
      setInForm({ name: '', value: '' })
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
      await api.post(`/trades/${tradeId}/cash`, {
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
      await api.patch(`/trades/${tradeId}`, { counterparty: counterparty || null })
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
                    <span className="text-xs text-pine-200 truncate">{item.name}</span>
                    <div className="flex items-center gap-2">
                      <PriceDisplay value={item.value} className="text-xs text-red-400" />
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
          <div className="flex gap-2">
            <input value={inForm.name} onChange={(e) => setInForm((f) => ({ ...f, name: e.target.value }))} placeholder="Card name" className="vault-field flex-1 px-2.5 py-1.5 rounded-lg text-xs" />
            <input type="number" step="0.01" value={inForm.value} onChange={(e) => setInForm((f) => ({ ...f, value: e.target.value }))} placeholder="Value" className="vault-field w-24 px-2.5 py-1.5 rounded-lg text-xs" />
            <button type="button" onClick={addIncoming} disabled={!inForm.name.trim() || !inForm.value} className="p-1.5 rounded-lg bg-mint/15 text-mint border border-mint/30 disabled:opacity-40">
              <Plus size={14} />
            </button>
          </div>
          <div className="vault-panel rounded-xl overflow-hidden">
            {incoming.length === 0 ? (
              <div className="p-4 text-center text-xs text-pine-500">No items coming in yet</div>
            ) : (
              <div className="divide-y divide-pine-700/25">
                {incoming.map((item, idx) => (
                  <div key={idx} className="flex items-center justify-between px-3 py-2">
                    <span className="text-xs text-pine-200 truncate">{item.name}</span>
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
              {balance ? `$${parseFloat(balance.balance).toFixed(2)}` : '$0.00'}
            </div>
          </div>

          {/* Margin (admin only) */}
          {!customerView && (
            <div className="text-right">
              <span className="text-[11px] text-pine-400 uppercase tracking-wider block mb-1">Our Margin</span>
              <div className="text-lg font-mono text-spriggatito-300">
                {balance?.our_margin_pct ? `${parseFloat(balance.our_margin_pct).toFixed(1)}%` : '—'}
              </div>
            </div>
          )}
        </div>

        {/* Counterparty + Confirm */}
        <div className="mt-4 flex items-center gap-3">
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
