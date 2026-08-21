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
  Package,
} from 'lucide-react'
import { useAdminApi, AdminApiError } from '@/lib/admin-api'
import { formatISODate, toLocalISODate } from '@/lib/dates'
import PriceDisplay from '@/components/admin/shared/PriceDisplay'
import SignedAmount from '@/components/admin/shared/SignedAmount'
import TransactionGroups, {
  type ArchiveTransaction,
  type VoidTarget,
} from '@/components/admin/shared/TransactionGroups'
import DataTable, { type Column } from '@/components/admin/shared/DataTable'

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
  inventory_value_at_start?: string | null
  /**
   * RFC 0010 T11. A snapshot is a stored point-in-time record, so voiding a
   * transaction behind it leaves it wrong by construction. It is never
   * rewritten silently and never served silently — regenerating is the only
   * thing that clears this.
   */
  stale?: boolean
  [key: string]: unknown
}

interface DailyAnalytics {
  date: string
  total_sold: string
  total_bought: string
  net_sales: string
  items_sold_count: number
  items_bought_count: number
  trades_count: number
  inventory_value_at_start: string
  sell_through_rate: string | null
}

type Tab = 'daily' | 'shows'
type ShowViewMode = 'list' | 'detail'

/** One row of the Shows-tab table — a `Show` joined to its (possibly
 * missing) analytics snapshot. Extends `Show` (which already carries the
 * `[key: string]: unknown` index signature `DataTable`'s generic needs)
 * rather than wrapping it in `{ show, analytics }`, so `keyField="show_id"`
 * and `onRowClick` can both work off the row directly. */
interface ShowRow extends Show {
  analytics?: ShowAnalytics
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getDefaultDateRange(): { start: string; end: string } {
  const end = new Date()
  const start = new Date()
  start.setMonth(start.getMonth() - 3) // Default to last 3 months
  // Local, never `toISOString()` — that is the UTC date, so after 5pm Pacific
  // the range ended tomorrow and disagreed with the pickers rendering it.
  return {
    start: toLocalISODate(start),
    end: toLocalISODate(end),
  }
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export default function AdminAnalyticsPage() {
  const api = useAdminApi()
  const [activeTab, setActiveTab] = useState<Tab>('daily')

  // === Daily view state ===
  const [availableDates, setAvailableDates] = useState<string[]>([])
  const [loadingDates, setLoadingDates] = useState(false)
  const [selectedDate, setSelectedDate] = useState<string | null>(null)
  const [dailyData, setDailyData] = useState<DailyAnalytics | null>(null)
  const [loadingDaily, setLoadingDaily] = useState(false)
  const [transactions, setTransactions] = useState<ArchiveTransaction[]>([])
  const [loadingTxns, setLoadingTxns] = useState(false)

  // === Shows view state ===
  const defaultRange = getDefaultDateRange()
  const [startDate, setStartDate] = useState(defaultRange.start)
  const [endDate, setEndDate] = useState(defaultRange.end)
  const [shows, setShows] = useState<Show[]>([])
  const [loadingShows, setLoadingShows] = useState(true)
  const [analytics, setAnalytics] = useState<ShowAnalytics[]>([])
  const [loadingAnalytics, setLoadingAnalytics] = useState(false)
  const [showViewMode, setShowViewMode] = useState<ShowViewMode>('list')
  const [selectedShow, setSelectedShow] = useState<Show | null>(null)
  const [showDetail, setShowDetail] = useState<ShowAnalytics | null>(null)
  const [loadingDetail, setLoadingDetail] = useState(false)
  const [generatingId, setGeneratingId] = useState<string | null>(null)
  // RFC 0013 T4e — server-side sort via services/shows_sort.py, the same
  // registry `/admin/shows` uses. `null` keeps this tab's existing
  // date-descending default (applied client-side below, in
  // `showsWithAnalytics`) untouched.
  const [sortKey, setSortKey] = useState<string | null>(null)
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')

  // Shared
  const [message, setMessage] = useState<string | null>(null)

  // ---------------------------------------------------------------------------
  // Daily view data fetching
  // ---------------------------------------------------------------------------

  const fetchAvailableDates = useCallback(async () => {
    if (!api.isAuthenticated) return
    setLoadingDates(true)
    try {
      const res = await api.get<{ dates: string[] }>('/analytics/dates')
      setAvailableDates(res.dates ?? [])
    } catch {
      setAvailableDates([])
    } finally {
      setLoadingDates(false)
    }
  }, [api])

  const fetchDailyData = useCallback(async (date: string) => {
    if (!api.isAuthenticated || !date) return
    setLoadingDaily(true)
    setLoadingTxns(true)
    try {
      const [daily, txns] = await Promise.all([
        api.get<DailyAnalytics>('/analytics/daily', { date }),
        api.get<{ items: ArchiveTransaction[] }>('/transactions', { start: date, end: date }),
      ])
      setDailyData(daily)
      setTransactions(txns.items ?? [])
    } catch {
      setDailyData(null)
      setTransactions([])
    } finally {
      setLoadingDaily(false)
      setLoadingTxns(false)
    }
  }, [api])

  useEffect(() => {
    if (activeTab === 'daily') fetchAvailableDates()
  }, [activeTab, fetchAvailableDates])

  useEffect(() => {
    if (activeTab === 'daily' && selectedDate) {
      fetchDailyData(selectedDate)
    }
  }, [activeTab, selectedDate, fetchDailyData])

  // ---------------------------------------------------------------------------
  // Shows view data fetching
  // ---------------------------------------------------------------------------

  const fetchShows = useCallback(async () => {
    if (!api.isAuthenticated) return
    setLoadingShows(true)
    try {
      const params: Record<string, string> = {}
      if (sortKey) params.sort = `${sortKey}_${sortDir}`
      const res = await api.get<{ shows: Show[] } | Show[]>('/shows', params)
      const showsList = Array.isArray(res) ? res : res.shows ?? []
      setShows(showsList)
    } catch {
      setShows([])
    } finally {
      setLoadingShows(false)
    }
  }, [api, sortKey, sortDir])

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
    if (activeTab === 'shows') fetchShows()
  }, [activeTab, fetchShows])

