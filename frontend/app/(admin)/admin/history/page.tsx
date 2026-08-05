'use client'

import { useCallback, useState } from 'react'
import { useRouter } from 'next/navigation'
import {
  Clock,
  GitBranch,
  Search,
  ArrowRight,
  ShoppingBag,
  ShoppingCart,
  ArrowRightLeft,
  DollarSign,
  ExternalLink,
  AlertTriangle,
  Pencil,
} from 'lucide-react'
import { useAdminApi, AdminApiError } from '@/lib/admin-api'
import SearchInput from '@/components/admin/shared/SearchInput'
import PriceDisplay from '@/components/admin/shared/PriceDisplay'
import StatusBadge from '@/components/admin/shared/StatusBadge'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TimelineEvent {
  txn_id?: string | null
  type: string
  date: string
  amount?: string | null
  payment_method?: string | null
  trade_id?: string | null
  counterpart_item_id?: string | null
  show_id?: string | null
  changed_fields?: Record<string, { old: string | null; new: string | null }> | null
}

interface LineageNode {
  item_id: string
  name: string
  acquired_cost: string
  status: string
  disposed_via?: string | null
  disposed_value?: string | null
  step_profit?: string | null
  cumulative_profit?: string
}

interface InventorySearchResult {
  item_id: string
  product_name?: string
  display_name?: string
  name?: string
  card_id?: string
  cost_basis?: string
  status?: string
  set_name?: string
  [key: string]: unknown
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export default function AdminHistoryPage() {
  const api = useAdminApi()
  const router = useRouter()

  // Search state
  const [searchQuery, setSearchQuery] = useState('')
  const [minPrice, setMinPrice] = useState('')
  const [maxPrice, setMaxPrice] = useState('')
  const [minProfit, setMinProfit] = useState('')
  const [maxProfit, setMaxProfit] = useState('')
  const [searchResults, setSearchResults] = useState<InventorySearchResult[]>([])
  const [searching, setSearching] = useState(false)

  // Selected item
  const [selectedItem, setSelectedItem] = useState<InventorySearchResult | null>(null)

  // Timeline and lineage
  const [timeline, setTimeline] = useState<TimelineEvent[]>([])
  const [lineage, setLineage] = useState<LineageNode[]>([])
  const [chainComplete, setChainComplete] = useState(false)
  const [loadingTimeline, setLoadingTimeline] = useState(false)
  const [loadingLineage, setLoadingLineage] = useState(false)

  // Active tab
  const [activeTab, setActiveTab] = useState<'timeline' | 'lineage'>('timeline')

  // ---------------------------------------------------------------------------
  // Search
  // ---------------------------------------------------------------------------

  const handleSearch = useCallback(
    async (query: string) => {
      setSearchQuery(query)
      if (!query.trim() || !api.isAuthenticated) {
        setSearchResults([])
        return
      }
      setSearching(true)
      try {
        const params: Record<string, string> = { name: query.trim() }
        if (minPrice) params.min_price = minPrice
        if (maxPrice) params.max_price = maxPrice
        if (minProfit) params.min_profit = minProfit
        if (maxProfit) params.max_profit = maxProfit
        const res = await api.get<{ items: InventorySearchResult[]; total: number }>(
          '/inventory/search',
          params,
        )
        setSearchResults(res.items?.slice(0, 20) ?? [])
      } catch {
        setSearchResults([])
      } finally {
        setSearching(false)
      }
    },
    [api, minPrice, maxPrice, minProfit, maxProfit],
  )

  // ---------------------------------------------------------------------------
  // Fetch timeline + lineage for selected item
  // ---------------------------------------------------------------------------

  const selectItem = useCallback(
    async (item: InventorySearchResult) => {
      setSelectedItem(item)
      setSearchResults([])
      setSearchQuery('')

      // Fetch timeline
      setLoadingTimeline(true)
      try {
        const res = await api.get<{ item_id: string; events: TimelineEvent[] }>(
          `/inventory/${item.item_id}/timeline`,
        )
        setTimeline(res.events ?? [])
      } catch {
        setTimeline([])
      } finally {
        setLoadingTimeline(false)
      }

      // Fetch lineage
      setLoadingLineage(true)
      try {
        const res = await api.get<{
          lineage_id: string
          chain: LineageNode[]
          chain_complete: boolean
        }>(`/inventory/${item.item_id}/lineage`)
        setLineage(res.chain ?? [])
        setChainComplete(res.chain_complete ?? false)
      } catch {
        setLineage([])
        setChainComplete(false)
      } finally {
        setLoadingLineage(false)
      }
    },
    [api],
  )

  // ---------------------------------------------------------------------------
  // Render helpers
  // ---------------------------------------------------------------------------

  const getEventIcon = (type: string) => {
    switch (type) {
      case 'purchase':
      case 'buy':
        return <ShoppingBag size={14} className="text-spriggatito-400" />
      case 'sale':
      case 'sell':
        return <ShoppingCart size={14} className="text-mint" />
      case 'trade_in':
      case 'trade_out':
      case 'trade':
        return <ArrowRightLeft size={14} className="text-blue-400" />
      case 'edit':
        return <Pencil size={14} className="text-amber-400" />
      default:
        return <Clock size={14} className="text-pine-400" />
    }
  }

  const getEventLabel = (type: string) => {
    switch (type) {
      case 'purchase':
      case 'buy':
        return 'Purchased'
      case 'sale':
      case 'sell':
        return 'Sold'
      case 'trade_in':
        return 'Traded In'
      case 'trade_out':
        return 'Traded Out'
      case 'trade':
        return 'Trade'
      case 'edit':
        return 'Edited'
      default:
        return type.replace(/_/g, ' ')
    }
  }

  const getDisposedLabel = (via: string) => {
    switch (via) {
      case 'sale':
      case 'sell':
        return 'Sold'
      case 'trade_out':
        return 'Traded Out'
      default:
        return via.replace(/_/g, ' ')
    }
  }

  /** Format step_profit as +$x.xx / -$x.xx with color and cost_basis guard. */
  const renderStepProfit = (node: LineageNode) => {
    if (node.step_profit == null) return null
    const profit = parseFloat(node.step_profit)
    const isPositive = profit >= 0
    const costBasisZero = node.acquired_cost === '0' || node.acquired_cost === '0.00'

    return (
      <span className="inline-flex items-center gap-1">
        <span className={isPositive ? 'text-mint' : 'text-red-400'}>
          {isPositive ? '+' : '-'}${Math.abs(profit).toFixed(2)}
        </span>
        {costBasisZero && (
          <span title="Profit may be overstated — cost basis is $0 (consigned)">
            <AlertTriangle size={11} className="text-amber-400" />
          </span>
        )}
      </span>
    )
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="p-6 lg:p-8 max-w-5xl">
      <header className="mb-6">
        <span className="font-mono text-[11px] uppercase tracking-[0.22em] text-mint/70">
          Admin
        </span>
        <h1 className="text-xl font-semibold text-pine-100">Transaction History</h1>
        <p className="text-xs text-pine-400 mt-1">
          Search for an inventory item to view its full transaction timeline and trade lineage.
        </p>
      </header>

      {/* Search bar with price filters */}
      <div className="relative mb-6">
        <div className="flex items-end gap-3">
          <SearchInput
            value={searchQuery}
            onChange={handleSearch}
            placeholder="Search by card name…"
            className="max-w-lg flex-1"
          />
          <div className="flex items-center gap-2">
            <div>
              <label className="text-[10px] text-pine-400 block mb-1">Min $</label>
              <input
                type="number"
                min="0"
                step="0.01"
                value={minPrice}
                onChange={(e) => setMinPrice(e.target.value)}
                placeholder="0.00"
                className="vault-field w-24 px-2.5 py-2 rounded-lg text-sm"
              />
            </div>
            <div>
              <label className="text-[10px] text-pine-400 block mb-1">Max $</label>
              <input
                type="number"
                min="0"
                step="0.01"
                value={maxPrice}
                onChange={(e) => setMaxPrice(e.target.value)}
                placeholder="0.00"
                className="vault-field w-24 px-2.5 py-2 rounded-lg text-sm"
              />
            </div>
            <div>
              <label className="text-[10px] text-pine-400 block mb-1">Min Profit</label>
              <input
                type="number"
                step="0.01"
                value={minProfit}
                onChange={(e) => setMinProfit(e.target.value)}
                placeholder="0.00"
                className="vault-field w-24 px-2.5 py-2 rounded-lg text-sm"
              />
            </div>
            <div>
              <label className="text-[10px] text-pine-400 block mb-1">Max Profit</label>
              <input
                type="number"
                step="0.01"
                value={maxProfit}
                onChange={(e) => setMaxProfit(e.target.value)}
                placeholder="0.00"
                className="vault-field w-24 px-2.5 py-2 rounded-lg text-sm"
              />
            </div>
          </div>
        </div>

        {/* Search results dropdown */}
        {searchResults.length > 0 && (
          <div className="absolute top-full left-0 mt-1 w-full max-w-lg vault-panel rounded-xl border border-pine-700/40 shadow-xl z-30 max-h-64 overflow-y-auto vault-scroll">
            {searchResults.map((item) => (
              <button
                key={item.item_id}
                type="button"
                onClick={() => selectItem(item)}
                className="w-full text-left px-4 py-2.5 hover:bg-pine-800/50 transition-colors flex items-center justify-between border-b border-pine-700/20 last:border-0"
              >
                <div>
                  <span className="text-sm text-pine-100 font-medium">
                    {item.display_name || item.product_name || item.name || '(unnamed)'}
                  </span>
                  {item.set_name && (
                    <span className="text-[10px] text-pine-400 ml-2">{item.set_name}</span>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  {item.status && <StatusBadge status={item.status} />}
                  {item.cost_basis && (
                    <PriceDisplay value={item.cost_basis} className="text-xs" />
                  )}
                </div>
              </button>
            ))}
          </div>
        )}

        {searching && (
          <div className="absolute top-full left-0 mt-1 w-full max-w-lg vault-panel rounded-xl p-4 z-30">
            <p className="text-xs text-pine-400">Searching…</p>
          </div>
        )}
      </div>

      {/* Selected item display */}
      {selectedItem && (
        <div className="space-y-6">
          {/* Item header */}
          <div className="vault-panel rounded-xl p-4 flex items-center justify-between">
            <div>
              <h2 className="text-sm font-semibold text-pine-100">
                {selectedItem.display_name ||
                  selectedItem.product_name ||
                  selectedItem.name ||
                  selectedItem.item_id}
              </h2>
              <div className="flex items-center gap-3 mt-1">
                {selectedItem.set_name && (
                  <span className="text-[10px] text-pine-400">{selectedItem.set_name}</span>
                )}
                <span className="text-[10px] text-pine-500 font-mono">
                  {selectedItem.item_id}
                </span>
              </div>
            </div>
            <div className="flex items-center gap-3">
              {selectedItem.cost_basis && (
                <PriceDisplay
                  value={selectedItem.cost_basis}
                  className="text-sm font-semibold"
                />
              )}
              {selectedItem.status && <StatusBadge status={selectedItem.status} />}
            </div>
          </div>

          {/* Tab switcher */}
          <div className="flex border-b border-pine-700/40">
            <button
              type="button"
              onClick={() => setActiveTab('timeline')}
              className={`px-4 py-2 text-xs font-medium transition-colors border-b-2 ${
                activeTab === 'timeline'
                  ? 'border-mint text-mint'
                  : 'border-transparent text-pine-400 hover:text-pine-200'
              }`}
            >
              <span className="inline-flex items-center gap-1.5">
                <Clock size={13} />
                Timeline ({timeline.length})
              </span>
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('lineage')}
              className={`px-4 py-2 text-xs font-medium transition-colors border-b-2 ${
                activeTab === 'lineage'
                  ? 'border-mint text-mint'
                  : 'border-transparent text-pine-400 hover:text-pine-200'
              }`}
            >
              <span className="inline-flex items-center gap-1.5">
                <GitBranch size={13} />
                Trade Lineage ({lineage.length})
              </span>
            </button>
          </div>

          {/* Timeline view */}
          {activeTab === 'timeline' && (
            <div className="space-y-0">
              {loadingTimeline ? (
                <p className="text-xs text-pine-400 py-4">Loading timeline…</p>
              ) : timeline.length === 0 ? (
                <div className="vault-panel rounded-xl p-6 text-center">
                  <Clock size={24} className="text-pine-600 mx-auto mb-2" />
                  <p className="text-xs text-pine-400">
                    No transaction events recorded for this item.
                  </p>
                </div>
              ) : (
                <div className="relative pl-6">
                  {/* Vertical line */}
                  <div className="absolute left-[11px] top-2 bottom-2 w-px bg-pine-700/50" />

                  {timeline.map((event, idx) => (
                    <div key={event.txn_id || idx} className="relative pb-4 last:pb-0">
                      {/* Dot */}
                      <div className="absolute left-[-16px] top-1 w-[9px] h-[9px] rounded-full bg-pine-800 border-2 border-mint/60" />

                      {/* Event card */}
                      <div className="vault-panel rounded-lg px-4 py-3 ml-2">
                        <div className="flex items-center justify-between mb-1">
                          <div className="flex items-center gap-2">
                            {getEventIcon(event.type)}
                            <span className="text-xs font-medium text-pine-100">
                              {getEventLabel(event.type)}
                            </span>
                          </div>
                          <span className="text-[10px] text-pine-500 font-mono">
                            {event.date || '—'}
                          </span>
                        </div>
                        <div className="flex items-center gap-4 text-[11px] text-pine-300 mt-1 flex-wrap">
                          {event.amount && (
                            <span className="flex items-center gap-1">
                              <DollarSign size={11} />
                              <PriceDisplay value={event.amount} className="text-[11px]" />
                            </span>
                          )}
                          {event.payment_method && (
                            <span className="capitalize">{event.payment_method}</span>
                          )}
                          {event.trade_id && (
                            <span className="font-mono text-pine-500">
                              Trade: {event.trade_id.slice(0, 8)}…
                            </span>
                          )}
                          {event.counterpart_item_id && (
                            <button
                              type="button"
                              onClick={() =>
                                selectItem({ item_id: event.counterpart_item_id! })
                              }
                              className="font-mono text-blue-400 hover:text-blue-300 underline underline-offset-2 transition-colors"
                            >
                              Counterpart: {event.counterpart_item_id.slice(0, 8)}…
                            </button>
                          )}
                          {event.show_id && (
                            <span className="font-mono text-pine-500">
                              Show: {event.show_id.slice(0, 8)}…
                            </span>
                          )}
                        </div>
                        {event.changed_fields && (
                          <div className="mt-1.5 space-y-0.5">
                            {Object.entries(event.changed_fields).map(([field, diff]) => (
                              <div key={field} className="text-[10px] text-pine-400 font-mono">
                                {field}: <span className="text-pine-500">{diff.old ?? '—'}</span>
                                {' → '}
                                <span className="text-pine-200">{diff.new ?? '—'}</span>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Lineage view */}
          {activeTab === 'lineage' && (
            <div>
              {loadingLineage ? (
                <p className="text-xs text-pine-400 py-4">Loading lineage…</p>
              ) : lineage.length === 0 ? (
                <div className="vault-panel rounded-xl p-6 text-center">
                  <GitBranch size={24} className="text-pine-600 mx-auto mb-2" />
                  <p className="text-xs text-pine-400">No trade chain found for this item.</p>
                </div>
              ) : (
                <div className="flex items-start gap-0 overflow-x-auto vault-scroll pb-4">
                  {lineage.map((node, idx) => {
                    const isSelected = node.item_id === selectedItem.item_id
                    return (
                      <div key={node.item_id} className="flex items-center">
                        {/* Node */}
                        <div
                          className={`vault-panel rounded-xl min-w-[180px] relative ${
                            isSelected ? 'border-mint/50 bg-mint/5' : ''
                          }`}
                        >
                          {/* ExternalLink icon — opens card detail page */}
                          <button
                            type="button"
                            onClick={() =>
                              router.push('/admin/card/' + node.item_id)
                            }
                            className="absolute top-3 right-3 text-pine-500 hover:text-mint transition-colors z-10"
                            title="Open card details"
                          >
                            <ExternalLink size={11} />
                          </button>

                          {/* Clickable node — selects item in this page */}
                          <button
                            type="button"
                            onClick={() =>
                              selectItem({
                                item_id: node.item_id,
                                name: node.name,
                              })
                            }
                            className="w-full text-left px-4 py-3 hover:bg-pine-800/30 transition-colors rounded-xl"
                            aria-label={`View history for ${node.name || 'unnamed card'}`}
                          >
                            <div className="text-xs font-medium text-pine-100 mb-1 truncate pr-5">
                              {node.name || '(unnamed)'}
                            </div>
                            <div className="flex items-center gap-2">
                              <PriceDisplay
                                value={node.acquired_cost}
                                className="text-[11px]"
                              />
                              <StatusBadge status={node.status} />
                            </div>
                            {/* Disposal info + step profit */}
                            {node.disposed_via && (
                              <div className="flex items-center gap-2 mt-1.5 text-[10px]">
                                <span className="text-pine-400">
                                  {getDisposedLabel(node.disposed_via)}
                                </span>
                                {node.disposed_value && (
                                  <span className="text-pine-300">
                                    ${parseFloat(node.disposed_value).toFixed(2)}
                                  </span>
                                )}
                              </div>
                            )}
                            {node.step_profit != null && (
                              <div className="mt-1 text-[11px]">
                                {renderStepProfit(node)}
                              </div>
                            )}
                            <div className="text-[9px] font-mono text-pine-600 mt-1">
                              {node.item_id.slice(0, 12)}…
                            </div>
                            {isSelected && (
                              <div className="text-[9px] text-mint font-medium mt-1">
                                Current Item
                              </div>
                            )}
                          </button>
                        </div>

                        {/* Arrow between nodes */}
                        {idx < lineage.length - 1 && (
                          <ArrowRight
                            size={16}
                            className="text-pine-600 mx-2 flex-shrink-0"
                          />
                        )}
                      </div>
                    )
                  })}
                </div>
              )}

              {/* Profit summary for lineage */}
              {lineage.length > 1 && (
                <div className="vault-panel rounded-xl p-4 mt-4">
                  <h4 className="text-[10px] uppercase tracking-wider text-pine-400 mb-2">
                    Lineage Summary
                  </h4>
                  <div className="grid grid-cols-3 gap-3">
                    <div className="px-3 py-2 rounded-lg bg-pine-800/50 border border-pine-700/30">
                      <div className="text-[10px] text-pine-400">Chain Length</div>
                      <div className="text-sm font-mono text-pine-100">{lineage.length}</div>
                    </div>
                    <div className="px-3 py-2 rounded-lg bg-pine-800/50 border border-pine-700/30">
                      <div className="text-[10px] text-pine-400">Initial Cost</div>
                      <PriceDisplay
                        value={lineage[0]?.acquired_cost}
                        className="text-sm font-mono"
                      />
                    </div>
                    <div className="px-3 py-2 rounded-lg bg-pine-800/50 border border-pine-700/30">
                      <div className="text-[10px] text-pine-400">Chain Profit</div>
                      {(() => {
                        const lastNode = lineage[lineage.length - 1]
                        const cp = lastNode?.cumulative_profit
                        if (cp == null) {
                          return (
                            <span className="text-sm font-mono text-pine-400">—</span>
                          )
                        }
                        const val = parseFloat(cp)
                        return (
                          <span
                            className={`text-sm font-mono ${val >= 0 ? 'text-mint' : 'text-red-400'}`}
                          >
                            {val >= 0 ? '+' : '-'}${Math.abs(val).toFixed(2)}
                          </span>
                        )
                      })()}
                    </div>
                  </div>
                  {/* Chain lifecycle chip */}
                  <div className="mt-3">
                    <span
                      className={`inline-flex items-center px-2.5 py-1 rounded-full text-[10px] font-medium ${
                        chainComplete
                          ? 'bg-mint/10 text-mint border border-mint/20'
                          : 'bg-blue-500/10 text-blue-400 border border-blue-500/20'
                      }`}
                    >
                      {chainComplete
                        ? 'Lifecycle complete (cashed out)'
                        : 'Still in inventory'}
                    </span>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Empty state when nothing selected */}
      {!selectedItem && (
        <div className="vault-panel rounded-xl p-12 text-center mt-6">
          <Search size={36} className="text-pine-600 mx-auto mb-3" />
          <p className="text-sm text-pine-400">
            Search for a card above to view its transaction history and trade lineage.
          </p>
        </div>
      )}
    </div>
  )
}
