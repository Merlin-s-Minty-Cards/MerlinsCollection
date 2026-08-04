'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { TrendingUp, Trash2, Star, RefreshCw } from 'lucide-react'
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

type ConfidenceLevel = 'high' | 'medium' | 'low'

function getMatchConfidence(query: string, cardName: string): ConfidenceLevel {
  const q = query.trim().toLowerCase()
  const name = cardName.toLowerCase()
  if (name === q) return 'high'
  if (name.startsWith(q) || q.startsWith(name)) return 'high'
  // Check if the query words all appear in the name
  const qWords = q.split(/\s+/).filter(Boolean)
  const allWordsMatch = qWords.every((w) => name.includes(w))
  if (allWordsMatch && qWords.length > 0) return 'medium'
  return 'low'
}

const CONFIDENCE_STYLES: Record<ConfidenceLevel, { bg: string; text: string; label: string }> = {
  high: { bg: 'bg-mint/15 border-mint/30', text: 'text-mint', label: 'High' },
  medium: { bg: 'bg-amber-500/15 border-amber-500/30', text: 'text-amber-400', label: 'Med' },
  low: { bg: 'bg-red-500/15 border-red-500/30', text: 'text-red-400', label: 'Low' },
}

// --- Coverage banner ---------------------------------------------------

export interface UnmatchedItem {
  item_id: string
  name: string
}

export interface MarketCoverage {
  total_items: number
  items_with_market_value: number
  catalog_cards: number
  catalog_cards_with_prices: number
  unmatched_sample: UnmatchedItem[]
}

export interface CoverageBannerState {
  summary: string
  catalogEmpty: boolean
  showUnmatched: boolean
  unmatchedItems: UnmatchedItem[]
}

/** Pure decision logic for the coverage banner — extracted so it's testable without mounting the page. */
export function getCoverageBannerState(coverage: MarketCoverage): CoverageBannerState {
  const {
    items_with_market_value,
    total_items,
    catalog_cards_with_prices,
    catalog_cards,
    unmatched_sample,
  } = coverage

  const summary = `${items_with_market_value}/${total_items} items priced · catalog ${catalog_cards_with_prices}/${catalog_cards} cards priced`
  const catalogEmpty = catalog_cards === 0
  const ratio = total_items > 0 ? items_with_market_value / total_items : 0

  return {
    summary,
    catalogEmpty,
    showUnmatched: ratio < 0.5,
    unmatchedItems: (unmatched_sample ?? []).slice(0, 10),
  }
}

// --- Sync status ---------------------------------------------------------

type SyncState = 'idle' | 'running' | 'completed' | 'failed'

interface SyncStatus {
  state: SyncState
  started_at: string | null
  finished_at: string | null
  priced_cards: number | null
  updated_items: number | null
  error: string | null
}

const IDLE_SYNC_STATUS: SyncStatus = {
  state: 'idle',
  started_at: null,
  finished_at: null,
  priced_cards: null,
  updated_items: null,
  error: null,
}

// --- Trend confidence ------------------------------------------------------

interface ConfidenceResponse {
  level: ConfidenceLevel
  points: number
  volatility_pct: string
  trend_pct: string
  reason: string
}

