'use client'

import { useCallback, useEffect, useState } from 'react'
import {
  BarChart3,
  Calendar,
  DollarSign,
  TrendingUp,
  ShoppingBag,
  ShoppingCart,
  ArrowRightLeft,
  RefreshCw,
  ChevronRight,
  ChevronLeft,
} from 'lucide-react'
import { useAdminApi, AdminApiError } from '@/lib/admin-api'
import PriceDisplay from '@/components/admin/shared/PriceDisplay'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Show {
  show_id: string
  name: string
  date: string
  location?: string
  [key: string]: unknown
}

interface ShowAnalytics {
  show_id: string
  date: string
  total_sold: string
  total_bought: string
  net_sales: string
  items_sold_count: number
  items_bought_count: number
  trades_count: number
  sell_through_rate?: number | null
  avg_margin?: string | null
  top_sale?: string | null
  [key: string]: unknown
}

type ViewMode = 'list' | 'detail'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDate(dateStr: string): string {
  try {
    const d = new Date(dateStr)
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
  } catch {
    return dateStr
  }
}

function getDefaultDateRange(): { start: string; end: string } {
  const end = new Date()
  const start = new Date()
  start.setMonth(start.getMonth() - 3) // Default to last 3 months
  return {
    start: start.toISOString().split('T')[0],
    end: end.toISOString().split('T')[0],
  }
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export default function AdminAnalyticsPage() {
  const api = useAdminApi()

  // Date range
  const defaultRange = getDefaultDateRange()
  const [startDate, setStartDate] = useState(defaultRange.start)
  const [endDate, setEndDate] = useState(defaultRange.end)

  // Shows
  const [shows, setShows] = useState<Show[]>([])
  const [loadingShows, setLoadingShows] = useState(true)

  // Analytics (date range)
  const [analytics, setAnalytics] = useState<ShowAnalytics[]>([])
  const [loadingAnalytics, setLoadingAnalytics] = useState(false)

  // Detail view
  const [viewMode, setViewMode] = useState<ViewMode>('list')
  const [selectedShow, setSelectedShow] = useState<Show | null>(null)
  const [showDetail, setShowDetail] = useState<ShowAnalytics | null>(null)
  const [loadingDetail, setLoadingDetail] = useState(false)

  // Generating
  const [generatingId, setGeneratingId] = useState<string | null>(null)

  // Messages
  const [message, setMessage] = useState<string | null>(null)

  // ---------------------------------------------------------------------------
  // Data fetching
  // ---------------------------------------------------------------------------

  const fetchShows = useCallback(async () => {
    if (!api.isAuthenticated) return
    setLoadingShows(true)
    try {
      const res = await api.get<{ shows: Show[] } | Show[]>('/shows')
      // Handle both array and {shows: [...]} responses
      const showsList = Array.isArray(res) ? res : res.shows ?? []
      setShows(showsList)
    } catch {
      setShows([])
    } finally {
      setLoadingShows(false)
    }
  }, [api])

  const fetchAnalyticsByDate = useCallback(async () => {
    if (!api.isAuthenticated || !startDate || !endDate) return
    setLoadingAnalytics(true)
    try {
      const res = await api.get<{ analytics: ShowAnalytics[] } | ShowAnalytics[]>(
        '/analytics/by-date',
        { start: startDate, end: endDate }
      )
      const list = Array.isArray(res) ? res : res.analytics ?? []
      setAnalytics(list)
    } catch {
      setAnalytics([])
    } finally {
      setLoadingAnalytics(false)
    }
  }, [api, startDate, endDate])

  const fetchShowDetail = useCallback(async (showId: string) => {
    if (!api.isAuthenticated) return
    setLoadingDetail(true)
    try {
      const res = await api.get<ShowAnalytics>(`/shows/${showId}/analytics`)
      setShowDetail(res)
    } catch {
      setShowDetail(null)
    } finally {
      setLoadingDetail(false)
    }
  }, [api])

  useEffect(() => {
    fetchShows()
  }, [fetchShows])

  useEffect(() => {
    fetchAnalyticsByDate()
  }, [fetchAnalyticsByDate])

  // ---------------------------------------------------------------------------
  // Actions
  // ---------------------------------------------------------------------------

  const generateAnalytics = async (showId: string) => {
    setGeneratingId(showId)
    setMessage(null)
    try {
      await api.post(`/shows/${showId}/analytics/generate`)
      setMessage('Analytics generated successfully')
      fetchAnalyticsByDate()
      // If viewing detail for this show, refresh it
      if (selectedShow?.show_id === showId) {
        fetchShowDetail(showId)
      }
    } catch (err) {
      setMessage(err instanceof AdminApiError ? (err.detail ?? 'Generation failed') : 'Generation failed')
    } finally {
      setGeneratingId(null)
    }
  }

  const openShowDetail = (show: Show) => {
    setSelectedShow(show)
    setViewMode('detail')
    fetchShowDetail(show.show_id)
  }

  const backToList = () => {
    setViewMode('list')
    setSelectedShow(null)
    setShowDetail(null)
  }

  // ---------------------------------------------------------------------------
  // Clear message on timeout
  // ---------------------------------------------------------------------------

  useEffect(() => {
    if (message) {
      const timer = setTimeout(() => setMessage(null), 4000)
      return () => clearTimeout(timer)
    }
  }, [message])

  // ---------------------------------------------------------------------------
  // Aggregate metrics for the period
  // ---------------------------------------------------------------------------

  const totalRevenue = analytics.reduce((sum, a) => sum + (parseFloat(a.total_sold) || 0), 0)
  const totalSpend = analytics.reduce((sum, a) => sum + (parseFloat(a.total_bought) || 0), 0)
  const netProfit = analytics.reduce((sum, a) => sum + (parseFloat(a.net_sales) || 0), 0)
  const totalShows = analytics.length

  // ---------------------------------------------------------------------------
  // Match analytics to shows for the list view
  // ---------------------------------------------------------------------------

  const showsWithAnalytics = shows
    .filter((show) => {
      // Only shows within date range
      if (!show.date) return false
      return show.date >= startDate && show.date <= endDate
    })
    .sort((a, b) => (b.date ?? '').localeCompare(a.date ?? ''))
    .map((show) => {
      const showAnalytic = analytics.find((a) => a.show_id === show.show_id)
      return { show, analytics: showAnalytic }
    })

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  if (viewMode === 'detail' && selectedShow) {
    return (
      <div className="p-6 lg:p-8 max-w-5xl">
        {/* Back button */}
        <button
          type="button"
          onClick={backToList}
          className="flex items-center gap-1 text-xs text-pine-400 hover:text-pine-200 transition-colors mb-4"
        >
          <ChevronLeft size={14} />
          Back to Dashboard
        </button>

        <header className="mb-6">
          <span className="font-mono text-[11px] uppercase tracking-[0.22em] text-mint/70">
            Show Analytics
          </span>
          <h1 className="text-xl font-semibold text-pine-100">{selectedShow.name}</h1>
          <p className="text-xs text-pine-400 mt-1">
            {formatDate(selectedShow.date)} {selectedShow.location && `• ${selectedShow.location}`}
          </p>
        </header>

        {/* Generate button */}
        <div className="mb-6">
          <button
            type="button"
            onClick={() => generateAnalytics(selectedShow.show_id)}
            disabled={generatingId === selectedShow.show_id}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-medium bg-mint/15 text-mint border border-mint/30 hover:bg-mint/25 disabled:opacity-40 transition-colors"
          >
            <RefreshCw size={13} className={generatingId === selectedShow.show_id ? 'animate-spin' : ''} />
            {generatingId === selectedShow.show_id ? 'Generating…' : 'Generate / Refresh Analytics'}
          </button>
        </div>

        {loadingDetail ? (
          <div className="vault-panel rounded-xl p-8 text-center text-xs text-pine-400">
            Loading analytics…
          </div>
        ) : showDetail ? (
          <div className="space-y-6">
            {/* Metrics grid */}
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
              <MetricCard label="Total Sold" value={showDetail.total_sold} icon={<ShoppingBag size={14} />} color="text-mint" />
              <MetricCard label="Total Bought" value={showDetail.total_bought} icon={<ShoppingCart size={14} />} color="text-blue-400" />
              <MetricCard label="Net Sales" value={showDetail.net_sales} icon={<DollarSign size={14} />} color="text-amber-400" />
              <MetricCard label="Items Sold" value={String(showDetail.items_sold_count)} icon={<ShoppingBag size={14} />} color="text-mint" isCount />
              <MetricCard label="Items Bought" value={String(showDetail.items_bought_count)} icon={<ShoppingCart size={14} />} color="text-blue-400" isCount />
              <MetricCard label="Trades" value={String(showDetail.trades_count)} icon={<ArrowRightLeft size={14} />} color="text-purple-400" isCount />
            </div>

            {/* Additional metrics */}
            <div className="vault-panel rounded-xl p-4 border border-pine-700/30">
              <h3 className="text-[11px] font-semibold uppercase tracking-wider text-pine-400 mb-3">
                Performance Details
              </h3>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                {showDetail.sell_through_rate != null && (
                  <div>
                    <div className="text-[10px] text-pine-500 uppercase mb-1">Sell-Through Rate</div>
                    <div className="text-sm font-mono text-pine-100">
                      {(showDetail.sell_through_rate * 100).toFixed(1)}%
                    </div>
                  </div>
                )}
                {showDetail.avg_margin && (
                  <div>
                    <div className="text-[10px] text-pine-500 uppercase mb-1">Avg Margin</div>
                    <PriceDisplay value={showDetail.avg_margin} className="text-sm text-pine-100" />
                  </div>
                )}
                {showDetail.top_sale && (
                  <div>
                    <div className="text-[10px] text-pine-500 uppercase mb-1">Top Sale</div>
                    <PriceDisplay value={showDetail.top_sale} className="text-sm text-amber-400" />
                  </div>
                )}
              </div>
            </div>
          </div>
        ) : (
          <div className="vault-panel rounded-xl p-8 text-center text-xs text-pine-500">
            No analytics generated yet. Click &quot;Generate / Refresh Analytics&quot; to compute a snapshot.
          </div>
        )}

        {/* Message */}
        {message && (
          <div className="mt-4 flex items-center gap-2 text-xs text-mint bg-mint/5 border border-mint/20 rounded-lg px-3 py-2">
            {message}
          </div>
        )}
      </div>
    )
  }

  // ---------------------------------------------------------------------------
  // List view (default)
  // ---------------------------------------------------------------------------

  return (
    <div className="p-6 lg:p-8 max-w-6xl">
      <header className="mb-6">
        <span className="font-mono text-[11px] uppercase tracking-[0.22em] text-mint/70">
          Analytics
        </span>
        <h1 className="text-xl font-semibold text-pine-100">Show Analytics Dashboard</h1>
        <p className="text-xs text-pine-400 mt-1">
          Performance metrics across your card shows
        </p>
      </header>

      {/* Date range picker */}
      <section className="vault-panel rounded-xl p-4 border border-pine-700/30 mb-6">
        <div className="flex items-center gap-4 flex-wrap">
          <Calendar size={15} className="text-mint" />
          <div className="flex items-center gap-2">
            <label className="text-[10px] text-pine-500 uppercase">From</label>
            <input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="vault-field px-3 py-1.5 rounded-lg text-xs font-mono"
            />
          </div>
          <div className="flex items-center gap-2">
            <label className="text-[10px] text-pine-500 uppercase">To</label>
            <input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="vault-field px-3 py-1.5 rounded-lg text-xs font-mono"
            />
          </div>
        </div>
      </section>

      {/* Summary cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
        <div className="vault-panel rounded-xl px-4 py-3 border border-pine-700/30">
          <div className="flex items-center gap-1.5 mb-1">
            <TrendingUp size={12} className="text-mint" />
            <span className="text-[10px] text-pine-500 uppercase tracking-wider">Revenue</span>
          </div>
          <PriceDisplay value={totalRevenue} className="text-lg text-mint" />
        </div>
        <div className="vault-panel rounded-xl px-4 py-3 border border-pine-700/30">
          <div className="flex items-center gap-1.5 mb-1">
            <ShoppingCart size={12} className="text-blue-400" />
            <span className="text-[10px] text-pine-500 uppercase tracking-wider">Spend</span>
          </div>
          <PriceDisplay value={totalSpend} className="text-lg text-blue-400" />
        </div>
        <div className="vault-panel rounded-xl px-4 py-3 border border-pine-700/30">
          <div className="flex items-center gap-1.5 mb-1">
            <DollarSign size={12} className="text-amber-400" />
            <span className="text-[10px] text-pine-500 uppercase tracking-wider">Net Profit</span>
          </div>
          <PriceDisplay value={netProfit} className={`text-lg ${netProfit >= 0 ? 'text-mint' : 'text-red-400'}`} />
        </div>
        <div className="vault-panel rounded-xl px-4 py-3 border border-pine-700/30">
          <div className="flex items-center gap-1.5 mb-1">
            <BarChart3 size={12} className="text-purple-400" />
            <span className="text-[10px] text-pine-500 uppercase tracking-wider">Shows</span>
          </div>
          <div className="text-lg font-mono text-pine-100">{totalShows}</div>
        </div>
      </div>

      {/* Message */}
      {message && (
        <div className="flex items-center gap-2 text-xs text-mint bg-mint/5 border border-mint/20 rounded-lg px-3 py-2 mb-4">
          {message}
        </div>
      )}

      {/* Shows list */}
      <section>
        <h2 className="text-xs font-semibold text-pine-200 uppercase tracking-wider mb-3">
          Shows in Period
        </h2>
        {loadingShows || loadingAnalytics ? (
          <div className="vault-panel rounded-xl p-6 text-center text-xs text-pine-400">
            Loading…
          </div>
        ) : showsWithAnalytics.length === 0 ? (
          <div className="vault-panel rounded-xl p-6 text-center text-xs text-pine-500">
            No shows found in the selected date range
          </div>
        ) : (
          <div className="space-y-2">
            {showsWithAnalytics.map(({ show, analytics: showAnalytic }) => (
              <div
                key={show.show_id}
                className="vault-panel rounded-xl px-4 py-3 border border-pine-700/30 hover:border-pine-600/50 transition-colors cursor-pointer"
                onClick={() => openShowDetail(show)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') openShowDetail(show)
                }}
              >
                <div className="flex items-center justify-between gap-4">
                  <div className="flex items-center gap-4 min-w-0 flex-1">
                    <div className="min-w-0">
                      <div className="text-sm text-pine-100 font-medium truncate">{show.name}</div>
                      <div className="text-[10px] text-pine-500 mt-0.5">
                        {formatDate(show.date)} {show.location && `• ${show.location}`}
                      </div>
                    </div>
                  </div>

                  {showAnalytic ? (
                    <div className="flex items-center gap-4 flex-shrink-0">
                      <div className="text-right">
                        <div className="text-[10px] text-pine-500">Sold</div>
                        <PriceDisplay value={showAnalytic.total_sold} className="text-xs text-mint" />
                      </div>
                      <div className="text-right">
                        <div className="text-[10px] text-pine-500">Bought</div>
                        <PriceDisplay value={showAnalytic.total_bought} className="text-xs text-blue-400" />
                      </div>
                      <div className="text-right">
                        <div className="text-[10px] text-pine-500">Net</div>
                        <PriceDisplay
                          value={showAnalytic.net_sales}
                          className={`text-xs ${parseFloat(showAnalytic.net_sales) >= 0 ? 'text-mint' : 'text-red-400'}`}
                        />
                      </div>
                      <div className="text-right hidden sm:block">
                        <div className="text-[10px] text-pine-500">Items S/B/T</div>
                        <span className="text-xs font-mono text-pine-300">
                          {showAnalytic.items_sold_count}/{showAnalytic.items_bought_count}/{showAnalytic.trades_count}
                        </span>
                      </div>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation()
                          generateAnalytics(show.show_id)
                        }}
                        disabled={generatingId === show.show_id}
                        className="p-1.5 rounded text-pine-500 hover:text-mint hover:bg-mint/10 disabled:opacity-40 transition-colors"
                        title="Regenerate analytics"
                      >
                        <RefreshCw size={13} className={generatingId === show.show_id ? 'animate-spin' : ''} />
                      </button>
                      <ChevronRight size={14} className="text-pine-600" />
                    </div>
                  ) : (
                    <div className="flex items-center gap-3 flex-shrink-0">
                      <span className="text-[10px] text-pine-600 italic">No analytics</span>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation()
                          generateAnalytics(show.show_id)
                        }}
                        disabled={generatingId === show.show_id}
                        className="inline-flex items-center gap-1 px-2.5 py-1 rounded text-[10px] font-medium bg-mint/10 text-mint border border-mint/20 hover:bg-mint/20 disabled:opacity-40 transition-colors"
                      >
                        <RefreshCw size={11} className={generatingId === show.show_id ? 'animate-spin' : ''} />
                        Generate
                      </button>
                      <ChevronRight size={14} className="text-pine-600" />
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Metric Card sub-component
// ---------------------------------------------------------------------------

function MetricCard({
  label,
  value,
  icon,
  color,
  isCount,
}: {
  label: string
  value: string
  icon: React.ReactNode
  color: string
  isCount?: boolean
}) {
  return (
    <div className="vault-panel rounded-xl px-3 py-3 border border-pine-700/30">
      <div className="flex items-center gap-1.5 mb-1">
        <span className={color}>{icon}</span>
        <span className="text-[10px] text-pine-500 uppercase tracking-wider">{label}</span>
      </div>
      {isCount ? (
        <div className={`text-base font-mono ${color}`}>{value}</div>
      ) : (
        <PriceDisplay value={value} className={`text-base ${color}`} />
      )}
    </div>
  )
}
