'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import {
  Package,
  ShoppingCart,
  ShoppingBag,
  ArrowRightLeft,
  AlertTriangle,
  TrendingUp,
  TrendingDown,
  Lock,
  Tag,
  Stethoscope,
  CheckCircle2,
  Activity,
  Wallet,
} from 'lucide-react'
import { useAdminApi } from '@/lib/admin-api'
import { todayLocal } from '@/lib/dates'
import { summarizeHoldings, type HoldingsSummary, type HoldingItem } from '@/lib/dashboard-stats'

interface TriageCounts { total: number; reasons: Record<string, number> }
interface Coverage { total_items: number; items_with_market_value: number }
interface DailyMetrics { total_sold: string; items_sold_count: number }

interface DashboardStats {
  holdings: HoldingsSummary
  locations: Record<string, number>
  flaggedCount: number
  triageCount: number | null
  prepQueueCount: number | null
  coveragePct: number | null
  today: DailyMetrics | null
}

const money = (n: number) =>
  `$${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

/** Resolves to null instead of throwing, so one dead panel cannot blank the page. */
function soft<T>(p: Promise<T>): Promise<T | null> {
  return p.then((v) => v).catch(() => null)
}

export default function AdminDashboardPage() {
  const api = useAdminApi()
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!api.isAuthenticated) return

    async function loadStats() {
      // Six independent reads. Each is soft-failed on its own so a single
      // broken endpoint costs one panel, not the whole dashboard — the
      // previous version wrapped all of them in one try and rendered nothing
      // when any single call rejected.
      const [inventory, mispriced, locations, triage, prepQueue, coverage, daily] =
        await Promise.all([
          soft(api.get<{ items: HoldingItem[]; total: number }>('/inventory/search')),
          soft(api.get<{ total_flagged: number }>('/show-prep/mispriced', { threshold: 20 })),
          soft(api.get<{ locations: Record<string, number> }>('/show-prep/location-summary')),
          soft(api.get<TriageCounts>('/triage/counts')),
          soft(api.get<{ total: number }>('/inventory/search', {
            status: 'available', missing_sticker: true,
          })),
          soft(api.get<Coverage>('/market/coverage')),
          soft(api.get<DailyMetrics>('/analytics/daily', {
            date: todayLocal(),
          })),
        ])

      setStats({
        holdings: summarizeHoldings(inventory?.items ?? []),
        locations: locations?.locations ?? {},
        flaggedCount: mispriced?.total_flagged ?? 0,
        triageCount: triage?.total ?? null,
        prepQueueCount: prepQueue?.total ?? null,
        coveragePct:
          coverage && coverage.total_items > 0
            ? (coverage.items_with_market_value / coverage.total_items) * 100
            : null,
        today: daily,
      })
      setLoading(false)
    }

    loadStats()
  }, [api.isAuthenticated]) // eslint-disable-line react-hooks/exhaustive-deps

  const h = stats?.holdings
  const dash = '—'

  // An all-clear is only meaningful once the counts have actually arrived.
  const actionCounts = [stats?.triageCount, stats?.prepQueueCount, stats?.flaggedCount]
  const allClear =
    !loading && actionCounts.every((c) => c !== null && c !== undefined && c === 0)

  return (
    <div className="p-6 lg:p-8 max-w-6xl">
      <header className="mb-8">
        <span className="font-mono text-[11px] uppercase tracking-[0.22em] text-mint/70">
          Dashboard
        </span>
        <h1 className="mt-1 text-2xl font-semibold text-pine-100">
          Welcome back, Merlin
        </h1>
      </header>

      {/* Quick Actions */}
      <div
        data-testid="quick-actions"
        className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mb-8"
      >
        <QuickAction href="/admin/sell" label="New Sale" hint="Start selling"
          icon={<ShoppingCart size={20} />} tone="text-mint bg-mint/10 group-hover:bg-mint/20" />
        <QuickAction href="/admin/buy" label="New Buy" hint="Purchase cards"
          icon={<ShoppingBag size={20} />}
          tone="text-spriggatito-400 bg-spriggatito-400/10 group-hover:bg-spriggatito-400/20" />
        <QuickAction href="/admin/trade" label="New Trade" hint="Trade calculator"
          icon={<ArrowRightLeft size={20} />}
          tone="text-spriggatito-300 bg-spriggatito-300/10 group-hover:bg-spriggatito-300/20" />
        <QuickAction href="/admin/vault" label="Vault" hint="On-hold P&amp;L"
          icon={<Lock size={20} />}
          tone="text-amber-400 bg-amber-400/10 group-hover:bg-amber-400/20" />
      </div>

      {/* Needs attention — the only section that changes what the admin does
          next, so it sits above the money. */}
      <section className="mb-8">
        <SectionLabel>Needs attention</SectionLabel>
        {allClear ? (
          <div className="vault-panel rounded-xl px-4 py-3.5 flex items-center gap-2.5">
            <CheckCircle2 size={16} className="text-mint" />
            <span className="text-sm text-pine-200">
              Nothing needs attention — every queue is clear.
            </span>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <ActionCard
              testId="action-triage" href="/admin/triage" label="Triage"
              hint="Data to correct" icon={<Stethoscope size={16} />}
              count={loading ? null : stats?.triageCount ?? null}
            />
            <ActionCard
              testId="action-prep-queue" href="/admin/outgoing" label="Prep Queue"
              hint="Unstickered stock" icon={<Tag size={16} />}
              count={loading ? null : stats?.prepQueueCount ?? null}
            />
            <ActionCard
              testId="action-repricing" href="/admin/show-prep" label="Needs Repricing"
              hint="20%+ off market" icon={<AlertTriangle size={16} />}
              count={loading ? null : stats?.flaggedCount ?? null}
            />
          </div>
        )}
      </section>

      {/* Position */}
      <section className="mb-8">
        <SectionLabel>Position</SectionLabel>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          <StatCard
            testId="stat-on-hand" icon={<Package size={18} />} label="Items on hand"
            value={loading || !h ? dash : String(h.onHandCount)}
            sub={h && h.consignedCount > 0 ? `${h.consignedCount} consigned` : undefined}
          />
          <StatCard
            testId="stat-market" icon={<Wallet size={18} />} label="Market value"
            value={loading || !h ? dash : money(h.marketValue)}
            accent
          />
          <StatCard
            testId="stat-cost" icon={<Wallet size={18} />} label="Cost basis"
            value={loading || !h ? dash : money(h.costBasis)}
            sub="Owned stock only"
          />
          <StatCard
            testId="stat-unrealized"
            icon={h && h.unrealized < 0 ? <TrendingDown size={18} /> : <TrendingUp size={18} />}
            label="Unrealized"
            value={loading || !h ? dash : money(h.unrealized)}
            sub={h?.marginPct == null ? undefined : `${h.marginPct.toFixed(1)}% margin`}
            tone={!h ? undefined : h.unrealized < 0 ? 'warning' : 'good'}
          />
        </div>
      </section>

      {/* Today + data health */}
      <section className="mb-8">
        <SectionLabel>Today</SectionLabel>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <StatCard
            testId="stat-today" icon={<Activity size={18} />} label="Sold today"
            value={loading ? dash : money(parseFloat(stats?.today?.total_sold ?? '0'))}
            sub={
              loading
                ? undefined
                : `${stats?.today?.items_sold_count ?? 0} item${
                    (stats?.today?.items_sold_count ?? 0) === 1 ? '' : 's'
                  }`
            }
            accent
          />
          <StatCard
            testId="stat-coverage" icon={<TrendingUp size={18} />} label="Price coverage"
            value={
              loading || stats?.coveragePct == null
                ? dash
                : `${Math.round(stats.coveragePct)}%`
            }
            sub="Inventory carrying a market price"
            // Thin coverage means the money numbers above are understated, so
            // it is a warning about THIS page, not a neutral statistic.
            tone={
              stats?.coveragePct == null
                ? undefined
                : stats.coveragePct < 50 ? 'warning' : 'good'
            }
          />
        </div>
      </section>

      {/* Location Breakdown */}
      {stats?.locations && Object.keys(stats.locations).length > 0 && (
        <section>
          <SectionLabel>Inventory by location</SectionLabel>
          <div className="vault-panel rounded-xl p-5">
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2">
              {Object.entries(stats.locations)
                .sort(([, a], [, b]) => b - a)
                .map(([loc, count]) => (
                  <div
                    key={loc}
                    className="flex items-center justify-between px-3 py-2 rounded-lg bg-pine-800/50 border border-pine-700/30"
                  >
                    <span className="text-xs text-pine-300 capitalize truncate">{loc}</span>
                    <span className="text-xs font-mono text-mint ml-2">{count}</span>
                  </div>
                ))}
            </div>
          </div>
        </section>
      )}
    </div>
  )
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="font-mono text-[10px] uppercase tracking-[0.18em] text-pine-500 mb-2.5">
      {children}
    </h2>
  )
}

function QuickAction({
  href, label, hint, icon, tone,
}: { href: string; label: string; hint: string; icon: React.ReactNode; tone: string }) {
  return (
    <Link
      href={href}
      className="vault-panel flex items-center gap-3 px-4 py-3.5 rounded-xl hover:border-mint/40 transition-colors group"
    >
      <div className={`p-2 rounded-lg transition-colors ${tone}`}>{icon}</div>
      <div>
        <div className="text-sm font-medium text-pine-100">{label}</div>
        <div className="text-xs text-pine-400">{hint}</div>
      </div>
    </Link>
  )
}

/**
 * A queue with outstanding work. Always a link — a count with nowhere to go
 * tells the admin there is a problem and then makes them find it.
 */
function ActionCard({
  testId, href, label, hint, icon, count,
}: {
  testId: string; href: string; label: string; hint: string
  icon: React.ReactNode; count: number | null
}) {
  const clear = count === 0
  return (
    <Link href={href} className="group">
      <div
        data-testid={testId}
        className={`vault-panel rounded-xl px-4 py-3.5 flex items-center justify-between transition-colors ${
          clear ? 'hover:border-pine-600' : 'border-amber-400/25 hover:border-amber-400/50'
        }`}
      >
        <div className="flex items-center gap-2.5 min-w-0">
          <span className={clear ? 'text-pine-500' : 'text-amber-400'}>{icon}</span>
          <div className="min-w-0">
            <div className="text-sm font-medium text-pine-100 truncate">{label}</div>
            <div className="text-[11px] text-pine-400 truncate">{hint}</div>
          </div>
        </div>
        <span
          className={`text-xl font-semibold font-mono ml-3 ${
            clear ? 'text-pine-500' : 'text-amber-400'
          }`}
        >
          {count === null ? '—' : count}
        </span>
      </div>
    </Link>
  )
}

function StatCard({
  testId, icon, label, value, sub, accent, tone,
}: {
  testId?: string
  icon: React.ReactNode
  label: string
  value: string
  sub?: string
  accent?: boolean
  tone?: 'good' | 'warning'
}) {
  const valueColor =
    tone === 'warning' ? 'text-amber-400'
      : tone === 'good' ? 'text-mint'
      : accent ? 'text-mint'
      : 'text-pine-100'

  return (
    <div data-testid={testId} data-tone={tone} className="vault-panel rounded-xl px-4 py-3.5">
      <div className="flex items-center gap-2 mb-1.5">
        <span className="text-pine-400">{icon}</span>
        <span className="text-xs text-pine-400">{label}</span>
      </div>
      <div className={`text-xl font-semibold font-mono ${valueColor}`}>{value}</div>
      {sub && <div className="text-[10px] text-pine-500 mt-0.5">{sub}</div>}
    </div>
  )
}