const TREND_CONFIDENCE_STYLES: Record<ConfidenceLevel, { bg: string; text: string; label: string }> = {
  high: { bg: 'bg-mint/15 border-mint/30', text: 'text-mint', label: 'High confidence' },
  medium: { bg: 'bg-amber-500/15 border-amber-500/30', text: 'text-amber-400', label: 'Medium confidence' },
  low: { bg: 'bg-pine-700/40 border-pine-600/40', text: 'text-pine-300', label: 'Low confidence' },
}

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

  // Coverage banner
  const [coverage, setCoverage] = useState<MarketCoverage | null>(null)

  // Sync
  const [syncStatus, setSyncStatus] = useState<SyncStatus>(IDLE_SYNC_STATUS)
  const [syncTriggerError, setSyncTriggerError] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Trend confidence
  const [confidence, setConfidence] = useState<ConfidenceResponse | null>(null)

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [])

  const loadCoverage = useCallback(async () => {
    if (!api.isAuthenticated) return
    try {
      const res = await api.get<MarketCoverage>('/market/coverage')
      setCoverage(res)
    } catch { setCoverage(null) }
  }, [api])

  useEffect(() => {
    loadCoverage()
  }, [loadCoverage])

  const pollSyncStatus = useCallback(async () => {
    try {
      const status = await api.get<SyncStatus>('/market/sync/status')
      setSyncStatus(status)
      if (status.state !== 'running') {
        stopPolling()
        if (status.state === 'completed') {
          loadCoverage()
        }
      }
    } catch {
      stopPolling()
    }
  }, [api, loadCoverage, stopPolling])

  useEffect(() => stopPolling, [stopPolling])

  const triggerSync = async () => {
    setSyncTriggerError(null)
    try {
      await api.post('/market/sync')
      setSyncStatus((prev) => ({ ...prev, state: 'running' }))
      stopPolling()
      pollRef.current = setInterval(pollSyncStatus, 3000)
    } catch (err) {
      if (err instanceof AdminApiError && err.status === 409) {
        setSyncTriggerError('A sync is already running')
      } else {
        setSyncTriggerError(err instanceof AdminApiError ? (err.detail ?? 'Failed to start sync') : 'Failed to start sync')
      }
    }
  }

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
    setConfidence(null)
    try {
      const res = await api.get<{ card_id: string; points: PricePoint[] }>(`/market/card/${card.card_id}/trend`, { days: 90 })
      setPriceHistory(res.points)
    } catch { setPriceHistory([]) }
    finally { setLoadingHistory(false) }

    try {
      const conf = await api.get<ConfidenceResponse>(`/market/card/${card.card_id}/confidence`, { days: 90 })
      setConfidence(conf)
    } catch { setConfidence(null) }
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

      {/* Coverage banner */}
      {coverage && (() => {
        const banner = getCoverageBannerState(coverage)
        return (
          <div className="vault-panel rounded-xl p-3 mb-6 text-xs space-y-2">
            <div className="flex items-center justify-between gap-3">
              <p className="text-pine-300">{banner.summary}</p>
              <button
                type="button"
                onClick={triggerSync}
                disabled={syncStatus.state === 'running'}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium text-mint bg-mint/10 border border-mint/25 hover:bg-mint/20 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex-shrink-0"
              >
                <RefreshCw size={12} className={syncStatus.state === 'running' ? 'animate-spin' : ''} />
                Sync Prices
              </button>
            </div>

            {banner.catalogEmpty && (
              <p className="text-amber-400">
                Catalog is empty — run backend/scripts/seed_catalog.py once, then press Sync Prices.
              </p>
            )}

            {syncTriggerError && <p className="text-red-400">{syncTriggerError}</p>}

            {syncStatus.state === 'completed' && (
              <p className="text-mint">
                Priced {syncStatus.priced_cards} cards, updated {syncStatus.updated_items} items
              </p>
            )}

            {syncStatus.state === 'failed' && (
              <p className="text-red-400">{syncStatus.error}</p>
            )}

            {banner.showUnmatched && banner.unmatchedItems.length > 0 && (
              <details>
                <summary className="cursor-pointer text-pine-400 select-none">Unmatched items</summary>
                <ul className="mt-1.5 space-y-0.5 text-pine-500 pl-3">
                  {banner.unmatchedItems.map((item) => (
                    <li key={item.item_id}>{item.name}</li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        )
      })()}

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
                  {results.map((card) => {
                    const matchConfidence = getMatchConfidence(query, card.name)
                    const style = CONFIDENCE_STYLES[matchConfidence]
                    return (
                      <button
                        key={card.card_id}
                        type="button"
                        onClick={() => loadPriceHistory(card)}
                        className={`w-full flex items-center justify-between px-3 py-2.5 text-left hover:bg-pine-800/50 transition-colors ${selectedCard?.card_id === card.card_id ? 'bg-pine-800/60' : ''}`}
                      >
                        <div className="min-w-0 flex-1">
                          <div className="text-xs text-pine-100 truncate flex items-center gap-2">
                            {card.name}
                            <span
                              title="name match quality"
                              className={`inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-medium border ${style.bg} ${style.text} flex-shrink-0`}
                            >
                              {style.label}
                            </span>
                          </div>
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
                    )
                  })}
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
                  <div className="flex items-center justify-between mb-2">
                    <h4 className="text-[11px] text-pine-400 uppercase tracking-wider">Price History (90d)</h4>
                    {confidence && (
                      <span
                        title={confidence.reason}
                        className={`inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-medium border ${TREND_CONFIDENCE_STYLES[confidence.level].bg} ${TREND_CONFIDENCE_STYLES[confidence.level].text}`}
                      >
                        {TREND_CONFIDENCE_STYLES[confidence.level].label}
                      </span>
                    )}
                  </div>
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
