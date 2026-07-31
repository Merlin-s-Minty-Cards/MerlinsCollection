'use client'

import { useCallback, useEffect, useState } from 'react'
import { ShoppingCart, Plus, X, CreditCard, Banknote, Check } from 'lucide-react'
import { useAdminApi, AdminApiError } from '@/lib/admin-api'
import SearchInput from '@/components/admin/shared/SearchInput'
import PriceDisplay from '@/components/admin/shared/PriceDisplay'
import ConfirmDialog from '@/components/admin/shared/ConfirmDialog'

interface SellItem {
  item_id: string
  name: string
  agreed_price: string | number
  original_price?: string | number | null
}

interface InventoryItem {
  item_id: string
  display_name?: string
  product_name?: string
  current_market_value?: string
  condition?: string
  status: string
  [key: string]: unknown
}

export default function AdminSellPage() {
  const api = useAdminApi()

  // Session state
  const [sellId, setSellId] = useState<string | null>(null)
  const [items, setItems] = useState<SellItem[]>([])
  const [paymentMethod, setPaymentMethod] = useState('cash')
  const [counterparty, setCounterparty] = useState('')
  const [notes, setNotes] = useState('')

  // Search
  const [search, setSearch] = useState('')
  const [searchResults, setSearchResults] = useState<InventoryItem[]>([])
  const [searching, setSearching] = useState(false)

  // Confirm
  const [showConfirm, setShowConfirm] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [confirmed, setConfirmed] = useState(false)
  const [confirmResult, setConfirmResult] = useState<{ items_sold: number; total_revenue: string } | null>(null)

  // Create session on mount
  useEffect(() => {
    if (!api.isAuthenticated || sellId) return
    api.post<{ sell_id: string }>('/sales', { payment_method: 'cash' }).then((res) => {
      setSellId(res.sell_id)
    })
  }, [api.isAuthenticated]) // eslint-disable-line react-hooks/exhaustive-deps

  // Search inventory
  const searchInventory = useCallback(async (q: string) => {
    if (!q.trim()) { setSearchResults([]); return }
    setSearching(true)
    try {
      const res = await api.get<{ items: InventoryItem[] }>('/inventory/search', { name: q, status: 'available' })
      // Filter out items already in cart
      const inCart = new Set(items.map((i) => i.item_id))
      setSearchResults(res.items.filter((i) => !inCart.has(i.item_id)).slice(0, 10))
    } catch {
      setSearchResults([])
    } finally {
      setSearching(false)
    }
  }, [api, items])

  useEffect(() => {
    searchInventory(search)
  }, [search, searchInventory])

  const addItem = async (inv: InventoryItem) => {
    if (!sellId) return
    const price = parseFloat(inv.current_market_value ?? '0')
    const agreedPrice = prompt(`Sell price for "${inv.display_name || inv.product_name}"?`, String(price))
    if (!agreedPrice) return

    try {
      await api.post(`/sales/${sellId}/items`, {
        item_id: inv.item_id,
        name: inv.display_name || inv.product_name || '',
        agreed_price: parseFloat(agreedPrice),
        original_price: price || null,
      })
      setItems((prev) => [...prev, {
        item_id: inv.item_id,
        name: inv.display_name || inv.product_name || '',
        agreed_price: agreedPrice,
        original_price: inv.current_market_value,
      }])
      setSearch('')
      setSearchResults([])
    } catch (err) {
      alert(err instanceof AdminApiError ? err.detail : 'Failed to add item')
    }
  }

  const removeItem = async (itemId: string) => {
    if (!sellId) return
    try {
      await api.del(`/sales/${sellId}/items/${itemId}`)
      setItems((prev) => prev.filter((i) => i.item_id !== itemId))
    } catch (err) {
      alert(err instanceof AdminApiError ? err.detail : 'Failed to remove item')
    }
  }

  const handleConfirm = async () => {
    if (!sellId) return
    setConfirming(true)
    try {
      // Update session metadata
      await api.patch(`/sales/${sellId}`, {
        payment_method: paymentMethod,
        counterparty: counterparty || null,
        notes: notes || null,
      })
      // Confirm
      const result = await api.post<{ items_sold: number; total_revenue: string }>(`/sales/${sellId}/confirm`)
      setConfirmResult(result)
      setConfirmed(true)
      setShowConfirm(false)
    } catch (err) {
      alert(err instanceof AdminApiError ? err.detail : 'Failed to confirm sale')
    } finally {
      setConfirming(false)
    }
  }

  const startNew = () => {
    setSellId(null)
    setItems([])
    setCounterparty('')
    setNotes('')
    setConfirmed(false)
    setConfirmResult(null)
  }

  const total = items.reduce((sum, i) => sum + parseFloat(String(i.agreed_price || 0)), 0)

  // Confirmed state
  if (confirmed && confirmResult) {
    return (
      <div className="p-6 lg:p-8 max-w-3xl">
        <div className="vault-panel rounded-xl p-8 text-center">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-full bg-mint/15 text-mint mb-4">
            <Check size={28} />
          </div>
          <h2 className="text-lg font-semibold text-pine-100 mb-1">Sale Confirmed</h2>
          <p className="text-sm text-pine-300 mb-4">
            {confirmResult.items_sold} item{confirmResult.items_sold !== 1 ? 's' : ''} sold for{' '}
            <span className="text-mint font-mono">${parseFloat(confirmResult.total_revenue).toFixed(2)}</span>
          </p>
          <button
            type="button"
            onClick={startNew}
            className="px-4 py-2 rounded-lg text-xs font-medium bg-mint/15 text-mint border border-mint/30 hover:bg-mint/25 transition-colors"
          >
            Start New Sale
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="p-6 lg:p-8 max-w-5xl">
      {/* Header */}
      <header className="mb-6">
        <span className="font-mono text-[11px] uppercase tracking-[0.22em] text-mint/70">
          Sell
        </span>
        <h1 className="text-xl font-semibold text-pine-100">New Sale</h1>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        {/* Left: Search & Add */}
        <div className="lg:col-span-2 space-y-4">
          <SearchInput
            value={search}
            onChange={setSearch}
            placeholder="Search available inventory…"
          />

          {/* Search results */}
          {search && (
            <div className="vault-panel rounded-xl divide-y divide-pine-700/30 max-h-80 overflow-y-auto vault-scroll">
              {searching ? (
                <div className="p-3 text-xs text-pine-400">Searching…</div>
              ) : searchResults.length === 0 ? (
                <div className="p-3 text-xs text-pine-500">No available items found</div>
              ) : (
                searchResults.map((item) => (
                  <button
                    key={item.item_id}
                    type="button"
                    onClick={() => addItem(item)}
                    className="w-full flex items-center justify-between px-3 py-2.5 hover:bg-pine-800/50 transition-colors text-left"
                  >
                    <div className="min-w-0">
                      <div className="text-xs text-pine-100 truncate">
                        {item.display_name || item.product_name}
                      </div>
                      <div className="text-[10px] text-pine-400">
                        {item.condition} · <PriceDisplay value={item.current_market_value} className="text-[10px] text-pine-400 inline" />
                      </div>
                    </div>
                    <Plus size={14} className="text-mint shrink-0 ml-2" />
                  </button>
                ))
              )}
            </div>
          )}

          {/* Session info */}
          <div className="vault-panel rounded-xl p-4 space-y-3">
            <label className="block">
              <span className="text-[11px] text-pine-400 uppercase tracking-wider">Customer</span>
              <input
                value={counterparty}
                onChange={(e) => setCounterparty(e.target.value)}
                placeholder="Name (optional)"
                className="vault-field w-full mt-1 px-2.5 py-1.5 rounded-lg text-xs"
              />
            </label>
            <label className="block">
              <span className="text-[11px] text-pine-400 uppercase tracking-wider">Payment</span>
              <div className="flex gap-2 mt-1">
                {[
                  { value: 'cash', icon: Banknote, label: 'Cash' },
                  { value: 'card', icon: CreditCard, label: 'Card' },
                ].map(({ value, icon: Icon, label }) => (
                  <button
                    key={value}
                    type="button"
                    onClick={() => setPaymentMethod(value)}
                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
                      paymentMethod === value
                        ? 'bg-mint/15 text-mint border-mint/30'
                        : 'text-pine-400 border-pine-700/40 hover:border-pine-600'
                    }`}
                  >
                    <Icon size={13} />
                    {label}
                  </button>
                ))}
              </div>
            </label>
            <label className="block">
              <span className="text-[11px] text-pine-400 uppercase tracking-wider">Notes</span>
              <textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                rows={2}
                className="vault-field w-full mt-1 px-2.5 py-1.5 rounded-lg text-xs resize-none"
                placeholder="Optional notes…"
              />
            </label>
          </div>
        </div>

        {/* Right: Cart */}
        <div className="lg:col-span-3">
          <div className="vault-panel rounded-xl overflow-hidden">
            <div className="px-4 py-3 border-b border-pine-700/40 flex items-center gap-2">
              <ShoppingCart size={16} className="text-mint" />
              <span className="text-sm font-medium text-pine-100">
                Cart ({items.length})
              </span>
            </div>

            {items.length === 0 ? (
              <div className="p-6 text-center text-xs text-pine-500">
                Search and add items to start a sale
              </div>
            ) : (
              <div className="divide-y divide-pine-700/25">
                {items.map((item) => (
                  <div key={item.item_id} className="flex items-center justify-between px-4 py-2.5">
                    <div className="min-w-0 flex-1">
                      <div className="text-xs text-pine-100 truncate">{item.name}</div>
                      {item.original_price && (
                        <div className="text-[10px] text-pine-500">
                          Market: <PriceDisplay value={item.original_price} className="text-[10px] text-pine-500 inline" />
                        </div>
                      )}
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="text-sm font-mono text-mint">
                        ${parseFloat(String(item.agreed_price)).toFixed(2)}
                      </span>
                      <button
                        type="button"
                        onClick={() => removeItem(item.item_id)}
                        className="p-1 rounded text-pine-500 hover:text-red-400 transition-colors"
                      >
                        <X size={14} />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* Total & Confirm */}
            {items.length > 0 && (
              <div className="px-4 py-3 border-t border-pine-700/40 flex items-center justify-between bg-pine-800/20">
                <div>
                  <span className="text-xs text-pine-400">Total</span>
                  <div className="text-lg font-mono font-semibold text-mint">
                    ${total.toFixed(2)}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => setShowConfirm(true)}
                  className="px-4 py-2 rounded-lg text-sm font-medium bg-mint/15 text-mint border border-mint/30 hover:bg-mint/25 transition-colors"
                >
                  Confirm Sale
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      <ConfirmDialog
        open={showConfirm}
        title="Confirm Sale"
        description={`Sell ${items.length} item${items.length !== 1 ? 's' : ''} for $${total.toFixed(2)} via ${paymentMethod}?`}
        confirmLabel="Complete Sale"
        loading={confirming}
        onConfirm={handleConfirm}
        onCancel={() => setShowConfirm(false)}
      />
    </div>
  )
}
