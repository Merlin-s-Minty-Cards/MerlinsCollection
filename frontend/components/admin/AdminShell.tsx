'use client'

import { useEffect, useRef, useState } from 'react'
import { usePathname } from 'next/navigation'
import Link from 'next/link'
import {
  LayoutDashboard,
  Package,
  ArrowRightLeft,
  ScanLine,
  TrendingUp,
  MapPin,
  MapPinned,
  CalendarDays,
  Lock,
  Stethoscope,
  Unlink,
  Tags,
  BarChart3,
  History,
  Users,
  PanelLeftClose,
  PanelLeft,
  ChevronDown,
  ChevronRight,
  LogOut,
} from 'lucide-react'
import { signOut } from 'next-auth/react'
import { useAdminApi } from '@/lib/admin-api'
import AdminChat from './AdminChat'

/**
 * The admin tabs, grouped by WHEN you use them (RFC 0010 T13). Sixteen at the
 * time of that change; Unmatched (RFC 0011 T8) made seventeen, which is the
 * point of the grouping — a flat list had already outgrown the viewport.
 *
 * Owner's choice of the three groupings offered: *At the show / Back office /
 * Data*. That is why Inventory sits with the transaction tabs rather than with
 * Vault — at a show table you are looking things up to sell them.
 *
 * **EVERY ROUTE PATH IS UNCHANGED**, `/admin/outgoing` included, even though it
 * is labelled *Prep Queue*. Grouping is a sidebar concern; nesting the URLs
 * would break every bookmark and doc reference to fix a URL nobody types.
 * CLAUDE.md already documents that gotcha.
 *
 * Within-group order is the old `navItems` order preserved wherever possible,
 * so muscle memory survives the change.
 */
const topLevel = [
  { href: '/admin', label: 'Dashboard', icon: LayoutDashboard },
]

const navGroups = [
  {
    id: 'show',
    label: 'At the show',
    items: [
      { href: '/admin/inventory', label: 'Inventory', icon: Package },
      // RFC 0011 T16: /admin/buy and /admin/sell are retired. `/admin/trade`
      // is now the single route for all three modes (T15), reached via
      // ?mode=buy|sell|trade — the label spells out all three so nothing has
      // to be learned from a one-word name.
      { href: '/admin/trade', label: 'Buy / Sell / Trade', icon: ArrowRightLeft },
      { href: '/admin/slabs', label: 'Slabs', icon: ScanLine },
    ],
  },
  {
    id: 'office',
    label: 'Back office',
    items: [
      { href: '/admin/outgoing', label: 'Prep Queue', icon: Tags },
      { href: '/admin/show-prep', label: 'Show Prep', icon: MapPin },
      { href: '/admin/shows', label: 'Shows', icon: CalendarDays },
      { href: '/admin/triage', label: 'Triage', icon: Stethoscope, badge: true },
      // Directly after Triage, because the two are read together and a card
      // moves from one to the other: Triage is "this is wrong", Unmatched is
      // "there is nothing to point at". Deliberately NO `badge` — the Triage
      // count is the only amber number in this group, and two of them trains
      // the eye to stop reading both. Unmatched's count lives in its own page
      // header and on the dashboard widget.
      { href: '/admin/unmatched', label: 'Unmatched', icon: Unlink },
      { href: '/admin/market', label: 'Market', icon: TrendingUp },
      { href: '/admin/vault', label: 'Vault', icon: Lock },
    ],
  },
  {
    id: 'data',
    label: 'Data',
    items: [
      { href: '/admin/analytics', label: 'Show Analytics', icon: BarChart3 },
      { href: '/admin/history', label: 'History', icon: History },
      { href: '/admin/cosigners', label: 'Cosigners', icon: Users },
      { href: '/admin/locations', label: 'Locations', icon: MapPinned },
    ],
  },
] as const

/**
 * The phone's five, declared OUTRIGHT rather than sliced off the tree.
 *
 * `navItems.slice(0, 5)` is what this replaces: flattening a nested structure
 * and slicing it silently changes what a phone shows, and nobody would notice.
 * It is not hypothetical here — flattening the groups above and taking five
 * yields Trade where Slabs used to be.
 */
// "Deal" here, "Buy / Sell / Trade" in the sidebar (RFC 0011 T16) — a
// deliberate divergence, not an inconsistency to "fix": the mobile bar is
// four icons across a phone and the long sidebar label does not fit.
const mobileItems = [
  { href: '/admin', label: 'Dashboard', icon: LayoutDashboard },
  { href: '/admin/inventory', label: 'Inventory', icon: Package },
  { href: '/admin/trade', label: 'Deal', icon: ArrowRightLeft },
  { href: '/admin/slabs', label: 'Slabs', icon: ScanLine },
]

/**
 * VERSIONED, so a later grouping change cannot silently resurrect a saved shape
 * that no longer matches. Same discipline as RFC 0008's column-visibility key.
 */
const NAV_GROUPS_KEY = 'admin-nav-groups-v1'

type OpenMap = Record<string, boolean>

function readSavedGroups(): OpenMap {
  if (typeof window === 'undefined') return {}
  try {
    const raw = window.localStorage.getItem(NAV_GROUPS_KEY)
    const parsed = raw ? JSON.parse(raw) : null
    return parsed && typeof parsed === 'object' ? (parsed as OpenMap) : {}
  } catch {
    return {}
  }
}

