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
  Lock,
} from 'lucide-react'
import { useAdminApi } from '@/lib/admin-api'

interface DashboardStats {
  totalItems: number
  availableItems: number
  flaggedCount: number
  locations: Record<string, number>
}

export default function AdminDashboardPage() {
  const api = useAdminApi()
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!api.isAuthenticated) return

    async function loadStats() {
      try {
        const [inventory, mispriced, locations] = await Promise.all([
          api.get<{ items: unknown[]; total: number }>('/inventory/search'),
          api.get<{ total_flagged: number }>('/show-prep/mispriced', { threshold: 20 }),
          api.get<{ locations: Record<string, number>; total: number }>('/show-prep/location-summary'),
        ])

        const available = inventory.items.filter(
          (i: any) => i.status === 'available',
        ).length

        setStats({
          totalItems: inventory.total,
          availableItems: available,
          flaggedCount: mispriced.total_flagged,
          locations: locations.locations,
        })
      } catch {
        // silently fail — dashboard is informational
      } finally {
        setLoading(false)
      }
    }

    loadStats()
  }, [api.isAuthenticated]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="p-6 lg:p-8 max-w-6xl">
      {/* Header */}
      <header className="mb-8">
        <span className="font-mono text-[11px] uppercase tracking-[0.22em] text-mint/70">
          Dashboard
        </span>
        <h1 className="mt-1 text-2xl font-semibold text-pine-100">
          Welcome back, Merlin
        </h1>
      </header>

      {/* Quick Actions */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mb-8">
        <Link
          href="/admin/sell"
          className="vault-panel flex items-center gap-3 px-4 py-3.5 rounded-xl hover:border-mint/40 transition-colors group"
        >
          <div className="p-2 rounded-lg bg-mint/10 text-mint group-hover:bg-mint/20 transition-colors">
            <ShoppingCart size={20} />
          </div>
          <div>
            <div className="text-sm font-medium text-pine-100">New Sale</div>
            <div className="text-xs text-pine-400">Start selling</div>
          </div>
        </Link>
        <Link
          href="/admin/buy"
          className="vault-panel flex items-center gap-3 px-4 py-3.5 rounded-xl hover:border-mint/40 transition-colors group"
        >
          <div className="p-2 rounded-lg bg-spriggatito-400/10 text-spriggatito-400 group-hover:bg-spriggatito-400/20 transition-colors">
            <ShoppingBag size={20} />
          </div>
          <div>
            <div className="text-sm font-medium text-pine-100">New Buy</div>
            <div className="text-xs text-pine-400">Purchase cards</div>
          </div>
        </Link>
        <Link
          href="/admin/trade"
          className="vault-panel flex items-center gap-3 px-4 py-3.5 rounded-xl hover:border-mint/40 transition-colors group"
        >
          <div className="p-2 rounded-lg bg-spriggatito-300/10 text-spriggatito-300 group-hover:bg-spriggatito-300/20 transition-colors">
            <ArrowRightLeft size={20} />
          </div>
          <div>
            <div className="text-sm font-medium text-pine-100">New Trade</div>
            <div className="text-xs text-pine-400">Trade calculator</div>
          </div>
        </Link>
        <Link
          href="/admin/vault"
          className="vault-panel flex items-center gap-3 px-4 py-3.5 rounded-xl hover:border-mint/40 transition-colors group"
        >
          <div className="p-2 rounded-lg bg-amber-400/10 text-amber-400 group-hover:bg-amber-400/20 transition-colors">
            <Lock size={20} />
          </div>
          <div>
            <div className="text-sm font-medium text-pine-100">Vault</div>
            <div className="text-xs text-pine-400">On-hold P&amp;L</div>
          </div>
        </Link>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mb-8">
        <StatCard
          icon={<Package size={18} />}
          label="Total Items"
          value={loading ? '—' : String(stats?.totalItems ?? 0)}
        />
        <StatCard
          icon={<TrendingUp size={18} />}
          label="Available"
          value={loading ? '—' : String(stats?.availableItems ?? 0)}
          accent
        />
        <StatCard
          icon={<AlertTriangle size={18} />}
          label="Needs Repricing"
          value={loading ? '—' : String(stats?.flaggedCount ?? 0)}
          warning={!!stats && stats.flaggedCount > 0}
        />
        <StatCard
          icon={<Package size={18} />}
          label="Locations"
          value={loading ? '—' : String(Object.keys(stats?.locations ?? {}).length)}
        />
      </div>

      {/* Location Breakdown */}
      {stats?.locations && Object.keys(stats.locations).length > 0 && (
        <section className="vault-panel rounded-xl p-5">
          <h2 className="text-sm font-medium text-pine-200 mb-3">
            Inventory by Location
          </h2>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2">
            {Object.entries(stats.locations)
              .sort(([, a], [, b]) => b - a)
              .map(([loc, count]) => (
                <div key={loc} className="flex items-center justify-between px-3 py-2 rounded-lg bg-pine-800/50 border border-pine-700/30">
                  <span className="text-xs text-pine-300 capitalize truncate">{loc}</span>
                  <span className="text-xs font-mono text-mint ml-2">{count}</span>
                </div>
              ))}
          </div>
        </section>
      )}
    </div>
  )
}

function StatCard({
  icon,
  label,
  value,
  accent,
  warning,
}: {
  icon: React.ReactNode
  label: string
  value: string
  accent?: boolean
  warning?: boolean
}) {
  return (
    <div className="vault-panel rounded-xl px-4 py-3.5">
      <div className="flex items-center gap-2 mb-1.5">
        <span className="text-pine-400">{icon}</span>
        <span className="text-xs text-pine-400">{label}</span>
      </div>
      <div
        className={`text-xl font-semibold font-mono ${
          warning ? 'text-amber-400' : accent ? 'text-mint' : 'text-pine-100'
        }`}
      >
        {value}
      </div>
    </div>
  )
}
