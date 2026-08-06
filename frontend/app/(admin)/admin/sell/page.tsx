'use client'

import { useCallback, useEffect, useState } from 'react'
import { ShoppingCart, Plus, X, CreditCard, Banknote, Check, Smartphone, DollarSign } from 'lucide-react'
import { useAdminApi, AdminApiError } from '@/lib/admin-api'
import { useCardImages } from '@/lib/use-card-images'
import SearchInput from '@/components/admin/shared/SearchInput'
import PriceDisplay from '@/components/admin/shared/PriceDisplay'
import ConfirmDialog from '@/components/admin/shared/ConfirmDialog'
import CardImage from '@/components/admin/shared/CardImage'
import ImageToggle from '@/components/admin/shared/ImageToggle'
import CardDetailModal from '@/components/admin/shared/CardDetailModal'
import OwnershipBadge from '@/components/admin/shared/OwnershipBadge'

interface SellItem {
  item_id: string
  name: string
  card_id?: string
  agreed_price: string | number
  original_price?: string | number | null
  cost_basis?: string | number | null
  sticker_price?: string | number | null
}

interface InventoryItem {
  item_id: string
  card_id?: string
  display_name?: string
  product_name?: string
  current_market_value?: string
  cost_basis?: string
  sticker_price?: string
  condition?: string
  status: string
  consignment?: { consignor_id: string; split_percent: string; minimum_price?: string | null; paid_out: boolean } | null
  [key: string]: unknown
}

type PaymentMethodOption = {
  value: string
  icon: typeof Banknote
  label: string
}

const PAYMENT_METHODS: PaymentMethodOption[] = [
  { value: 'cash', icon: Banknote, label: 'Cash' },
  { value: 'card', icon: CreditCard, label: 'Card' },
  { value: 'venmo', icon: Smartphone, label: 'Venmo' },
  { value: 'zelle', icon: DollarSign, label: 'Zelle' },
]

