'use client'

import { useEffect, useState } from 'react'
import { usePathname } from 'next/navigation'
import Link from 'next/link'
import {
  LayoutDashboard,
  Package,
  ShoppingCart,
  ShoppingBag,
  ArrowRightLeft,
  ScanLine,
  TrendingUp,
  MapPin,
  MapPinned,
  CalendarDays,
  Lock,
  Stethoscope,
  Tags,
  BarChart3,
  History,
  Users,
  PanelLeftClose,
  PanelLeft,
  LogOut,
} from 'lucide-react'
import { signOut } from 'next-auth/react'
import { useAdminApi } from '@/lib/admin-api'

const navItems = [
  { href: '/admin', label: 'Dashboard', icon: LayoutDashboard },
  { href: '/admin/inventory', label: 'Inventory', icon: Package },
  { href: '/admin/sell', label: 'Sell', icon: ShoppingCart },
  { href: '/admin/buy', label: 'Buy', icon: ShoppingBag },
  { href: '/admin/slabs', label: 'Slabs', icon: ScanLine },
  { href: '/admin/trade', label: 'Trade', icon: ArrowRightLeft },
  { href: '/admin/vault', label: 'Vault', icon: Lock },
  { href: '/admin/market', label: 'Market', icon: TrendingUp },
  { href: '/admin/show-prep', label: 'Show Prep', icon: MapPin },
  { href: '/admin/shows', label: 'Shows', icon: CalendarDays },
  { href: '/admin/outgoing', label: 'Prep Queue', icon: Tags },
  { href: '/admin/triage', label: 'Triage', icon: Stethoscope, badge: true },
  { href: '/admin/analytics', label: 'Show Analytics', icon: BarChart3 },
  { href: '/admin/history', label: 'History', icon: History },
  { href: '/admin/cosigners', label: 'Cosigners', icon: Users },
  { href: '/admin/locations', label: 'Locations', icon: MapPinned },
]

export default function AdminShell({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = useState(false)
  const [triageCount, setTriageCount] = useState(0)
  const pathname = usePathname()
  const api = useAdminApi()

  // The count is what makes the Triage tab get used instead of forgotten — a
  // queue with no visible number is a page nobody opens twice. Fetched per
  // navigation rather than cached: a stale badge that still counts a card the
  // admin just fixed is the exact failure this feature exists to avoid.
  // A failure is swallowed to zero on purpose; a chrome element must never be
  // able to break the page it frames.
  useEffect(() => {
    let cancelled = false
    api
      .get<{ total: number }>('/triage/counts')
      .then((data) => { if (!cancelled) setTriageCount(data?.total ?? 0) })
      .catch(() => { if (!cancelled) setTriageCount(0) })
    return () => { cancelled = true }
  }, [api, pathname])

  const isActive = (href: string) => {
    if (href === '/admin') return pathname === '/admin'
    return pathname.startsWith(href)
  }

  return (
    // h-screen, not min-h-screen: `overflow-y-auto` on <main> only bounds
    // scrolling when its flex parent's height is CAPPED. A minimum lets both
    // <aside> and <main> stretch to content height, so the document scrolls and
    // the sidebar rides away with it (RFC 0008 §F2). Capping here activates
    // <main>'s existing overflow and leaves <aside> viewport-bounded, which in
    // turn lets the nav's own overflow-y-auto engage when the tab list is long.
    <div className="vault-scope h-screen overflow-hidden font-sans text-pine-100 flex">
      {/* Sidebar */}
      <aside
        className={`
          hidden md:flex flex-col shrink-0 border-r border-pine-700/60
          bg-pine-900/80 backdrop-blur-sm transition-[width] duration-200
          ${collapsed ? 'w-[60px]' : 'w-[220px]'}
        `}
      >
        {/* Header */}
        <div className={`flex items-center h-14 px-3 border-b border-pine-700/40 ${collapsed ? 'justify-center' : 'justify-between'}`}>
          {!collapsed && (
            <span className="font-mono text-[11px] uppercase tracking-[0.18em] text-mint truncate">
              Admin
            </span>
          )}
          <button
            type="button"
            onClick={() => setCollapsed((c) => !c)}
            className="p-1.5 rounded-md text-pine-400 hover:text-pine-100 hover:bg-pine-700/50 transition-colors"
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {collapsed ? <PanelLeft size={18} /> : <PanelLeftClose size={18} />}
          </button>
        </div>

        {/* Navigation */}
        <nav className="flex-1 py-2 space-y-0.5 px-2 overflow-y-auto vault-scroll">
          {navItems.map(({ href, label, icon: Icon, badge }) => {
            const active = isActive(href)
            // Rendered only when there is outstanding work: a permanent "0"
            // chip is visual debt that trains the eye to ignore the badge.
            const showBadge = badge && triageCount > 0
            return (
              <Link
                key={href}
                href={href}
                title={collapsed ? label : undefined}
                className={`
                  flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-[13px] font-medium
                  transition-colors duration-150
                  ${active
                    ? 'bg-pine-700/70 text-mint shadow-sm'
                    : 'text-pine-300 hover:text-pine-100 hover:bg-pine-800/60'
                  }
                  ${collapsed ? 'justify-center px-0' : ''}
                `}
              >
                <Icon size={18} className={active ? 'text-mint' : 'text-pine-400'} />
                {!collapsed && <span className="truncate">{label}</span>}
                {showBadge && (
                  <span
                    className={`ml-auto rounded-full bg-amber-400/20 text-amber-300 text-[10px]
                                font-semibold px-1.5 py-0.5 leading-none
                                ${collapsed ? 'ml-0 absolute translate-x-3 -translate-y-2' : ''}`}
                  >
                    {triageCount}
                  </span>
                )}
              </Link>
            )
          })}
        </nav>

        {/* Footer */}
        <div className="px-2 py-3 border-t border-pine-700/40">
          <button
            type="button"
            onClick={() => signOut({ callbackUrl: '/' })}
            className={`
              flex items-center gap-2.5 w-full px-2.5 py-2 rounded-lg text-[13px]
              text-pine-400 hover:text-red-400 hover:bg-pine-800/60 transition-colors
              ${collapsed ? 'justify-center px-0' : ''}
            `}
            title="Sign out"
          >
            <LogOut size={16} />
            {!collapsed && <span>Sign out</span>}
          </button>
        </div>
      </aside>

      {/* Mobile bottom nav */}
      <nav className="md:hidden fixed bottom-0 inset-x-0 z-50 bg-pine-900/95 backdrop-blur-md border-t border-pine-700/60 px-1 py-1 flex justify-around safe-bottom">
        {navItems.slice(0, 5).map(({ href, label, icon: Icon }) => {
          const active = isActive(href)
          return (
            <Link
              key={href}
              href={href}
              className={`
                flex flex-col items-center gap-0.5 px-2 py-1.5 rounded-lg text-[10px]
                ${active ? 'text-mint' : 'text-pine-400'}
              `}
            >
              <Icon size={20} />
              <span>{label}</span>
            </Link>
          )
        })}
      </nav>

      {/* Main content */}
      <main className="flex-1 min-w-0 pb-20 md:pb-0 overflow-y-auto vault-scroll">
        {children}
      </main>
    </div>
  )
}
