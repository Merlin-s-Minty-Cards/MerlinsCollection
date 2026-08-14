'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { TrendingUp, Trash2, Star, RefreshCw, PackagePlus } from 'lucide-react'
import { useAdminApi, AdminApiError } from '@/lib/admin-api'
import { describeApiError, type ApiErrorDescription } from '@/lib/admin-error'
import { getCoverageBannerState, type MarketCoverage } from '@/lib/market-coverage'
import { MONEY_PARSE_MESSAGE, parseMoney } from '@/lib/money'
import SearchInput from '@/components/admin/shared/SearchInput'
import PriceDisplay from '@/components/admin/shared/PriceDisplay'
import CardPickerRow, { type PickerCard } from '@/components/admin/shared/CardPickerRow'
import SetCombobox from '@/components/shared/SetCombobox'
import { useCatalogSets, toComboboxSets } from '@/lib/use-catalog-sets'

interface CatalogCard extends PickerCard {
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

// --- Catalog sync status -------------------------------------------------

interface CatalogSyncStatus {
  state: SyncState
  started_at: string | null
  finished_at: string | null
  sets_checked: number | null
  new_sets: string[] | null
  cards_added: number | null
  error: string | null
}

const IDLE_CATALOG_SYNC_STATUS: CatalogSyncStatus = {
  state: 'idle',
  started_at: null,
  finished_at: null,
  sets_checked: null,
  new_sets: null,
  cards_added: null,
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

// --- Shared poll helper ---------------------------------------------------

/** Clear a poll interval ref. Shared by price-sync and catalog-sync polling. */
function clearPollRef(ref: { current: ReturnType<typeof setInterval> | null }) {
  if (ref.current) {
    clearInterval(ref.current)
    ref.current = null
  }
}

export default function AdminMarketPage() {
  const api = useAdminApi()
  const [activeTab, setActiveTab] = useState<Tab>('search')

  // Search
  const [query, setQuery] = useState('')
  const [number, setNumber] = useState('')
  const [setId, setSetId] = useState('')
  const { sets: catalogSets } = useCatalogSets()
  const [results, setResults] = useState<CatalogCard[]>([])
  const [searching, setSearching] = useState(false)
  // Described, not a bare boolean — see the note in lib/admin-error.ts.
  const [searchError, setSearchError] = useState<ApiErrorDescription | null>(null)
  // Which search is current — see the Buy page for why: a slow catalog search
  // means several are in flight and they do not resolve in order.
  const searchSeqRef = useRef(0)

  // Detail
  const [selectedCard, setSelectedCard] = useState<CatalogCard | null>(null)
  const [priceHistory, setPriceHistory] = useState<PricePoint[]>([])
  const [loadingHistory, setLoadingHistory] = useState(false)

  // Watchlist
  const [watchlist, setWatchlist] = useState<WatchlistEntry[]>([])
  const [loadingWatchlist, setLoadingWatchlist] = useState(false)

  // Coverage banner
  const [coverage, setCoverage] = useState<MarketCoverage | null>(null)

  // Price sync
  const [syncStatus, setSyncStatus] = useState<SyncStatus>(IDLE_SYNC_STATUS)
  const [syncTriggerError, setSyncTriggerError] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Catalog sync
  const [catalogSyncStatus, setCatalogSyncStatus] = useState<CatalogSyncStatus>(IDLE_CATALOG_SYNC_STATUS)
  const [catalogSyncTriggerError, setCatalogSyncTriggerError] = useState<string | null>(null)
  const catalogPollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Unmount guard — prevents setState after unmount (React 18 console warning)
  const unmountedRef = useRef(false)

  // Trend confidence
  const [confidence, setConfidence] = useState<ConfidenceResponse | null>(null)

  const stopPolling = useCallback(() => clearPollRef(pollRef), [])
  const stopCatalogPolling = useCallback(() => clearPollRef(catalogPollRef), [])

  const loadCoverage = useCallback(async () => {
    if (!api.isAuthenticated) return
    try {
      const res = await api.get<MarketCoverage>('/market/coverage')
      if (!unmountedRef.current) setCoverage(res)
    } catch {
      if (!unmountedRef.current) setCoverage(null)
    }
  }, [api])

  useEffect(() => {
    loadCoverage()
  }, [loadCoverage])

  // --- Price sync polling ---
  const pollSyncStatus = useCallback(async () => {
    try {
      const status = await api.get<SyncStatus>('/market/sync/status')
      if (unmountedRef.current) return
      setSyncStatus(status)
      if (status.state !== 'running') {
        stopPolling()
        if (status.state === 'completed') {
          loadCoverage()
        }
      }
    } catch {
      if (!unmountedRef.current) stopPolling()
    }
  }, [api, loadCoverage, stopPolling])

  // --- Catalog sync polling ---
  const pollCatalogSyncStatus = useCallback(async () => {
    try {
      const status = await api.get<CatalogSyncStatus>('/market/catalog-sync/status')
      if (unmountedRef.current) return
      setCatalogSyncStatus(status)
      if (status.state !== 'running') {
        stopCatalogPolling()
        if (status.state === 'completed' && (status.cards_added ?? 0) > 0) {
          loadCoverage()
        }
      }
    } catch {
      if (!unmountedRef.current) stopCatalogPolling()
    }
  }, [api, loadCoverage, stopCatalogPolling])

  // Clean up both poll intervals on unmount, and set the guard flag
  useEffect(() => {
    return () => {
      unmountedRef.current = true
      stopPolling()
      stopCatalogPolling()
    }
  }, [stopPolling, stopCatalogPolling])

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

  const triggerCatalogSync = async () => {
    setCatalogSyncTriggerError(null)
    try {
      await api.post('/market/catalog-sync')
      setCatalogSyncStatus((prev) => ({ ...prev, state: 'running' }))
      stopCatalogPolling()
      catalogPollRef.current = setInterval(pollCatalogSyncStatus, 3000)
    } catch (err) {
      if (err instanceof AdminApiError && err.status === 409) {
        setCatalogSyncTriggerError('A catalog sync is already running')
      } else {
        setCatalogSyncTriggerError(err instanceof AdminApiError ? (err.detail ?? 'Failed to start catalog sync') : 'Failed to start catalog sync')
      }
    }
  }

  const searchCatalog = useCallback(async (q: string, num: string, set: string) => {
    if (!q.trim() && !num.trim() && !set.trim()) {
      setResults([]); setSearchError(null); return
    }
    if (!api.isAuthenticated) return
    const seq = ++searchSeqRef.current
    setSearching(true)
    setSearchError(null)
    const params: Record<string, string> = {}
    if (q.trim()) params.name = q.trim()
    if (num.trim()) params.number = num.trim()
    if (set.trim()) params.set_id = set.trim()
    try {
      const res = await api.get<{ items: CatalogCard[]; total: number }>('/market/search', params)
      if (seq !== searchSeqRef.current) return
      setResults(res.items.slice(0, 20))
    } catch (err) {
      if (seq !== searchSeqRef.current) return
      setResults([])
      setSearchError(describeApiError(err))
    } finally {
      if (seq === searchSeqRef.current) setSearching(false)
    }
  }, [api])

  useEffect(() => {
    const timeout = setTimeout(() => searchCatalog(query, number, setId), 350)
    return () => clearTimeout(timeout)
  }, [query, number, setId, searchCatalog])

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
    // A prompt is still a human typing money, so it gets the same discipline as
    // a MoneyInput: parseMoney, and `=== null` rather than falsiness. Cancelling
    // (null) or leaving it blank means "no target"; an unreadable amount is an
    // error the admin is told about, never a silently truncated 1.
    let targetBuyPrice: number | null = null
    if (target !== null && target.trim() !== '') {
      targetBuyPrice = parseMoney(target)
      if (targetBuyPrice === null) {
        alert(MONEY_PARSE_MESSAGE)
        return
      }
    }
    try {
      await api.post('/watchlist', {
        card_id: card.card_id,
        name: card.name,
        set_name: card.set_name || card.set_id || '',
        target_buy_price: targetBuyPrice,
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
    <div className="p-6 lg:p-8">
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
              <div className="flex items-center gap-2 flex-shrink-0">
                <button
                  type="button"
                  onClick={triggerSync}
                  disabled={syncStatus.state === 'running'}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium text-mint bg-mint/10 border border-mint/25 hover:bg-mint/20 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <RefreshCw size={12} className={syncStatus.state === 'running' ? 'animate-spin' : ''} />
                  Sync Prices
                </button>
                <button
                  type="button"
                  onClick={triggerCatalogSync}
                  disabled={catalogSyncStatus.state === 'running'}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium text-mint bg-mint/10 border border-mint/25 hover:bg-mint/20 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <PackagePlus size={12} className={catalogSyncStatus.state === 'running' ? 'animate-spin' : ''} />
                  Check for New Sets
                </button>
              </div>
            </div>

            <p className="text-pine-500 text-[10px]">
              Prices refresh values for cards you hold. New Sets adds newly released cards to the catalog.
            </p>

            {/* The summary line above says "80/100 items priced", which is one
                number meaning two things. This splits it: a hand-valued card is
                priced and can never be synced, so counting it as a gap makes the
                worklist permanently unfinishable. */}
            {banner.valuation && (
              <p className="text-pine-500 text-[10px]">{banner.valuation}</p>
            )}

            {banner.cycle && (
              <p className={banner.cycleBehind ? 'text-amber-400' : 'text-pine-500'}>
                {banner.cycle}
              </p>
            )}

            {banner.catalogEmpty && (
              <p className="text-amber-400">
                Catalog is empty — run backend/scripts/seed_catalog.py once, then press Sync Prices.
              </p>
            )}

            {syncTriggerError && <p className="text-red-400">{syncTriggerError}</p>}
            {catalogSyncTriggerError && <p className="text-red-400">{catalogSyncTriggerError}</p>}

            {syncStatus.state === 'completed' && (
              <p className="text-mint">
                Priced {syncStatus.priced_cards} cards, updated {syncStatus.updated_items} items
              </p>
            )}

            {syncStatus.state === 'failed' && (
              <p className="text-red-400">{syncStatus.error}</p>
            )}

            {catalogSyncStatus.state === 'completed' && (
              <p className="text-mint">
                Checked {catalogSyncStatus.sets_checked} sets · added {catalogSyncStatus.cards_added} cards from {catalogSyncStatus.new_sets?.length ?? 0} new set(s)
              </p>
            )}

            {catalogSyncStatus.state === 'failed' && (
              <p className="text-red-400">{catalogSyncStatus.error}</p>
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
            <div className="grid grid-cols-2 gap-2">
              <input
                aria-label="Card number"
                value={number}
                placeholder="Card #"
                className="vault-field w-full rounded-lg px-2.5 py-1.5 text-xs"
                onChange={(e) => setNumber(e.target.value)}
              />
              <SetCombobox
                sets={toComboboxSets(catalogSets)}
                value={setId}
                onChange={setSetId}
                inputId="market-search-set"
                ariaLabel="Set"
                placeholder="All sets"
                emptyLabel="All sets"
                className="vault-field w-full rounded-lg px-2.5 py-1.5 text-xs"
              />
            </div>
            <div className="vault-panel rounded-xl overflow-hidden max-h-[500px] overflow-y-auto vault-scroll">
              {searching ? (
                <div className="p-4 text-xs text-pine-400">Searching…</div>
              ) : searchError ? (
                /* Deliberately distinct from "no cards found": a failed request
                   dressed up as an empty catalog is what made this bug
                   undiagnosable from the UI. */
                <div className="p-4 space-y-2">
                  <p className="text-xs text-red-400">{searchError.message}</p>
                  {searchError.retryable && (
                    <button
                      type="button"
                      onClick={() => searchCatalog(query, number, setId)}
                      className="flex items-center gap-1.5 text-[11px] text-pine-300 hover:text-mint transition-colors"
                    >
                      <RefreshCw size={12} />
                      Retry
                    </button>
                  )}
                </div>
              ) : results.length === 0 && (query || number || setId) ? (
                <div className="p-4 text-xs text-pine-500">No cards found in catalog</div>
              ) : (
                <div className="divide-y divide-pine-700/25">
                  {results.map((card) => {
                    const matchConfidence = getMatchConfidence(query, card.name)
                    const style = CONFIDENCE_STYLES[matchConfidence]
                    return (
                      // The star used to be a <button> nested INSIDE the row
                      // button — invalid HTML, and only `stopPropagation` kept
                      // it from also loading the price history. As a
                      // CardPickerRow `action` the two are siblings.
                      <CardPickerRow
                        key={card.card_id}
                        card={card}
                        selected={selectedCard?.card_id === card.card_id}
                        onSelect={loadPriceHistory}
                        nameBadge={
                          <span
                            title="name match quality"
                            className={`inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-medium border ${style.bg} ${style.text} flex-shrink-0`}
                          >
                            {style.label}
                          </span>
                        }
                        action={
                          <button
                            type="button"
                            onClick={() => addToWatchlist(card)}
                            className="p-1 text-pine-500 hover:text-amber-400 transition-colors"
                            title="Add to watchlist"
                          >
                            <Star size={13} />
                          </button>
                        }
                      />
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
