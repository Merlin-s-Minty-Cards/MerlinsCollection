'use client'

import { useEffect, useState } from 'react'
import { ShoppingBag, Plus, X, Check, Banknote, CreditCard, Smartphone, DollarSign } from 'lucide-react'
import { useAdminApi, AdminApiError } from '@/lib/admin-api'
import { CONDITION_OPTIONS, LOCATION_OPTIONS, parseCondition } from '@/lib/constants'
import PriceDisplay from '@/components/admin/shared/PriceDisplay'
import ConfirmDialog from '@/components/admin/shared/ConfirmDialog'
import ImageToggle from '@/components/admin/shared/ImageToggle'
import CardImage from '@/components/admin/shared/CardImage'

interface BuyItem {
  name: string
  condition: string
  buy_price: string
  market_value: string
  set_name: string
  location: string
  card_number: string
  buy_pct: string
}

export default function AdminBuyPage() {
  const api = useAdminApi()

  // Session
  const [buyId, setBuyId] = useState<string | null>(null)
  const [items, setItems] = useState<BuyItem[]>([])
  const [paymentMethod, setPaymentMethod] = useState('cash')
  const [counterparty, setCounterparty] = useState('')
  const [notes, setNotes] = useState('')

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
  })

  // Bidirectional percentage calculation
  const updateBuyPrice = (price: string) => {
    setForm((f) => {
      const newForm = { ...f, buy_price: price }
      if (price && f.market_value) {
        const pct = ((parseFloat(price) / parseFloat(f.market_value)) * 100).toFixed(0)
        newForm.buy_pct = pct
      } else {
        newForm.buy_pct = ''
      }
      return newForm
    })
  }

  const updateBuyPct = (pct: string) => {
    setForm((f) => {
      const newForm = { ...f, buy_pct: pct }
      if (pct && f.market_value) {
        const price = ((parseFloat(pct) / 100) * parseFloat(f.market_value)).toFixed(2)
        newForm.buy_price = price
      } else {
        newForm.buy_price = ''
      }
      return newForm
    })
  }

  const updateMarketValue = (mv: string) => {
    setForm((f) => {
      const newForm = { ...f, market_value: mv }
      // Recalculate buy price from percentage if pct is set
      if (f.buy_pct && mv) {
        const price = ((parseFloat(f.buy_pct) / 100) * parseFloat(mv)).toFixed(2)
        newForm.buy_price = price
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
    if (!buyId || !form.name.trim() || !form.buy_price) return
    try {
      await api.post(`/purchases/${buyId}/items`, {
        name: form.name.trim(),
        ...parseCondition(form.condition),
        buy_price: parseFloat(form.buy_price),
        market_value: form.market_value ? parseFloat(form.market_value) : null,
        set_name: form.set_name || null,
        location: form.location,
        number: form.card_number || null,
      })
      setItems((prev) => [...prev, { ...form }])
      setForm({ name: '', condition: 'NM', buy_price: '', market_value: '', set_name: '', location: 'toploader', card_number: '', buy_pct: '' })
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
  }

  const totalCost = items.reduce((sum, i) => sum + parseFloat(i.buy_price || '0'), 0)
  const totalMarket = items.reduce((sum, i) => sum + parseFloat(i.market_value || '0'), 0)
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
    <div className="p-6 lg:p-8 max-w-5xl">
      <header className="mb-6">
        <span className="font-mono text-[11px] uppercase tracking-[0.22em] text-spriggatito-400/70">Buy</span>
        <h1 className="text-xl font-semibold text-pine-100">New Purchase</h1>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        {/* Left: Add form */}
        <div className="lg:col-span-2 space-y-4">
          <div className="vault-panel rounded-xl p-4 space-y-3">
            <h3 className="text-xs font-semibold text-pine-200 uppercase tracking-wider">Add Card</h3>
            <label className="block">
              <span className="text-[11px] text-pine-400">Card Name</span>
              <input value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} className="vault-field w-full mt-1 px-2.5 py-1.5 rounded-lg text-sm" placeholder="e.g. Charizard ex" />
            </label>
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
                  {LOCATION_OPTIONS.map((loc) => <option key={loc.value} value={loc.value}>{loc.label}</option>)}
                </select>
              </label>
            </div>
            <label className="block">
              <span className="text-[11px] text-pine-400">Market Value ($)</span>
              <input type="number" step="0.01" value={form.market_value} onChange={(e) => updateMarketValue(e.target.value)} className="vault-field w-full mt-1 px-2.5 py-1.5 rounded-lg text-xs" placeholder="0.00" />
            </label>
            <div className="grid grid-cols-5 gap-2 items-end">
              <label className="col-span-2">
                <span className="text-[11px] text-pine-400">Buy Price ($)</span>
                <input type="number" step="0.01" value={form.buy_price} onChange={(e) => updateBuyPrice(e.target.value)} className="vault-field w-full mt-1 px-2.5 py-1.5 rounded-lg text-xs" placeholder="0.00" />
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
              disabled={!form.name.trim() || !form.buy_price}
              className="w-full flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium bg-spriggatito-400/15 text-spriggatito-400 border border-spriggatito-400/30 hover:bg-spriggatito-400/25 disabled:opacity-40 transition-colors"
            >
              <Plus size={14} />
              Add to Purchase
            </button>
          </div>

          {/* Session meta */}
          <div className="vault-panel rounded-xl p-4 space-y-3">
            <label className="block">
              <span className="text-[11px] text-pine-400 uppercase tracking-wider">Seller</span>
              <input value={counterparty} onChange={(e) => setCounterparty(e.target.value)} placeholder="Name (optional)" className="vault-field w-full mt-1 px-2.5 py-1.5 rounded-lg text-xs" />
            </label>
            <label className="block">
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
            </label>
          </div>
        </div>

        {/* Right: Item list */}
        <div className="lg:col-span-3">
          <div className="vault-panel rounded-xl overflow-hidden">
            <div className="px-4 py-3 border-b border-pine-700/40 flex items-center gap-2">
              <ShoppingBag size={16} className="text-spriggatito-400" />
              <span className="text-sm font-medium text-pine-100">Purchasing ({items.length})</span>
            </div>

            {items.length === 0 ? (
              <div className="p-6 text-center text-xs text-pine-500">
                Add cards you&apos;re buying above
              </div>
            ) : (
              <div className="divide-y divide-pine-700/25">
                {items.map((item, idx) => {
                  const buyPct = item.market_value && parseFloat(item.market_value) > 0
                    ? ((parseFloat(item.buy_price) / parseFloat(item.market_value)) * 100).toFixed(0)
                    : null
                  return (
                    <div key={idx} className="flex items-center justify-between px-4 py-2.5">
                      <div className="min-w-0 flex-1">
                        <div className="text-xs text-pine-100 truncate">{item.name}</div>
                        <div className="text-[10px] text-pine-400">
                          {item.condition} {item.set_name && `· ${item.set_name}`}
                          {item.card_number && ` · #${item.card_number}`}
                          {item.market_value && <> · MV: <PriceDisplay value={item.market_value} className="text-[10px] text-pine-400 inline" /></>}
                          {buyPct && <> · <span className="text-pine-300 font-mono">{buyPct}%</span></>}
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
              <div className="px-4 py-3 border-t border-pine-700/40 bg-pine-800/20">
                <div className="flex items-center justify-between mb-2">
                  <div className="text-xs text-pine-400">
                    Total Cost: <span className="font-mono text-spriggatito-400">${totalCost.toFixed(2)}</span>
                    {totalMarket > 0 && <> · Avg Buy %: <span className="font-mono text-pine-200">{avgBuyPct}%</span></>}
                  </div>
                </div>
                <button type="button" onClick={() => setShowConfirm(true)} className="w-full px-4 py-2 rounded-lg text-sm font-medium bg-spriggatito-400/15 text-spriggatito-400 border border-spriggatito-400/30 hover:bg-spriggatito-400/25 transition-colors">
                  Confirm Purchase
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      <ConfirmDialog
        open={showConfirm}
        title="Confirm Purchase"
        description={`Buy ${items.length} card${items.length !== 1 ? 's' : ''} for $${totalCost.toFixed(2)}?`}
        confirmLabel="Complete Purchase"
        loading={confirming}
        onConfirm={handleConfirm}
        onCancel={() => setShowConfirm(false)}
      />
    </div>
  )
}
