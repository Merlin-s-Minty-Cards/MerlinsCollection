'use client'

import { useCallback, useEffect, useState } from 'react'
import { Lock, Unlock } from 'lucide-react'
import { useAdminApi, AdminApiError } from '@/lib/admin-api'
import { useCardImages } from '@/lib/use-card-images'
import { formatCondition } from '@/lib/constants'
import { sortVaultItems } from '@/lib/vault-sort'
import PriceDisplay from '@/components/admin/shared/PriceDisplay'
import SearchInput from '@/components/admin/shared/SearchInput'
import ConfirmDialog from '@/components/admin/shared/ConfirmDialog'
import CardImage, { TABLE_THUMB_SIZE, TABLE_THUMB_COLUMN } from '@/components/admin/shared/CardImage'
import ImageToggle from '@/components/admin/shared/ImageToggle'
import CardDetailModal from '@/components/admin/shared/CardDetailModal'
import { patchRow } from '@/lib/item-update'
import OwnershipBadge from '@/components/admin/shared/OwnershipBadge'
import DataTable, { Column } from '@/components/admin/shared/DataTable'

interface VaultItem {
  item_id: string
  name: string
  kind: string
  card_id?: string
  cost_basis: string
  current_market_value: string | null
  sticker_price: string | null
  location: string | null
  condition: string | null
  condition_modifier: string | null
  dollar_net: string | null
  percent_net: string | null
  consigned: boolean
  [key: string]: unknown
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
  const [sortKey, setSortKey] = useState<string | null>(null)
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')

  // Image toggle and detail modal
  const [showImages, setShowImages] = useState(false)
  const [detailItem, setDetailItem] = useState<VaultItem | null>(null)
  const cardIds = (data?.items ?? []).map((i) => i.card_id)
  const { getImageUrl } = useCardImages(showImages ? cardIds : [])

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

  const handleSort = (key: string) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir('asc')
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

  // Client-side sort — deliberately, not a RFC 0013 T4c regression. `/vault`
  // (like `/show-prep/mispriced`) returns its FULL on-hold set with no
  // `limit`/pagination, so there is no page-boundary a server sort would
  // need to protect the way Inventory/Prep Queue's `limit` does. `sortVaultItems`
  // (lib/vault-sort.ts) already enforces the same missing-sorts-last-in-both-
  // directions invariant every backend registry does, so converting this to a
  // server round trip would add a new backend sort registry for a bespoke,
  // computed response shape (`dollar_net`/`percent_net`/`consigned`) that is
  // not one of RFC 0013's five named tables, for zero behavioral gain. See
  // CLAUDE.md/RFC 0013 sync-docs notes for this deviation.
  const sortedItems = sortKey ? sortVaultItems(filteredItems, sortKey, sortDir) : filteredItems

  const summary = data?.summary

