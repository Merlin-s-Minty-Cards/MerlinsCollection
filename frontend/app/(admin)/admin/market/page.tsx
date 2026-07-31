'use client'

import { useCallback, useEffect, useState } from 'react'
import { TrendingUp, Plus, Trash2, Star, Search as SearchIcon } from 'lucide-react'
import { useAdminApi, AdminApiError } from '@/lib/admin-api'
import SearchInput from '@/components/admin/shared/SearchInput'
import PriceDisplay from '@/components/admin/shared/PriceDisplay'

interface CatalogCard {
  card_id: string
  name: string
  set_id?: string
  set_name?: string
  rarity?: string
  prices?: Record<string, unknown>
  [key: string]: unknown
}

interface PricePoint {
  date: string
  price: string | number
  finish?: string
}

interface WatchlistEntry {
  entry_id: string
  card_id: string
  name: string
  set_name: string
  target_buy_price?: string | null
  notes?: string | null
  added_at: string
}

type Tab = 'search' | 'watchlist'

export default function AdminMarketPage() {
  const api = useAdminApi()
  const [activeTab, setActiveTab] = useState<Tab>('search')

  // Search
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<CatalogCard[]>([])
  const [searching, setSearching] = useState(false)

  // Detail
  const [selectedCard, setSelectedCard] = useState<CatalogCard | null>(null)
  const [priceHistory, setPriceHistory] = useState<PricePoint[]>([])
  const [loadingHistory, setLoadingHistory] = useState(false)

  // Watchlist
  const [watchlist, setWatchlist] = useState<WatchlistEntry[]>([])
  const [loadingWatchlist, setLoadingWatchlist] = useState(false)

  const searchCatalog = useCallback(async (q: string) => {
    if (!q.trim() || !api.isAuthenticated) { setResults([]); return }
    setSearching(true)
    try {
      const res = await api.get<{ items: CatalogCard[]; total: number }>('/market/search', { name: q })
      setResults(res.items.slice(0, 20))
    } catch { setResults([]) }
    finally { setSearching(false) }
  }, [api])

  useEffect(() => {
    const timeout = setTimeout(() => searchCatalog(query), 350)
    return () => clearTimeout(timeout)
  }, [query, searchCatalog])

  const loadPriceHistory = async (card: CatalogCard) => {
    setSelectedCard(card)
    setLoadingHistory(true)
    try {
      const res = await api.get<{ card_id: string; points: PricePoint[] }>(`/market/card/${card.card_id}/trend`, { days: 90 })
      setPriceHistory(res.points)
    } catch { setPriceHistory([]) }
    finally { setLoadingHistory(false) }
  }

  const addToWatchlist = async (card: CatalogCard) => {
    const target = prompt('Target buy price (optional):')
    try {
      await api.post('/watchlist', {
        card_id: card.card_id,
        name: card.name,
        set_name: card.set_name || card.set_id || '',
        target_buy_price: target ? parseFloat(target) : null,
      })
      loadWatchlist()
    } catch (err) {
      alert(err instanceof AdminApiError ? err.detail : 'Failed to add')
    }
  }

  const loadWatchlist = useCallback(async () => {
    if (!api.isAuthenticated) return
    setLoadingWatchlist(true)
    try {
      const res = await api.get<{ entries: WatchlistEntry[] }>('/watchlist')
      setWatchlist(res.entries)
    } catch { setWatchlist([]) }
    finally { setLoadingWatchlist(false) }
  }, [api])

  useEffect(() => {
    if (activeTab === 'watchlist') loadWatchlist()
  }, [activeTab, loadWatchlist])

  const removeFromWatchlist = async (entryId: string) => {
    try {
      await api.del(`/watchlist/${entryId}`)
      setWatchlist((prev) => prev.filter((e) => e.entry_id !== entryId))
    } catch (err) {
      alert(err instanceof AdminApiError ? err.detail : 'Failed to remove')
    }
  }

  return (
    <div className="p-6 lg:p-8 max-w-5xl">
      <header className="mb-6">
        <span className="font-mono text-[11px] uppercase tracking-[0.22em] text-mint/70">Market</span>
        <h1 className="text-xl font-semibold text-pine-100">Catalog & Watchlist</h1>
      </header>

      {/* Tabs */}
      <div className="flex gap-1 mb-6 border-b border-pine-700/40 pb-px">
        {([['search', 'Search'], ['watchlist', 'Watchlist']] as [Tab, string][]).map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => setActiveTab(key)}
            className={`px-4 py-2 text-xs font-medium rounded-t-lg transition-colors ${
              activeTab === key
                ? 'bg-pine-800/60 text-mint border border-pine-700/40 border-b-transparent -mb-px'
                : 'text-pine-400 hover:text-pine-200'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {activeTab === 'search' && (
        <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
          {/* Search + Results */}
          <div className="lg:col-span-2 space-y-4">
            <SearchInput value={query} onChange={setQuery} placeholder="Search catalog by name…" />
            <div className="vault-panel rounded-xl overflow-hidden max-h-[500px] overflow-y-auto vault-scroll">
              {searching ? (
                <div className="p-4 text-xs text-pine-400">Searching…</div>
              ) : results.length === 0 && query ? (
                <div className="p-4 text-xs text-pine-500">No cards found in catalog</div>
              ) : (
                <div className="divide-y divide-pine-700/25">
                  {results.map((card) => (
                    <button
                      key={card.card_id}
                      type="button"
                      onClick={() => loadPriceHistory(card)}
                      className={`w-full flex items-center justify-between px-3 py-2.5 text-left hover:bg-pine-800/50 transition-colors ${selectedCard?.card_id === card.card_id ? 'bg-pine-800/60' : ''}`}
                    >
                      <div className="min-w-0">
                        <div className="text-xs text-pine-100 truncate">{card.name}</div>
                        <div className="text-[10px] text-pine-400">{card.set_name || card.set_id} {card.rarity && `· ${card.rarity}`}</div>
                      </div>
                      <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); addToWatchlist(card) }}
                        className="p-1 text-pine-500 hover:text-amber-400 transition-colors shrink-0"
                        title="Add to watchlist"
                      >
                        <Star size={13} />
                      </button>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Detail / Price Trend */}
          <div className="lg:col-span-3">
            {selectedCard ? (
              <div className="vault-panel rounded-xl p-4 space-y-4">
                <div className="flex items-start justify-between">
                  <div>
                    <h3 className="text-sm font-semibold text-pine-100">{selectedCard.name}</h3>
                    <p className="text-xs text-pine-400">{selectedCard.set_name || selectedCard.set_id} {selectedCard.rarity && `· ${selectedCard.rarity}`}</p>
                  </div>
                  <button type="button" onClick={() => addToWatchlist(selectedCard)} className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-[11px] font-medium text-amber-400 bg-amber-500/10 border border-amber-500/20 hover:bg-amber-500/20 transition-colors">
                    <Star size={11} />
                    Watch
                  </button>
                </div>

                {/* Price History Table */}
                <div>
                  <h4 className="text-[11px] text-pine-400 uppercase tracking-wider mb-2">Price History (90d)</h4>
                  {loadingHistory ? (
                    <div className="text-xs text-pine-400">Loading…</div>
                  ) : priceHistory.length === 0 ? (
                    <div className="text-xs text-pine-500">No price data available</div>
                  ) : (
                    <div className="space-y-1 max-h-60 overflow-y-auto vault-scroll">
                      {priceHistory.map((pt, idx) => (
                        <div key={idx} className="flex items-center justify-between px-2 py-1.5 rounded bg-pine-800/30 text-xs">
                          <span className="text-pine-300">{pt.date}</span>
                          {pt.finish && <span className="text-pine-500 text-[10px]">{pt.finish}</span>}
                          <PriceDisplay value={pt.price} className="text-mint text-xs" />
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ) : (
              <div className="vault-panel rounded-xl p-8 text-center">
                <TrendingUp size={32} className="text-pine-600 mx-auto mb-2" />
                <p className="text-xs text-pine-500">Select a card to view price data</p>
              </div>
            )}
          </div>
        </div>
      )}

      {activeTab === 'watchlist' && (
        <div className="vault-panel rounded-xl overflow-hidden">
          {loadingWatchlist ? (
            <div className="p-6 text-center text-xs text-pine-400">Loading watchlist…</div>
          ) : watchlist.length === 0 ? (
            <div className="p-6 text-center text-xs text-pine-500">
              <Star size={24} className="text-pine-600 mx-auto mb-2" />
              No cards on your watchlist yet. Search the catalog and add cards to watch.
            </div>
          ) : (
            <div className="divide-y divide-pine-700/25">
              {watchlist.map((entry) => (
                <div key={entry.entry_id} className="flex items-center justify-between px-4 py-3">
                  <div className="min-w-0">
                    <div className="text-xs text-pine-100 font-medium">{entry.name}</div>
                    <div className="text-[10px] text-pine-400">
                      {entry.set_name}
                      {entry.target_buy_price && <> · Target: <PriceDisplay value={entry.target_buy_price} className="text-[10px] text-amber-400 inline" /></>}
                    </div>
                    {entry.notes && <div className="text-[10px] text-pine-500 mt-0.5">{entry.notes}</div>}
                  </div>
                  <button type="button" onClick={() => removeFromWatchlist(entry.entry_id)} className="p-1.5 rounded text-pine-500 hover:text-red-400 transition-colors" title="Remove">
                    <Trash2 size={13} />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
