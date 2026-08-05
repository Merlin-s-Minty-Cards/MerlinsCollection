'use client'

import { useCallback, useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import {
  ArrowLeft,
  ExternalLink,
  Clock,
  MapPin,
  Tag,
  Package,
  DollarSign,
  User,
  Layers,
  Pencil,
} from 'lucide-react'
import { useAdminApi } from '@/lib/admin-api'
import { useCardImages } from '@/lib/use-card-images'
import { formatCondition } from '@/lib/constants'
import PriceDisplay from '@/components/admin/shared/PriceDisplay'
import PriceChart from '@/components/admin/shared/PriceChart'
import StatusBadge from '@/components/admin/shared/StatusBadge'
import CardImage from '@/components/admin/shared/CardImage'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface InventoryItem {
  item_id: string
  card_id?: string
  display_name?: string
  product_name?: string
  name?: string
  set_name?: string
  card_number?: string
  artist?: string
  condition?: string
  condition_modifier?: string | null
  cost_basis?: string | null
  current_market_value?: string | null
  sticker_price?: string | null
  location?: string
  status?: string
  kind?: string
  finish?: string
  language?: string
  acquired_at?: string
  notes?: string
  company?: string
  grade?: string
  cosigner_id?: string | null
  consignment_split?: number | null
  tcg_url?: string | null
  [key: string]: unknown
}

interface TimelineEvent {
  txn_id?: string | null
  type: string
  date: string
  amount?: string | null
  payment_method?: string | null
  counterparty?: string | null
  changed_fields?: Record<string, { old: string | null; new: string | null }> | null
  [key: string]: unknown
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function buildTcgPlayerUrl(name: string): string {
  const query = encodeURIComponent(name)
  return `https://www.tcgplayer.com/search/pokemon/product?q=${query}&view=grid`
}

function buildEbayUrl(name: string): string {
  const query = encodeURIComponent(name)
  return `https://www.ebay.com/sch/i.html?_nkw=${query}&_sacat=0`
}

function formatDate(dateStr: string | undefined | null): string {
  if (!dateStr) return '—'
  try {
    const d = new Date(dateStr)
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
  } catch {
    return dateStr
  }
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export default function AdminCardDetailPage() {
  const params = useParams()
  const router = useRouter()
  const api = useAdminApi()

  const itemId = params.id as string

  // Data
  const [item, setItem] = useState<InventoryItem | null>(null)
  const [timeline, setTimeline] = useState<TimelineEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [loadingTimeline, setLoadingTimeline] = useState(false)

  // Resolve image for this card
  const cardIds = item?.card_id ? [item.card_id] : []
  const { getImageUrl } = useCardImages(cardIds)
  const imageUrl = item?.card_id ? getImageUrl(item.card_id) : null

  // ---------------------------------------------------------------------------
  // Data fetching
  // ---------------------------------------------------------------------------

  const fetchItem = useCallback(async () => {
    if (!api.isAuthenticated || !itemId) return
    setLoading(true)
    try {
      const res = await api.get<InventoryItem>(`/inventory/${itemId}`)
      setItem(res)
    } catch {
      setItem(null)
    } finally {
      setLoading(false)
    }
  }, [api, itemId])

  const fetchTimeline = useCallback(async () => {
    if (!api.isAuthenticated || !itemId) return
    setLoadingTimeline(true)
    try {
      const res = await api.get<{ events: TimelineEvent[] } | TimelineEvent[]>(
        `/inventory/${itemId}/timeline`
      )
      const events = Array.isArray(res) ? res : res.events ?? []
      setTimeline(events)
    } catch {
      setTimeline([])
    } finally {
      setLoadingTimeline(false)
    }
  }, [api, itemId])

  useEffect(() => {
    fetchItem()
    fetchTimeline()
  }, [fetchItem, fetchTimeline])

  // ---------------------------------------------------------------------------
  // Derived
  // ---------------------------------------------------------------------------

  const cardName = item?.display_name || item?.product_name || item?.name || '(unnamed)'
  const conditionDisplay = item?.condition
    ? formatCondition(item.condition, item.condition_modifier)
    : null
  const hasStoredTcgLink =
    typeof item?.tcg_url === 'string' && item.tcg_url.startsWith('http')

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  if (loading) {
    return (
      <div className="p-6 lg:p-8 max-w-5xl">
        <div className="text-xs text-pine-400">Loading…</div>
      </div>
    )
  }

  if (!item) {
    return (
      <div className="p-6 lg:p-8 max-w-5xl">
        <button
          type="button"
          onClick={() => router.back()}
          className="flex items-center gap-1 text-xs text-pine-400 hover:text-pine-200 transition-colors mb-4"
        >
          <ArrowLeft size={14} />
          Back
        </button>
        <div className="vault-panel rounded-xl p-8 text-center text-xs text-pine-500">
          Item not found
        </div>
      </div>
    )
  }

  return (
    <div className="p-6 lg:p-8 max-w-5xl">
      {/* Back button */}
      <button
        type="button"
        onClick={() => router.back()}
        className="flex items-center gap-1 text-xs text-pine-400 hover:text-pine-200 transition-colors mb-4"
      >
        <ArrowLeft size={14} />
        Back
      </button>

      {/* Header with large image */}
      <div className="grid grid-cols-1 md:grid-cols-[240px_1fr] gap-6 mb-6">
        {/* Large card image */}
        <div className="flex justify-center md:justify-start">
          {imageUrl ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={imageUrl}
              alt={cardName}
              className="w-56 h-80 rounded-xl object-cover border border-pine-700/40 shadow-lg"
              loading="eager"
            />
          ) : (
            <CardImage imageUrl={null} alt={cardName} size="lg" className="!w-56 !h-80 rounded-xl" />
          )}
        </div>

        {/* Card info header */}
        <div className="space-y-4">
          <div>
            <span className="font-mono text-[11px] uppercase tracking-[0.22em] text-mint/70">
              Card Detail
            </span>
            <h1 className="text-xl font-semibold text-pine-100 mt-1">{cardName}</h1>
            <div className="flex items-center gap-2 mt-1 flex-wrap">
              {item.set_name && (
                <span className="text-xs text-pine-400">{item.set_name}</span>
              )}
              {item.card_number && (
                <span className="text-xs text-pine-500 font-mono">#{item.card_number}</span>
              )}
              {item.status && <StatusBadge status={item.status} />}
            </div>
          </div>

          {/* Links section */}
          <div className="flex items-center gap-3 flex-wrap">
            {hasStoredTcgLink && (
              <a
                href={item.tcg_url!}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium text-emerald-400 bg-emerald-400/10 border border-emerald-400/20 hover:bg-emerald-400/20 transition-colors"
              >
                <ExternalLink size={12} />
                TCGplayer (stored)
              </a>
            )}
            <a
              href={buildTcgPlayerUrl(cardName)}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium text-blue-400 bg-blue-400/10 border border-blue-400/20 hover:bg-blue-400/20 transition-colors"
            >
              <ExternalLink size={12} />
              {hasStoredTcgLink ? 'Search TCGplayer' : 'TCGplayer'}
            </a>
            <a
              href={buildEbayUrl(cardName)}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium text-purple-400 bg-purple-400/10 border border-purple-400/20 hover:bg-purple-400/20 transition-colors"
            >
              <ExternalLink size={12} />
              eBay
            </a>
          </div>

          {/* Key metrics */}
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            <InfoField icon={<DollarSign size={12} />} label="Cost Basis">
              <PriceDisplay value={item.cost_basis} className="text-sm text-pine-100" />
            </InfoField>
            <InfoField icon={<Tag size={12} />} label="Market Value">
              <PriceDisplay value={item.current_market_value} className="text-sm text-mint" />
            </InfoField>
            <InfoField icon={<Tag size={12} />} label="Sticker Price">
              <PriceDisplay value={item.sticker_price} className="text-sm text-amber-400" />
            </InfoField>
            <InfoField icon={<Layers size={12} />} label="Condition">
              <span className="text-sm text-pine-100 font-mono">{conditionDisplay || '—'}</span>
            </InfoField>
            <InfoField icon={<MapPin size={12} />} label="Location">
              <span className="text-sm text-pine-100 capitalize">{item.location || '—'}</span>
            </InfoField>
            <InfoField icon={<Clock size={12} />} label="Acquired">
              <span className="text-sm text-pine-100">{formatDate(item.acquired_at)}</span>
            </InfoField>
          </div>
        </div>
      </div>

      {/* Price History */}
      <section className="vault-panel rounded-xl p-4 border border-pine-700/30 mb-6">
        <h2 className="text-[11px] font-semibold uppercase tracking-wider text-pine-400 mb-3">
          Price History
        </h2>
        <PriceChart
          itemId={itemId}
          costBasis={item.cost_basis ?? undefined}
          acquiredAt={item.acquired_at ?? undefined}
        />
      </section>

      {/* Detailed fields */}
      <section className="vault-panel rounded-xl p-4 border border-pine-700/30 mb-6">
        <h2 className="text-[11px] font-semibold uppercase tracking-wider text-pine-400 mb-3">
          All Details
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          <DetailRow label="Item ID" value={item.item_id} mono />
          <DetailRow label="Card ID" value={item.card_id} mono />
          <DetailRow label="Kind" value={item.kind} />
          <DetailRow label="Set" value={item.set_name} />
          <DetailRow label="Card Number" value={item.card_number} />
          <DetailRow label="Artist" value={item.artist} />
          <DetailRow label="Condition" value={conditionDisplay} />
          <DetailRow label="Finish" value={item.finish} />
          <DetailRow label="Language" value={item.language} />
          <DetailRow label="Location" value={item.location} />
          <DetailRow label="Status" value={item.status} />
          {item.company && (
            <DetailRow label="Grading Company" value={item.company} />
          )}
          {item.grade && (
            <DetailRow label="Grade" value={item.grade} />
          )}
          {item.cosigner_id && (
            <DetailRow label="Consigner" value={item.cosigner_id} mono />
          )}
          {item.consignment_split != null && (
            <DetailRow label="Consignment Split" value={`${item.consignment_split}%`} />
          )}
          <DetailRow label="Notes" value={item.notes} />
        </div>
      </section>

      {/* Timeline */}
      <section className="vault-panel rounded-xl p-4 border border-pine-700/30">
        <h2 className="text-[11px] font-semibold uppercase tracking-wider text-pine-400 mb-3">
          Timeline ({timeline.length} event{timeline.length !== 1 ? 's' : ''})
        </h2>
        {loadingTimeline ? (
          <div className="text-xs text-pine-400 py-4 text-center">Loading timeline…</div>
        ) : timeline.length === 0 ? (
          <div className="text-xs text-pine-500 py-4 text-center">No timeline events</div>
        ) : (
          <div className="space-y-2">
            {timeline.map((event, idx) => (
              <div
                key={event.txn_id || idx}
                className="flex items-start gap-3 px-3 py-2 rounded-lg bg-pine-800/30 border border-pine-700/20"
              >
                <TimelineIcon type={event.type} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-pine-200 font-medium capitalize">
                      {event.type.replace(/_/g, ' ')}
                    </span>
                    {event.amount && (
                      <PriceDisplay value={event.amount} className="text-xs text-mint" />
                    )}
                  </div>
                  <div className="flex items-center gap-2 mt-0.5 text-[10px] text-pine-500">
                    <span>{formatDate(event.date)}</span>
                    {event.payment_method && <span>• {event.payment_method}</span>}
                    {event.counterparty && <span>• {event.counterparty}</span>}
                  </div>
                  {event.changed_fields && (
                    <div className="mt-1 space-y-0.5">
                      {Object.entries(event.changed_fields).map(([field, diff]) => (
                        <div key={field} className="text-[10px] text-pine-400 font-mono">
                          {field}: {diff.old ?? '—'} → {diff.new ?? '—'}
                        </div>
                      ))}
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
// Sub-components
// ---------------------------------------------------------------------------

function InfoField({
  icon,
  label,
  children,
}: {
  icon: React.ReactNode
  label: string
  children: React.ReactNode
}) {
  return (
    <div className="vault-panel rounded-lg px-3 py-2 border border-pine-700/20">
      <div className="flex items-center gap-1.5 mb-1">
        <span className="text-pine-500">{icon}</span>
        <span className="text-[10px] text-pine-500 uppercase tracking-wider">{label}</span>
      </div>
      {children}
    </div>
  )
}

function DetailRow({
  label,
  value,
  mono,
}: {
  label: string
  value?: string | null
  mono?: boolean
}) {
  return (
    <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-pine-800/30 border border-pine-700/20">
      <span className="text-[10px] text-pine-500 uppercase tracking-wider w-28 flex-shrink-0">
        {label}
      </span>
      <span className={`text-xs text-pine-200 truncate flex-1 ${mono ? 'font-mono' : ''}`}>
        {value || '—'}
      </span>
    </div>
  )
}

function TimelineIcon({ type }: { type: string }) {
  const iconClass = 'text-pine-400'
  switch (type) {
    case 'purchase':
    case 'buy':
      return <Package size={13} className="text-blue-400 mt-0.5" />
    case 'sale':
    case 'sell':
      return <DollarSign size={13} className="text-mint mt-0.5" />
    case 'trade':
      return <Layers size={13} className="text-purple-400 mt-0.5" />
    case 'consignment':
      return <User size={13} className="text-amber-400 mt-0.5" />
    case 'edit':
      return <Pencil size={13} className="text-amber-400 mt-0.5" />
    default:
      return <Clock size={13} className={`${iconClass} mt-0.5`} />
  }
}