  const columns: Column<VaultItem>[] = [
    ...(showImages
      ? [
          {
            key: '_image',
            label: '',
            className: TABLE_THUMB_COLUMN,
            render: (item: VaultItem) => (
              <CardImage
                imageUrl={getImageUrl(item.card_id)}
                alt={item.name || 'card'}
                size={TABLE_THUMB_SIZE}
              />
            ),
          },
        ]
      : []),
    {
      key: 'name',
      label: 'Card',
      sortable: true,
      className: 'min-w-[180px]',
      render: (item) => (
        <div>
          <div className="text-pine-100 font-medium truncate max-w-[200px]">{item.name || '(unnamed)'}</div>
          <div className="text-[10px] text-pine-500">{item.kind} · {item.location ?? '—'}</div>
        </div>
      ),
    },
    {
      key: 'condition',
      label: 'Condition',
      sortable: true,
      render: (item) => (
        <span className="text-pine-300">
          {item.condition ? formatCondition(item.condition, item.condition_modifier) : '—'}
        </span>
      ),
    },
    {
      key: 'cost_basis',
      label: 'Price Paid',
      sortable: true,
      className: 'text-right',
      render: (item) => <PriceDisplay value={item.cost_basis} className="text-xs text-pine-300 font-mono" />,
    },
    {
      key: 'current_market_value',
      label: 'Market',
      sortable: true,
      className: 'text-right',
      render: (item) => <PriceDisplay value={item.current_market_value} className="text-xs text-mint font-mono" />,
    },
    {
      key: 'sticker_price',
      label: 'Sticker',
      sortable: true,
      className: 'text-right',
      render: (item) =>
        item.sticker_price ? (
          <PriceDisplay value={item.sticker_price} className="text-xs text-pine-300 font-mono" />
        ) : (
          <span className="text-pine-600">—</span>
        ),
    },
    {
      key: 'dollar_net',
      label: '$ Net',
      sortable: true,
      className: 'text-right',
      render: (item) => {
        const dollarNet = item.dollar_net ? parseFloat(item.dollar_net) : null
        if (dollarNet === null) return <span className="text-pine-600">—</span>
        const isPositive = dollarNet >= 0
        return (
          <span className={`font-mono ${isPositive ? 'text-mint' : 'text-red-400'}`}>
            {isPositive ? '+' : ''}${dollarNet.toFixed(2)}
          </span>
        )
      },
    },
    {
      key: 'percent_net',
      label: '% Net',
      sortable: true,
      className: 'text-right',
      render: (item) => {
        const pctNet = item.percent_net ? parseFloat(item.percent_net) : null
        if (pctNet === null) return <span className="text-pine-600">—</span>
        const isPositive = pctNet >= 0
        return (
          <span className={`font-mono ${isPositive ? 'text-mint' : 'text-red-400'}`}>
            {isPositive ? '+' : ''}{pctNet.toFixed(1)}%
          </span>
        )
      },
    },
    {
      key: 'consigned',
      label: 'Ownership',
      sortable: true,
      render: (item) => <OwnershipBadge consigned={item.consigned} />,
    },
    {
      key: '_action',
      label: 'Action',
      className: 'text-center',
      render: (item) => (
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); setReleaseId(item.item_id) }}
          className="inline-flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium text-pine-300 border border-pine-700/40 hover:border-mint/30 hover:text-mint transition-colors"
          title="Release from vault"
        >
          <Unlock size={11} />
          Release
        </button>
      ),
    },
  ]

  return (
    <div className="p-6 lg:p-8">
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
            <div className="text-[10px] text-pine-400 uppercase tracking-wider mb-1">Price Paid</div>
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

      {/* Search + Image Toggle */}
      <div className="mb-4 flex items-center gap-3">
        <SearchInput
          value={search}
          onChange={setSearch}
          placeholder="Filter vault cards…"
        />
        <ImageToggle showImages={showImages} onToggle={() => setShowImages(!showImages)} label="Images" />
      </div>

      {/* Items Table */}
      <div className="vault-panel rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-pine-700/40 flex items-center gap-2">
          <Lock size={16} className="text-mint" />
          <span className="text-sm font-medium text-pine-100">
            Vault Holdings ({sortedItems.length})
          </span>
        </div>

        <DataTable
          columns={columns}
          data={sortedItems}
          keyField="item_id"
          sortKey={sortKey}
          sortDir={sortDir}
          onSort={handleSort}
          onRowClick={(item) => setDetailItem(item)}
          loading={loading}
          emptyMessage={search ? 'No matching items' : 'No items in vault'}
        />
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

      <CardDetailModal
        item={detailItem as Record<string, unknown> | null}
        onClose={() => setDetailItem(null)}
        // Patch the row, do not refetch (RFC 0010 T5) — this table is sortable
        // and long, and a refetch resets both the scroll and the sort.
        onUpdated={(updated) => {
          if (!updated) { fetchVault(); return }
          setData((cur) => (cur ? { ...cur, items: patchRow(cur.items, updated) } : cur))
        }}
      />
    </div>
  )
}
