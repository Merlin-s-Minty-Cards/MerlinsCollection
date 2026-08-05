'use client'

import { useState } from 'react'
import { usePathname } from 'next/navigation'
import Link from 'next/link'
import {
  LayoutDashboard,
  Package,
  ShoppingCart,
  ShoppingBag,
  ArrowRightLeft,
  TrendingUp,
  MapPin,
  MapPinned,
  Lock,
  Tags,
  BarChart3,
  History,
  Users,
  PanelLeftClose,
  PanelLeft,
  LogOut,
} from 'lucide-react'
import { signOut } from 'next-auth/react'

const navItems = [
  { href: '/admin', label: 'Dashboard', icon: LayoutDashboard },
  { href: '/admin/inventory', label: 'Inventory', icon: Package },
  { href: '/admin/sell', label: 'Sell', icon: ShoppingCart },
  { href: '/admin/buy', label: 'Buy', icon: ShoppingBag },
  { href: '/admin/trade', label: 'Trade', icon: ArrowRightLeft },
  { href: '/admin/vault', label: 'Vault', icon: Lock },
  { href: '/admin/market', label: 'Market', icon: TrendingUp },
  { href: '/admin/show-prep', label: 'Show Prep', icon: MapPin },
  { href: '/admin/outgoing', label: 'Prep Queue', icon: Tags },
  { href: '/admin/analytics', label: 'Show Analytics', icon: BarChart3 },
  { href: '/admin/history', label: 'History', icon: History },
  { href: '/admin/cosigners', label: 'Cosigners', icon: Users },
  { href: '/admin/locations', label: 'Locations', icon: MapPinned },
]

export default function AdminShell({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = useState(false)
  const pathname = usePathname()

  const isActive = (href: string) => {
    if (href === '/admin') return pathname === '/admin'
    return pathname.startsWith(href)
  }

  return (
    <div className="vault-scope min-h-screen font-sans text-pine-100 flex">
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
          {navItems.map(({ href, label, icon: Icon }) => {
            const active = isActive(href)
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