  useEffect(() => {
    if (activeTab === 'shows') fetchAnalyticsByDate()
  }, [activeTab, fetchAnalyticsByDate])

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
      if (selectedShow?.show_id === showId) {
        fetchShowDetail(showId)
      }
    } catch (err) {
      setMessage(err instanceof AdminApiError ? (err.detail ?? 'Generation failed') : 'Generation failed')
    } finally {
      setGeneratingId(null)
    }
  }

  // RFC 0010 T11. `batch_id` is the key that selects a WHOLE transaction, so a
  // five-card sale is undone by one all-or-nothing call rather than five that
  // can half-succeed. The errors are deliberately re-thrown: `TransactionGroups`
  // keeps its dialog open with the message, and the row unchanged.
  const voidPath = (target: VoidTarget, action: 'void' | 'restore') =>
    target.scope === 'batch'
      ? `/transactions/batch/${target.id}/${action}`
      : `/transactions/${target.id}/${action}`

  const refetchDay = async () => {
    if (selectedDate) await fetchDailyData(selectedDate)
  }

  const handleVoid = async (target: VoidTarget, reason: string) => {
    await api.post(voidPath(target, 'void'), { reason })
    // The day's metrics move with the void — refetching both together is what
    // keeps the tiles and the archive from disagreeing on screen.
    await refetchDay()
  }

  const handleRestore = async (target: VoidTarget) => {
    await api.post(voidPath(target, 'restore'))
    await refetchDay()
  }

  const openShowDetail = (show: Show) => {
    setSelectedShow(show)
    setShowViewMode('detail')
    fetchShowDetail(show.show_id)
  }

  const backToList = () => {
    setShowViewMode('list')
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
  // Shows aggregate metrics
  // ---------------------------------------------------------------------------

  // Read-only dashboard: every figure here is a server-sent decimal string,
  // which is never comma-grouped. Nothing on this page is typed by a human.
  const totalRevenue = analytics.reduce((sum, a) => sum + (parseFloat(a.total_sold) || 0), 0)
  const totalSpend = analytics.reduce((sum, a) => sum + (parseFloat(a.total_bought) || 0), 0)
  const netProfit = analytics.reduce((sum, a) => sum + (parseFloat(a.net_sales) || 0), 0)
  const totalShows = analytics.length

  const handleSort = (key: string) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir('desc')
    }
  }

  const showsWithAnalytics = shows
    .filter((show) => {
      if (!show.date) return false
      return show.date >= startDate && show.date <= endDate
    })
    // Only when no column sort is active — `shows` already arrived in the
    // server's requested order (RFC 0013 T4e) once `sortKey` is set, and
    // re-sorting here would silently override that choice, the same rule
    // Unmatched's `ordered` follows (task 4a above).
    .sort((a, b) => (sortKey ? 0 : (b.date ?? '').localeCompare(a.date ?? '')))
    .map((show): ShowRow => ({
      ...show,
      analytics: analytics.find((a) => a.show_id === show.show_id),
    }))

  const showColumns: Column<ShowRow>[] = [
    {
      key: 'date',
      label: 'Date',
      sortable: true,
      className: 'w-28',
      render: (row) => <span className="text-xs font-mono text-pine-300">{formatISODate(row.date)}</span>,
    },
    {
      key: 'name',
      label: 'Show',
      sortable: true,
      className: 'min-w-[160px]',
      render: (row) => (
        <div className="min-w-0">
          <div className="text-sm text-pine-100 font-medium truncate">{row.name}</div>
          {row.location != null && (
            <div className="text-[10px] text-pine-500 mt-0.5">{String(row.location)}</div>
          )}
          {row.analytics?.stale && (
            <div className="mt-1 inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium border border-amber-500/30 bg-amber-500/10 text-amber-300">
              Out of date — regenerate
            </div>
          )}
        </div>
      ),
    },
    {
      key: '_sold',
      label: 'Sold',
      className: 'text-right',
      render: (row) =>
        row.analytics ? (
          <PriceDisplay value={row.analytics.total_sold} className="text-xs text-mint" />
        ) : (
          <span className="text-[10px] text-pine-600">—</span>
        ),
    },
    {
      key: '_bought',
      label: 'Bought',
      className: 'text-right',
      render: (row) =>
        row.analytics ? (
          <PriceDisplay value={row.analytics.total_bought} className="text-xs text-blue-400" />
        ) : (
          <span className="text-[10px] text-pine-600">—</span>
        ),
    },
    {
      key: '_net',
      label: 'Net',
      className: 'text-right',
      render: (row) =>
        row.analytics ? (
          <SignedAmount value={row.analytics.net_sales} fromValue className="text-xs" />
        ) : (
          <span className="text-[10px] text-pine-600">—</span>
        ),
    },
    {
      key: '_items',
      label: 'Items S/B/T',
      className: 'text-right hidden sm:table-cell',
      render: (row) =>
        row.analytics ? (
          <span className="text-xs font-mono text-pine-300">
            {row.analytics.items_sold_count}/{row.analytics.items_bought_count}/{row.analytics.trades_count}
          </span>
        ) : (
          <span className="text-[10px] text-pine-600 italic">No analytics</span>
        ),
    },
    {
      key: '_actions',
      label: '',
      className: 'text-right w-24',
      render: (row) => (
        <div
          className="flex items-center justify-end gap-2"
          onClick={(e) => e.stopPropagation()}
        >
          <button
            type="button"
            onClick={() => generateAnalytics(row.show_id)}
            disabled={generatingId === row.show_id}
            className={
              row.analytics
                ? 'p-1.5 rounded text-pine-500 hover:text-mint hover:bg-mint/10 disabled:opacity-40 transition-colors'
                : 'inline-flex items-center gap-1 px-2.5 py-1 rounded text-[10px] font-medium bg-mint/10 text-mint border border-mint/20 hover:bg-mint/20 disabled:opacity-40 transition-colors'
            }
            title={row.analytics ? 'Regenerate analytics' : undefined}
          >
            <RefreshCw size={row.analytics ? 13 : 11} className={generatingId === row.show_id ? 'animate-spin' : ''} />
            {!row.analytics && 'Generate'}
          </button>
          <ChevronRight size={14} className="text-pine-600" />
        </div>
      ),
    },
  ]

  // ---------------------------------------------------------------------------
  // Shows detail view (rendered early return)
  // ---------------------------------------------------------------------------

  if (activeTab === 'shows' && showViewMode === 'detail' && selectedShow) {
    return (
      <div className="p-6 lg:p-8">
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
            {formatISODate(selectedShow.date)} {selectedShow.location && `• ${selectedShow.location}`}
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

        {showDetail?.stale && (
          <div
            role="alert"
            className="mb-4 flex items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-300"
          >
            These numbers are out of date — a transaction behind them was voided
            or restored. Regenerate to bring them back in line.
          </div>
        )}

        {loadingDetail ? (
          <div className="vault-panel rounded-xl p-8 text-center text-xs text-pine-400">
            Loading analytics…
          </div>
        ) : showDetail ? (
          <div className="space-y-6">
            {/* Metrics grid */}
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
              <MetricCard label="Total Sold" value={showDetail.total_sold} icon={<ShoppingBag size={14} />} color="text-mint" />
              <MetricCard label="Total Bought" value={showDetail.total_bought} icon={<ShoppingCart size={14} />} color="text-blue-400" />
              <MetricCard label="Net Sales" value={showDetail.net_sales} icon={<DollarSign size={14} />} color="text-amber-400" signed />
              {showDetail.inventory_value_at_start != null && (
                <MetricCard label="Inventory Value at Start" value={String(showDetail.inventory_value_at_start)} icon={<Package size={14} />} color="text-pine-200" />
              )}
              <MetricCard label="Items Sold" value={String(showDetail.items_sold_count)} icon={<ShoppingBag size={14} />} color="text-mint" isCount />
              <MetricCard label="Items Bought" value={String(showDetail.items_bought_count)} icon={<ShoppingCart size={14} />} color="text-blue-400" isCount />
              <MetricCard label="Trades" value={String(showDetail.trades_count)} icon={<ArrowRightLeft size={14} />} color="text-purple-400" isCount />
            </div>

            {/* Performance details */}
            {showDetail.sell_through_rate != null && (
              <div className="vault-panel rounded-xl p-4 border border-pine-700/30">
                <h3 className="text-[11px] font-semibold uppercase tracking-wider text-pine-400 mb-3">
                  Performance Details
                </h3>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                  <div>
                    <div className="text-[10px] text-pine-500 uppercase mb-1">Sell-Through Rate</div>
                    <div className="text-sm font-mono text-pine-100">
                      {(showDetail.sell_through_rate * 100).toFixed(1)}%
                    </div>
                  </div>
                </div>
              </div>
            )}
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
  // Main render with tabs
  // ---------------------------------------------------------------------------

  return (
    <div className="p-6 lg:p-8">
      <header className="mb-6">
        <span className="font-mono text-[11px] uppercase tracking-[0.22em] text-mint/70">
          Analytics
        </span>
        <h1 className="text-xl font-semibold text-pine-100">Analytics Dashboard</h1>
        <p className="text-xs text-pine-400 mt-1">
          Daily metrics and show performance
        </p>
      </header>

      {/* Tab switcher */}
      <div className="flex gap-1 mb-6 border-b border-pine-700/40 pb-px">
        {([['daily', 'Daily'], ['shows', 'Shows']] as [Tab, string][]).map(([key, label]) => (
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

      {/* Message */}
      {message && (
        <div className="flex items-center gap-2 text-xs text-mint bg-mint/5 border border-mint/20 rounded-lg px-3 py-2 mb-4">
          {message}
        </div>
      )}

      {/* ================================================================== */}
      {/* Daily view                                                         */}
      {/* ================================================================== */}
      {activeTab === 'daily' && (
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
          {/* Left: date list */}
          <div className="lg:col-span-1 space-y-3">
            <div>
              <label className="text-[10px] text-pine-500 uppercase tracking-wider block mb-1">
                Pick a date
              </label>
              <input
                type="date"
                value={selectedDate ?? ''}
                onChange={(e) => setSelectedDate(e.target.value || null)}
                className="vault-field px-3 py-1.5 rounded-lg text-xs font-mono w-full"
              />
            </div>

            <div>
              <h3 className="text-[10px] text-pine-500 uppercase tracking-wider mb-2">
                Dates with activity
              </h3>
              {loadingDates ? (
                <div className="text-xs text-pine-400">Loading…</div>
              ) : availableDates.length === 0 ? (
                <div className="text-xs text-pine-500">No activity dates found</div>
              ) : (
                <div className="space-y-1 max-h-[400px] overflow-y-auto vault-scroll">
                  {availableDates.map((d) => (
                    <button
                      key={d}
                      type="button"
                      onClick={() => setSelectedDate(d)}
                      className={`w-full text-left px-3 py-1.5 rounded-lg text-xs font-mono transition-colors ${
                        selectedDate === d
                          ? 'bg-pine-700/70 text-mint'
                          : 'text-pine-300 hover:text-pine-100 hover:bg-pine-800/60'
                      }`}
                    >
                      {formatISODate(d)}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Right: metrics + transaction archive */}
          <div className="lg:col-span-3 space-y-6">
            {!selectedDate ? (
              <div className="vault-panel rounded-xl p-8 text-center text-xs text-pine-500">
                Select a date to view daily analytics
              </div>
            ) : loadingDaily ? (
              <div className="vault-panel rounded-xl p-8 text-center text-xs text-pine-400">
                Loading analytics…
              </div>
            ) : dailyData ? (
              <>
                {/* Daily metrics grid */}
                <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
                  <MetricCard label="Total Sold" value={dailyData.total_sold} icon={<ShoppingBag size={14} />} color="text-mint" />
                  <MetricCard label="Total Bought" value={dailyData.total_bought} icon={<ShoppingCart size={14} />} color="text-blue-400" />
                  <MetricCard label="Net Sales" value={dailyData.net_sales} icon={<DollarSign size={14} />} color="text-amber-400" signed />
                  <MetricCard label="Inventory Value at Start" value={dailyData.inventory_value_at_start} icon={<Package size={14} />} color="text-pine-200" />
                  <MetricCard
                    label="Sell-Through"
                    value={dailyData.sell_through_rate != null ? `${(parseFloat(dailyData.sell_through_rate) * 100).toFixed(1)}%` : '—'}
                    icon={<TrendingUp size={14} />}
                    color="text-amber-400"
                    isCount
                  />
                  <MetricCard label="Items Sold" value={String(dailyData.items_sold_count)} icon={<ShoppingBag size={14} />} color="text-mint" isCount />
                  <MetricCard label="Items Bought" value={String(dailyData.items_bought_count)} icon={<ShoppingCart size={14} />} color="text-blue-400" isCount />
                  <MetricCard label="Trades" value={String(dailyData.trades_count)} icon={<ArrowRightLeft size={14} />} color="text-purple-400" isCount />
                </div>

                {/* Transaction archive */}
                <section>
                  <h2 className="text-xs font-semibold text-pine-200 uppercase tracking-wider mb-3">
                    Transaction Archive
                  </h2>
                  <TransactionGroups
                    transactions={transactions}
                    loading={loadingTxns}
                    emptyMessage="No transactions for this date"
                    onVoid={handleVoid}
                    onRestore={handleRestore}
                  />
                </section>
              </>
            ) : (
              <div className="vault-panel rounded-xl p-8 text-center text-xs text-pine-500">
                No data for the selected date
              </div>
            )}
          </div>
        </div>
      )}

      {/* ================================================================== */}
      {/* Shows view                                                         */}
      {/* ================================================================== */}
      {activeTab === 'shows' && (
        <>
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
              <SignedAmount value={netProfit} fromValue className="text-lg" />
            </div>
            <div className="vault-panel rounded-xl px-4 py-3 border border-pine-700/30">
              <div className="flex items-center gap-1.5 mb-1">
                <BarChart3 size={12} className="text-purple-400" />
                <span className="text-[10px] text-pine-500 uppercase tracking-wider">Shows</span>
              </div>
              <div className="text-lg font-mono text-pine-100">{totalShows}</div>
            </div>
          </div>

          {/* Shows list */}
          <section>
            <h2 className="text-xs font-semibold text-pine-200 uppercase tracking-wider mb-3">
              Shows in Period
            </h2>
            <DataTable
              columns={showColumns}
              data={showsWithAnalytics}
              keyField="show_id"
              loading={loadingShows || loadingAnalytics}
              emptyMessage="No shows found in the selected date range"
              onRowClick={(row) => openShowDetail(row)}
              sortKey={sortKey}
              sortDir={sortDir}
              onSort={handleSort}
            />
          </section>
        </>
      )}
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
  signed,
}: {
  label: string
  value: string
  icon: React.ReactNode
  color: string
  isCount?: boolean
  /** A genuinely signed figure (Net Sales). Its own tone replaces `color`. */
  signed?: boolean
}) {
  return (
    <div className="vault-panel rounded-xl px-3 py-3 border border-pine-700/30">
      <div className="flex items-center gap-1.5 mb-1">
        <span className={color}>{icon}</span>
        <span className="text-[10px] text-pine-500 uppercase tracking-wider">{label}</span>
      </div>
      {isCount ? (
        <div className={`text-base font-mono ${color}`}>{value}</div>
      ) : signed ? (
        <SignedAmount value={value} fromValue className="text-base" />
      ) : (
        <PriceDisplay value={value} className={`text-base ${color}`} />
      )}
    </div>
  )
}