export default function AdminShell({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = useState(false)
  const [triageCount, setTriageCount] = useState(0)
  // Absent means OPEN. Every destination is reachable on a first visit, which
  // is the least surprising migration from a flat list; shutting a group is
  // then a deliberate act the key above remembers.
  const [openGroups, setOpenGroups] = useState<OpenMap>({})
  const pathname = usePathname()
  const api = useAdminApi()
  // A real flex sibling of <main>, in the SAME row as <aside> — this is what
  // lets AdminChat's panel take real layout space and shrink <main> instead
  // of overlaying it (owner report 2026-08-28). AdminChat portals into it.
  const chatSlotRef = useRef<HTMLDivElement>(null)

  // Read on mount, not in the initial state: `useState(readSavedGroups)` runs
  // during SSR too, where there is no localStorage, and the hydrated markup
  // would then disagree with the server's.
  useEffect(() => {
    setOpenGroups(readSavedGroups())
  }, [])

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

  // The group holding the current route is ALWAYS open, whatever was saved.
  // Landing on a page whose group is shut, with no visible indication of where
  // you are, is worse than the flat list this replaces.
  const isOpen = (group: (typeof navGroups)[number]) =>
    group.items.some((item) => isActive(item.href)) || openGroups[group.id] !== false

  const toggleGroup = (id: string, next: boolean) => {
    setOpenGroups((prev) => {
      const merged = { ...prev, [id]: next }
      try {
        window.localStorage.setItem(NAV_GROUPS_KEY, JSON.stringify(merged))
      } catch {
        // A private-mode browser must not be able to break the sidebar.
      }
      return merged
    })
  }

  const showBadgeCount = triageCount > 0

  const navLink = (
    { href, label, icon: Icon, badge }:
    { href: string; label: string; icon: typeof Package; badge?: boolean },
    { indented = false }: { indented?: boolean } = {},
  ) => {
    const active = isActive(href)
    // Rendered only when there is outstanding work: a permanent "0" chip is
    // visual debt that trains the eye to ignore the badge.
    const withBadge = badge && showBadgeCount
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
          ${collapsed ? 'justify-center px-0' : indented ? 'ml-2' : ''}
        `}
      >
        <Icon size={18} className={active ? 'text-mint' : 'text-pine-400'} />
        {!collapsed && <span className="truncate">{label}</span>}
        {withBadge && (
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
          {topLevel.map((item) => navLink(item))}

          {navGroups.map((group) => {
            const open = isOpen(group)
            // Only when SHUT, deliberately: a badge on both the header and the
            // row beneath it is the same number twice, and this is chrome.
            const rollUp =
              !open && showBadgeCount && group.items.some((i) => 'badge' in i && i.badge)
            return (
              <div key={group.id} className="pt-1.5 first:pt-0">
                {/* A <button> with aria-expanded, not a div with an onClick:
                    the sidebar is keyboard-navigated by anyone using it
                    one-handed at a show table. */}
                <button
                  type="button"
                  aria-expanded={open}
                  aria-controls={`nav-group-${group.id}`}
                  aria-label={group.label}
                  title={group.label}
                  onClick={() => toggleGroup(group.id, !open)}
                  className={`
                    flex w-full items-center gap-1.5 rounded-md text-pine-400
                    transition-colors hover:text-pine-200
                    ${collapsed
                      // At 60px there is no room for a label, and a truncated
                      // one is an unreadable stub. A thin divider carrying a
                      // tooltip is the honest rendering.
                      ? 'my-1.5 h-px justify-center bg-pine-700/60 p-0'
                      : 'px-2.5 py-1 font-mono text-[11px] uppercase tracking-[0.18em] text-mint'
                    }
                  `}
                >
                  {!collapsed && (
                    <>
                      {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                      <span>{group.label}</span>
                    </>
                  )}
                  {rollUp && (
                    <span
                      className={`rounded-full bg-amber-400/20 text-amber-300 text-[10px]
                                  font-semibold px-1.5 py-0.5 leading-none
                                  ${collapsed ? 'absolute translate-x-3' : 'ml-auto'}`}
                    >
                      {triageCount}
                    </span>
                  )}
                </button>
                {open && (
                  <div
                    id={`nav-group-${group.id}`}
                    role="group"
                    aria-label={group.label}
                    className="space-y-0.5"
                  >
                    {group.items.map((item) => navLink(item, { indented: true }))}
                  </div>
                )}
              </div>
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
      <nav
        aria-label="Mobile navigation"
        className="md:hidden fixed bottom-0 inset-x-0 z-50 bg-pine-900/95 backdrop-blur-md border-t border-pine-700/60 px-1 py-1 flex justify-around safe-bottom"
      >

        {mobileItems.map(({ href, label, icon: Icon }) => {
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
        {/* The analyst chat's toggle (RFC 0018 decision 2). It lives here, above
            the page, rather than in the sidebar: the panel is available on
            EVERY tab, and the tab underneath stays mounted while it is open —
            the questions worth asking are about the rows you are looking at. */}
        <div className="sticky top-0 z-30 flex justify-end border-b border-pine-700/40 bg-pine-950/80 px-4 py-2 backdrop-blur-md">
          <AdminChat slotRef={chatSlotRef} />
        </div>
        {children}
      </main>

      {/* Empty when the panel is closed — an empty flex item with no
          explicit width takes none, so <main> is untouched until AdminChat
          portals its (width-capped) panel in here. shrink-0 keeps it at
          exactly that width rather than being squeezed by flexbox's default
          proportional-shrink alongside <main>'s own min-w-0. */}
      <div ref={chatSlotRef} className="shrink-0" />
    </div>
  )
}