export default function AdminSellPage() {
  const api = useAdminApi()

  // Session state
  const [sellId, setSellId] = useState<string | null>(null)
  const [items, setItems] = useState<SellItem[]>([])
  const [paymentMethod, setPaymentMethod] = useState('cash')
  const [counterparty, setCounterparty] = useState('')
  const [notes, setNotes] = useState('')
  const [saleDate, setSaleDate] = useState(new Date().toISOString().split('T')[0])

  // Search
  const [search, setSearch] = useState('')
  const [searchResults, setSearchResults] = useState<InventoryItem[]>([])
  const [searching, setSearching] = useState(false)

  // Confirm
  const [showConfirm, setShowConfirm] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [confirmed, setConfirmed] = useState(false)
  const [confirmResult, setConfirmResult] = useState<{
    items_sold: number
    total_revenue: string
    fee: string
    net_revenue: string
  } | null>(null)

  // Discount
  const [bulkDiscount, setBulkDiscount] = useState('')

  // Fee preview
  const [feePreview, setFeePreview] = useState<{ fee: string; net: string } | null>(null)

  // Image toggle and detail modal
  const [showImages, setShowImages] = useState(true)
  const [detailItem, setDetailItem] = useState<InventoryItem | null>(null)

  // Collect all card_ids from search results and cart items for bulk image resolution
  const allCardIds = [
    ...searchResults.map((i) => i.card_id),
    ...items.map((i) => i.card_id),
  ]
  const { getImageUrl } = useCardImages(showImages ? allCardIds : [])

  // Track the selected/highlighted item for large preview
  const [previewItem, setPreviewItem] = useState<{ name: string; card_id?: string } | null>(null)

  // Create session on mount
  useEffect(() => {
    if (!api.isAuthenticated || sellId) return
    api.post<{ sell_id: string }>('/sales', { payment_method: 'cash' }).then((res) => {
      setSellId(res.sell_id)
    })
  }, [api.isAuthenticated]) // eslint-disable-line react-hooks/exhaustive-deps

  // Calculate fee preview when total or payment method changes
  const total = items.reduce((sum, i) => sum + parseFloat(String(i.agreed_price || 0)), 0)

  useEffect(() => {
    if (total <= 0 || !api.isAuthenticated) {
      setFeePreview(null)
      return
    }
    api.get<{ fee: string; net: string }>('/sales/calculate-fee', {
      amount: total.toFixed(2),
      payment_method: paymentMethod,
    }).then(setFeePreview).catch(() => setFeePreview(null))
  }, [total, paymentMethod, api]) // eslint-disable-line react-hooks/exhaustive-deps

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
    const sticker = parseFloat(inv.sticker_price ?? '0')
    const market = parseFloat(inv.current_market_value ?? '0')
    const price = sticker > 0 ? sticker : market

    try {
      await api.post(`/sales/${sellId}/items`, {
        item_id: inv.item_id,
        name: inv.display_name || inv.product_name || '',
        agreed_price: price,
        original_price: market || null,
      })
      const newItem: SellItem = {
        item_id: inv.item_id,
        name: inv.display_name || inv.product_name || '',
        card_id: inv.card_id,
        agreed_price: String(price),
        original_price: inv.current_market_value,
        cost_basis: inv.cost_basis,
        sticker_price: inv.sticker_price,
      }
      setItems((prev) => [...prev, newItem])
      // Show the added item in the preview panel
      setPreviewItem({ name: newItem.name, card_id: inv.card_id })
      setSearch('')
      setSearchResults([])
    } catch (err) {
      alert(err instanceof AdminApiError ? err.detail : 'Failed to add item')
    }
  }

  const updateItemPrice = (itemId: string, newPrice: string) => {
    setItems((prev) => prev.map((i) =>
      i.item_id === itemId ? { ...i, agreed_price: newPrice } : i
    ))
  }

  const applyBulkDiscount = () => {
    const pct = parseFloat(bulkDiscount)
    if (!pct || pct <= 0 || pct > 100) return
    setItems((prev) => prev.map((i) => {
      const original = parseFloat(String(i.sticker_price || i.original_price || i.agreed_price))
      const discounted = (original * (1 - pct / 100)).toFixed(2)
      return { ...i, agreed_price: discounted }
    }))
  }

  const removeItem = async (itemId: string) => {
    if (!sellId) return
    try {
      await api.del(`/sales/${sellId}/items/${itemId}`)
      setItems((prev) => prev.filter((i) => i.item_id !== itemId))
      // Clear preview if the removed item was being previewed
      if (previewItem && items.find((i) => i.item_id === itemId)?.card_id === previewItem.card_id) {
        setPreviewItem(null)
      }
    } catch (err) {
      alert(err instanceof AdminApiError ? err.detail : 'Failed to remove item')
    }
  }

  const handleConfirm = async () => {
    if (!sellId) return
    setConfirming(true)
    try {
      await api.patch(`/sales/${sellId}`, {
        payment_method: paymentMethod,
        counterparty: counterparty || null,
        notes: notes || null,
        sale_date: saleDate || null,
      })
      const result = await api.post<{
        items_sold: number
        total_revenue: string
        fee: string
        net_revenue: string
      }>(`/sales/${sellId}/confirm`)
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
    setFeePreview(null)
    setBulkDiscount('')
    setSaleDate(new Date().toISOString().split('T')[0])
    setPreviewItem(null)
  }

  // Confirmed state
  if (confirmed && confirmResult) {
    const fee = parseFloat(confirmResult.fee)
    const net = parseFloat(confirmResult.net_revenue)
    return (
      <div className="p-6 lg:p-8 max-w-3xl">
        <div className="vault-panel rounded-xl p-8 text-center">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-full bg-mint/15 text-mint mb-4">
            <Check size={28} />
          </div>
          <h2 className="text-lg font-semibold text-pine-100 mb-1">Sale Confirmed</h2>
          <p className="text-sm text-pine-300 mb-2">
            {confirmResult.items_sold} item{confirmResult.items_sold !== 1 ? 's' : ''} sold for{' '}
            <span className="text-mint font-mono">${parseFloat(confirmResult.total_revenue).toFixed(2)}</span>
          </p>
          {fee > 0 && (
            <p className="text-xs text-pine-400 mb-1">
              Fee ({paymentMethod}): <span className="text-red-400 font-mono">-${fee.toFixed(2)}</span>
              {' · '}Net: <span className="text-mint font-mono">${net.toFixed(2)}</span>
            </p>
          )}
          <button
            type="button"
            onClick={startNew}
            className="mt-4 px-4 py-2 rounded-lg text-xs font-medium bg-mint/15 text-mint border border-mint/30 hover:bg-mint/25 transition-colors"
          >
            Start New Sale
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="p-6 lg:p-8 max-w-6xl">
      {/* Header */}
      <header className="mb-6">
        <span className="font-mono text-[11px] uppercase tracking-[0.22em] text-mint/70">
          Sell
        </span>
        <h1 className="text-xl font-semibold text-pine-100">New Sale</h1>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left: Search & Add */}
        <div className="lg:col-span-4 space-y-4">
          <div className="flex items-center gap-3">
            <SearchInput
              value={search}
              onChange={setSearch}
              placeholder="Search available inventory…"
            />
            <ImageToggle showImages={showImages} onToggle={() => setShowImages(!showImages)} size="sm" />
          </div>

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
                    onMouseEnter={() => setPreviewItem({ name: item.display_name || item.product_name || '', card_id: item.card_id })}
                    className="w-full flex items-center justify-between px-3 py-2.5 hover:bg-pine-800/50 transition-colors text-left"
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      <div className="min-w-0">
                        <div className="text-xs text-pine-100 truncate flex items-center gap-1.5">
                          {item.display_name || item.product_name}
                          <OwnershipBadge consigned={item.consignment != null} />
                        </div>
                        <div className="text-[10px] text-pine-400 flex items-center gap-2">
                          <span>{item.condition}</span>
                          {item.sticker_price && (
                            <span className="text-amber-400">Sticker: ${parseFloat(item.sticker_price).toFixed(2)}</span>
                          )}
                          <span>Market: <PriceDisplay value={item.current_market_value} className="text-[10px] text-pine-400 inline" /></span>
                        </div>
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
              <span className="text-[11px] text-pine-400 uppercase tracking-wider">Date</span>
              <input
                type="date"
                value={saleDate}
                onChange={(e) => setSaleDate(e.target.value)}
                className="vault-field w-full mt-1 px-2.5 py-1.5 rounded-lg text-xs"
              />
            </label>
            <label className="block">
              <span className="text-[11px] text-pine-400 uppercase tracking-wider">Customer</span>
              <input
                value={counterparty}
                onChange={(e) => setCounterparty(e.target.value)}
                placeholder="Name (optional)"
                className="vault-field w-full mt-1 px-2.5 py-1.5 rounded-lg text-xs"
              />
            </label>
            <div>
              <span className="text-[11px] text-pine-400 uppercase tracking-wider">Payment</span>
              <div className="flex flex-wrap gap-2 mt-1">
                {PAYMENT_METHODS.map(({ value, icon: Icon, label }) => (
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
              {paymentMethod === 'venmo' && (
                <p className="text-[10px] text-amber-400/80 mt-1.5">
                  Venmo fee: 1.9% + $0.10 deducted from profit
                </p>
              )}
            </div>
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

        {/* Center: Image Preview */}
        <div className="lg:col-span-3 flex flex-col items-center">
          <div className="vault-panel rounded-xl p-4 w-full flex flex-col items-center justify-center min-h-[32rem] sticky top-6">
            {previewItem?.card_id && getImageUrl(previewItem.card_id) ? (
              <>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={getImageUrl(previewItem.card_id)!}
                  alt={previewItem.name}
                  className="rounded-lg border border-pine-700/40 max-h-[30rem] w-auto object-contain shadow-lg"
                />
                <p className="mt-3 text-xs text-pine-100 font-medium text-center">{previewItem.name}</p>
                <p className="text-[10px] text-pine-500 mt-0.5">Visual confirmation</p>
              </>
            ) : previewItem ? (
              <div className="text-center">
                <div className="inline-flex items-center justify-center w-16 h-22 rounded-lg bg-pine-800/40 border border-pine-700/30 mb-3">
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-pine-600">
                    <rect x="3" y="3" width="18" height="18" rx="2" />
                    <circle cx="8.5" cy="8.5" r="1.5" />
                    <path d="M21 15l-5-5L5 21" />
                  </svg>
                </div>
                <p className="text-xs text-pine-200">{previewItem.name}</p>
                <p className="text-[10px] text-pine-500 mt-0.5">No image available</p>
              </div>
            ) : (
              <div className="text-center">
                <div className="inline-flex items-center justify-center w-16 h-22 rounded-lg bg-pine-800/40 border border-pine-700/30 mb-3">
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-pine-600">
                    <rect x="3" y="3" width="18" height="18" rx="2" />
                    <circle cx="8.5" cy="8.5" r="1.5" />
                    <path d="M21 15l-5-5L5 21" />
                  </svg>
                </div>
                <p className="text-[11px] text-pine-500">Hover or select a card</p>
                <p className="text-[10px] text-pine-600 mt-0.5">Image preview for verification</p>
              </div>
            )}
          </div>
        </div>

        {/* Right: Cart */}
        <div className="lg:col-span-5">
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
              <div className="divide-y divide-pine-700/25 max-h-[380px] overflow-y-auto vault-scroll">
                {items.map((item) => {
                  const cost = parseFloat(String(item.cost_basis || 0))
                  const agreed = parseFloat(String(item.agreed_price || 0))
                  const marginPct = cost > 0 ? (((agreed - cost) / cost) * 100).toFixed(0) : null
                  const marginColor = marginPct && parseFloat(marginPct) >= 0 ? 'text-mint' : 'text-red-400'
                  return (
                    <div
                      key={item.item_id}
                      className="flex items-center justify-between px-4 py-2.5 hover:bg-pine-800/30 transition-colors cursor-pointer"
                      onClick={() => setPreviewItem({ name: item.name, card_id: item.card_id })}
                    >
                      <div className="flex items-center gap-2 min-w-0 flex-1">
                        {showImages && (
                          <CardImage imageUrl={getImageUrl(item.card_id)} alt={item.name} size="md" />
                        )}
                        <div className="min-w-0 flex-1">
                          <div className="text-xs text-pine-100 truncate">{item.name}</div>
                          <div className="text-[10px] text-pine-500 flex items-center gap-2 flex-wrap">
                            {item.sticker_price && (
                              <span className="text-amber-400/80">Sticker: ${parseFloat(String(item.sticker_price)).toFixed(2)}</span>
                            )}
                            {item.original_price && (
                              <span>Market: <PriceDisplay value={item.original_price} className="text-[10px] text-pine-500 inline" /></span>
                            )}
                            {item.cost_basis && (
                              <span>Paid: <PriceDisplay value={item.cost_basis} className="text-[10px] text-pine-500 inline" /></span>
                            )}
                            {marginPct && (
                              <span className={`font-mono ${marginColor}`}>{parseFloat(marginPct) >= 0 ? '+' : ''}{marginPct}%</span>
                            )}
                          </div>
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-[10px] text-pine-500">$</span>
                        <input
                          type="number"
                          step="0.01"
                          value={item.agreed_price}
                          onChange={(e) => updateItemPrice(item.item_id, e.target.value)}
                          onClick={(e) => e.stopPropagation()}
                          className="vault-field w-20 px-1.5 py-0.5 rounded text-sm text-right text-mint font-mono"
                        />
                        <button
                          type="button"
                          onClick={(e) => { e.stopPropagation(); removeItem(item.item_id) }}
                          className="p-1 rounded text-pine-500 hover:text-red-400 transition-colors"
                        >
                          <X size={14} />
                        </button>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}

            {/* Total & Confirm */}
            {items.length > 0 && (
              <div className="px-4 py-3 border-t border-pine-700/40 bg-pine-800/20 space-y-3">
                {/* Bulk discount */}
                <div className="flex items-center gap-2">
                  <span className="text-[10px] text-pine-400 uppercase tracking-wider">Bulk Discount:</span>
                  <div className="relative">
                    <input
                      type="number"
                      step="1"
                      min="0"
                      max="100"
                      value={bulkDiscount}
                      onChange={(e) => setBulkDiscount(e.target.value)}
                      placeholder="0"
                      className="vault-field w-16 px-2 py-0.5 rounded text-xs text-right pr-5 font-mono"
                    />
                    <span className="absolute right-1.5 top-1/2 -translate-y-1/2 text-[10px] text-pine-500">%</span>
                  </div>
                  <button
                    type="button"
                    onClick={applyBulkDiscount}
                    disabled={!bulkDiscount || parseFloat(bulkDiscount) <= 0}
                    className="px-2 py-0.5 rounded text-[10px] font-medium bg-mint/10 text-mint border border-mint/20 hover:bg-mint/20 disabled:opacity-40 transition-colors"
                  >
                    Apply
                  </button>
                </div>

                {/* Fee preview for Venmo */}
                {feePreview && parseFloat(feePreview.fee) > 0 && (
                  <div className="flex items-center gap-3 text-[10px]">
                    <span className="text-pine-400">Fee ({paymentMethod}):</span>
                    <span className="text-red-400 font-mono">-${parseFloat(feePreview.fee).toFixed(2)}</span>
                    <span className="text-pine-400">Net:</span>
                    <span className="text-mint font-mono">${parseFloat(feePreview.net).toFixed(2)}</span>
                  </div>
                )}

                {/* Total + Confirm */}
                <div className="flex items-center justify-between">
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
              </div>
            )}
          </div>
        </div>
      </div>

      <ConfirmDialog
        open={showConfirm}
        title="Confirm Sale"
        description={
          feePreview && parseFloat(feePreview.fee) > 0
            ? `Sell ${items.length} item${items.length !== 1 ? 's' : ''} for $${total.toFixed(2)} via ${paymentMethod}? Fee: $${parseFloat(feePreview.fee).toFixed(2)}, Net: $${parseFloat(feePreview.net).toFixed(2)}`
            : `Sell ${items.length} item${items.length !== 1 ? 's' : ''} for $${total.toFixed(2)} via ${paymentMethod}?`
        }
        confirmLabel="Complete Sale"
        loading={confirming}
        onConfirm={handleConfirm}
        onCancel={() => setShowConfirm(false)}
      />

      <CardDetailModal
        item={detailItem as Record<string, unknown> | null}
        onClose={() => setDetailItem(null)}
        onUpdated={() => {}}
      />
    </div>
  )
}
