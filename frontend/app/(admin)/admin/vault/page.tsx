'use client'

import { useCallback, useEffect, useState } from 'react'
import { Lock, Unlock } from 'lucide-react'
import { useAdminApi, AdminApiError } from '@/lib/admin-api'
import PriceDisplay from '@/components/admin/shared/PriceDisplay'
import SearchInput from '@/components/admin/shared/SearchInput'
import ConfirmDialog from '@/components/admin/shared/ConfirmDialog'

interface VaultItem {
  item_id: string
  name: string
  kind: string
  cost_basis: string
  current_market_value: string | null
  sticker_price: string | null
  location: string | null
  condition: string | null
  dollar_net: string | null
  percent_net: string | null
}

interface VaultSummary {
  total_items: number
  total_cost_basis: string
  total_market_value: string
  total_dollar_gain: string
  total_percent_gain: string | null
}

interface VaultResponse {
  items: VaultItem[]
  summary: VaultSummary
}

export default function AdminVaultPage() {
  const api = useAdminApi()

  const [data, setData] = useState<VaultResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [releaseId, setReleaseId] = useState<string | null>(null)
  const [releasing, setReleasing] = useState(false)

  const fetchVault = useCallback(async () => {
    if (!api.isAuthenticated) return
    setLoading(true)
    try {
      const res = await api.get<VaultResponse>('/vault')
      setData(res)
    } catch {
      setData(null)
    } finally {
      setLoading(false)
    }
  }, [api])

  useEffect(() => {
    fetchVault()
  }, [fetchVault])

  const handleRelease = async () => {
    if (!releaseId) return
    setReleasing(true)
    try {
      await api.post(`/vault/${releaseId}/release`)
      setReleaseId(null)
      fetchVault()
    } catch (err) {
      alert(err instanceof AdminApiError ? err.detail : 'Failed to release item')
    } finally {
      setReleasing(false)
    }
  }

  const filteredItems = data?.items.filter((item) => {
    if (!search) return true
    const q = search.toLowerCase()
    return (
      item.name.toLowerCase().includes(q) ||
      (item.location ?? '').toLowerCase().includes(q)
    )
  }) ?? []

  const summary = data?.summary

  return (
    <div className="p-6 lg:p-8 max-w-6xl">
      {/* Header */}
      <header className="mb-6">
        <span className="font-mono text-[11px] uppercase tracking-[0.22em] text-mint/70">
          Vault
        </span>
        <h1 className="text-xl font-semibold text-pine-100">Merlin&apos;s Vault</h1>
        <p className="text-xs text-pine-400 mt-1">Cards on hold — personal collection &amp; long-term holds</p>
      </header>

      {/* Summary Cards */}
      {summary && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
          <div className="vault-panel rounded-xl p-4">
            <div className="text-[10px] text-pine-400 uppercase tracking-wider mb-1">Items Held</div>
            <div className="text-lg font-mono font-semibold text-pine-100">{summary.total_items}</div>
          </div>
          <div className="vault-panel rounded-xl p-4">
            <div className="text-[10px] text-pine-400 uppercase tracking-wider mb-1">Cost Basis</div>
            <div className="text-lg font-mono font-semibold text-pine-100">
              <PriceDisplay value={summary.total_cost_basis} className="text-lg font-mono font-semibold text-pine-100" />
            </div>
          </div>
          <div className="vault-panel rounded-xl p-4">
            <div className="text-[10px] text-pine-400 uppercase tracking-wider mb-1">Market Value</div>
            <div className="text-lg font-mono font-semibold text-mint">
              <PriceDisplay value={summary.total_market_value} className="text-lg font-mono font-semibold text-mint" />
            </div>
          </div>
          <div className="vault-panel rounded-xl p-4">
            <div className="text-[10px] text-pine-400 uppercase tracking-wider mb-1">Total Gain/Loss</div>
            <div className={`text-lg font-mono font-semibold ${
              parseFloat(summary.total_dollar_gain) >= 0 ? 'text-mint' : 'text-red-400'
            }`}>
              {parseFloat(summary.total_dollar_gain) >= 0 ? '+' : ''}${parseFloat(summary.total_dollar_gain).toFixed(2)}
              {summary.total_percent_gain && (
                <span className="text-xs ml-1">({parseFloat(summary.total_percent_gain) >= 0 ? '+' : ''}{summary.total_percent_gain}%)</span>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Search */}
      <div className="mb-4">
        <SearchInput
          value={search}
          onChange={setSearch}
          placeholder="Filter vault cards…"
        />
      </div>

      {/* Items Table */}
      <div className="vault-panel rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-pine-700/40 flex items-center gap-2">
          <Lock size={16} className="text-mint" />
          <span className="text-sm font-medium text-pine-100">
            Vault Holdings ({filteredItems.length})
          </span>
        </div>

        {loading ? (
          <div className="p-6 text-center text-xs text-pine-500">Loading vault…</div>
        ) : filteredItems.length === 0 ? (
          <div className="p-6 text-center text-xs text-pine-500">
            {search ? 'No matching items' : 'No items in vault'}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-pine-700/30 text-pine-400 text-left">
                  <th className="px-4 py-2 font-medium">Card</th>
                  <th className="px-4 py-2 font-medium">Condition</th>
                  <th className="px-4 py-2 font-medium text-right">Cost</th>
                  <th className="px-4 py-2 font-medium text-right">Market</th>
                  <th className="px-4 py-2 font-medium text-right">Sticker</th>
                  <th className="px-4 py-2 font-medium text-right">$ Net</th>
                  <th className="px-4 py-2 font-medium text-right">% Net</th>
                  <th className="px-4 py-2 font-medium text-center">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-pine-700/20">
                {filteredItems.map((item) => {
                  const dollarNet = item.dollar_net ? parseFloat(item.dollar_net) : null
                  const pctNet = item.percent_net ? parseFloat(item.percent_net) : null
                  const isPositive = dollarNet !== null && dollarNet >= 0
                  return (
                    <tr key={item.item_id} className="hover:bg-pine-800/30 transition-colors">
                      <td className="px-4 py-2.5">
                        <div className="text-pine-100 font-medium truncate max-w-[200px]">{item.name || '(unnamed)'}</div>
                        <div className="text-[10px] text-pine-500">{item.kind} · {item.location ?? '—'}</div>
                      </td>
                      <td className="px-4 py-2.5 text-pine-300">{item.condition ?? '—'}</td>
                      <td className="px-4 py-2.5 text-right">
                        <PriceDisplay value={item.cost_basis} className="text-xs text-pine-300 font-mono" />
                      </td>
                      <td className="px-4 py-2.5 text-right">
                        <PriceDisplay value={item.current_market_value} className="text-xs text-mint font-mono" />
                      </td>
                      <td className="px-4 py-2.5 text-right">
                        {item.sticker_price ? (
                          <PriceDisplay value={item.sticker_price} className="text-xs text-pine-300 font-mono" />
                        ) : (
                          <span className="text-pine-600">—</span>
                        )}
                      </td>
                      <td className="px-4 py-2.5 text-right">
                        {dollarNet !== null ? (
                          <span className={`font-mono ${isPositive ? 'text-mint' : 'text-red-400'}`}>
                            {isPositive ? '+' : ''}${dollarNet.toFixed(2)}
                          </span>
                        ) : (
                          <span className="text-pine-600">—</span>
                        )}
                      </td>
                      <td className="px-4 py-2.5 text-right">
                        {pctNet !== null ? (
                          <span className={`font-mono ${isPositive ? 'text-mint' : 'text-red-400'}`}>
                            {pctNet >= 0 ? '+' : ''}{pctNet.toFixed(1)}%
                          </span>
                        ) : (
                          <span className="text-pine-600">—</span>
                        )}
                      </td>
                      <td className="px-4 py-2.5 text-center">
                        <button
                          type="button"
                          onClick={() => setReleaseId(item.item_id)}
                          className="inline-flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium text-pine-300 border border-pine-700/40 hover:border-mint/30 hover:text-mint transition-colors"
                          title="Release from vault"
                        >
                          <Unlock size={11} />
                          Release
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <ConfirmDialog
        open={!!releaseId}
        title="Release from Vault"
        description="Move this card back to available inventory?"
        confirmLabel="Release"
        loading={releasing}
        onConfirm={handleRelease}
        onCancel={() => setReleaseId(null)}
      />
    </div>
  )
}
