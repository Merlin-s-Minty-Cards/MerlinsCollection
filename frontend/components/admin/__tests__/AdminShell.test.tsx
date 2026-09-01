import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent, cleanup, within } from '@testing-library/react'
import AdminShell from '../AdminShell'

// Mutable so a test can render at a DIFFERENT route — RFC 0010 T13's
// force-the-active-group-open rule is only observable from inside the group
// that is supposed to be forced. Every pre-existing test keeps the original
// value, restored in the file-level beforeEach.
let mockPathname = '/admin/inventory'
vi.mock('next/navigation', () => ({
  usePathname: () => mockPathname,
}))

vi.mock('next-auth/react', () => ({
  signOut: vi.fn(),
  // AdminShell mounts AdminChat (RFC 0018), which reads the Cognito access
  // token to call /admin/chat. Not a change to what this file tests — the
  // shell simply has a new child with a real session dependency.
  useSession: () => ({ data: { accessToken: 'test-token' }, status: 'authenticated' }),
}))

const getMock = vi.fn()

vi.mock('@/lib/admin-api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/admin-api')>('@/lib/admin-api')
  return {
    ...actual,
    useAdminApi: () => ({
      get: getMock,
      post: vi.fn(),
      put: vi.fn(),
      patch: vi.fn(),
      del: vi.fn(),
      isAuthenticated: true,
      isLoading: false,
    }),
  }
})

// File-level, not per-describe: AdminShell fetches the Triage badge count on
// every render, so EVERY test in this file — including the layout ones that
// predate the badge — needs `get` to return a promise.
beforeEach(() => {
  mockPathname = '/admin/inventory'
  getMock.mockReset()
  getMock.mockResolvedValue({ total: 0, reasons: {} })
})

function renderShell() {
  const { container } = render(
    <AdminShell>
      <div>page content</div>
    </AdminShell>,
  )
  const wrapper = container.querySelector('.vault-scope')
  if (!wrapper) throw new Error('AdminShell outer wrapper (.vault-scope) not found')
  return wrapper
}

describe('AdminShell layout bounding (RFC 0008 §F2)', () => {
  // `overflow-y-auto` on <main> only bounds scrolling when the flex parent's
  // height is CAPPED. `min-h-screen` is a floor, not a cap, so both <aside> and
  // <main> grow to content height and the *document* scrolls instead — which is
  // exactly why the sidebar scrolls out of view on a long inventory table.
  it('caps the outer wrapper to the viewport height instead of only flooring it', () => {
    const wrapper = renderShell()

    expect(wrapper.className).toMatch(/\bh-screen\b/)
    expect(wrapper.className).not.toMatch(/\bmin-h-screen\b/)
  })

  it('hides overflow on the outer wrapper so the document itself cannot scroll', () => {
    expect(renderShell().className).toMatch(/\boverflow-hidden\b/)
  })

  it('keeps <main> as the scroll container so page content still scrolls', () => {
    renderShell()

    const main = screen.getByRole('main')
    expect(main.className).toMatch(/\boverflow-y-auto\b/)
    // Clears the fixed mobile bottom nav; a capped wrapper must not eat this.
    expect(main.className).toMatch(/\bpb-20\b/)
  })

  it('lets the sidebar nav scroll independently when the tab list overflows', () => {
    // Queried through <aside> rather than by role: the mobile bottom bar is a
    // second <nav>, and only the sidebar one is under test here.
    const nav = renderShell().querySelector('aside nav')
    expect(nav?.className).toMatch(/\boverflow-y-auto\b/)
  })
})

// ===========================================================================
// T11 — Triage nav entry + outstanding-count badge
// ===========================================================================
//
// The badge is what makes the tab get used rather than forgotten: a queue with
// no visible count is a page nobody opens twice.
describe('AdminShell Triage nav (RFC 0008 T11)', () => {
  beforeEach(() => {
    getMock.mockReset()
    getMock.mockResolvedValue({ total: 0, reasons: {} })
  })

  it('links to /admin/triage from the sidebar', async () => {
    renderShell()

    const link = await screen.findByRole('link', { name: /triage/i })
    expect(link).toHaveAttribute('href', '/admin/triage')
  })

  it('shows the outstanding count from /admin/triage/counts', async () => {
    getMock.mockResolvedValue({
      total: 21,
      reasons: { flagged: 21, missing_card_id: 13, missing_english_name: 9 },
    })

    renderShell()

    await waitFor(() => expect(getMock).toHaveBeenCalledWith('/triage/counts'))
    const link = await screen.findByRole('link', { name: /triage/i })
    // `total`, not a sum of the per-reason counts: an item qualifying under two
    // reasons is one card to fix, and 43 would send the admin hunting for
    // cards that are not in the list.
    expect(link).toHaveTextContent('21')
  })

  it('renders no badge at all when the queue is empty', async () => {
    // The queue is meant to drain. A permanent "0" chip is visual debt that
    // trains the eye to ignore the badge entirely.
    renderShell()

    const link = await screen.findByRole('link', { name: /triage/i })
    await waitFor(() => expect(getMock).toHaveBeenCalled())
    expect(link).not.toHaveTextContent('0')
  })
})

// ===========================================================================
// T7 — Shows nav entry
// ===========================================================================

describe('AdminShell Shows nav (RFC 0008 T7)', () => {
  it('links to /admin/shows from the sidebar', async () => {
    renderShell()

    const link = await screen.findByRole('link', { name: /^shows$/i })
    expect(link).toHaveAttribute('href', '/admin/shows')
  })

  it('keeps Show Prep as its own distinct entry', async () => {
    // `isActive` matches on `pathname.startsWith(href)`, so a Shows entry sitting
    // next to Show Prep is exactly the pairing that goes wrong if either href is
    // a prefix of the other.
    renderShell()

    const link = await screen.findByRole('link', { name: /show prep/i })
    expect(link).toHaveAttribute('href', '/admin/show-prep')
  })
})

// ===========================================================================
// RFC 0010 T13 — sixteen flat tabs become three groups
// ===========================================================================
//
// Owner report: *"Create Larger tabs to hold sub tabs for this. Ex. 'Show'
// would hold our inventory, buy, sell, trade, slabs tabs"*. Grouped by WHEN
// you use them, which is why Inventory sits with the transaction tabs rather
// than with Vault.
//
// EVERY ROUTE PATH IS UNCHANGED, `/admin/outgoing` included. Grouping is a
// sidebar concern; nesting the URLs would break every bookmark to fix a URL
// nobody types.

const NAV_KEY = 'admin-nav-groups-v1'

/** Every destination, at the href it has always had. */
const ALL_DESTINATIONS: [string, RegExp][] = [
  ['/admin', /^dashboard$/i],
  ['/admin/inventory', /^inventory$/i],
  ['/admin/slabs', /^slabs$/i],
  ['/admin/trade', /buy \/ sell \/ trade/i],
  ['/admin/outgoing', /^prep queue$/i],
  ['/admin/show-prep', /^show prep$/i],
  ['/admin/shows', /^shows$/i],
  ['/admin/triage', /^triage$/i],
  ['/admin/unmatched', /^unmatched$/i],
  ['/admin/market', /^market$/i],
  ['/admin/vault', /^vault$/i],
  ['/admin/analytics', /^show analytics$/i],
  ['/admin/history', /^history$/i],
  ['/admin/cosigners', /^cosigners$/i],
  ['/admin/locations', /^locations$/i],
]

describe('AdminShell grouped navigation (RFC 0010 T13)', () => {
  beforeEach(() => {
    window.localStorage.clear()
  })

  it('still reaches every destination, at its existing href', async () => {
    renderShell()
    await waitFor(() => expect(getMock).toHaveBeenCalled())

    for (const [href, name] of ALL_DESTINATIONS) {
      const links = screen.getAllByRole('link', { name })
      expect(links.some((l) => l.getAttribute('href') === href),
        `${href} is unreachable`).toBe(true)
    }
  })

  it('renders the three group headers', () => {
    renderShell()
    for (const label of ['At the show', 'Back office', 'Data']) {
      expect(screen.getByRole('button', { name: label })).toBeInTheDocument()
    }
  })

  it('toggles a group open and shut, and says so with aria-expanded', () => {
    renderShell()
    const header = screen.getByRole('button', { name: 'Data' })
    expect(header).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('link', { name: /^cosigners$/i })).toBeInTheDocument()

    fireEvent.click(header)
    expect(header).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('link', { name: /^cosigners$/i })).not.toBeInTheDocument()

    fireEvent.click(header)
    expect(screen.getByRole('link', { name: /^cosigners$/i })).toBeInTheDocument()
  })

  it('forces the group containing the current route open, even if it was saved shut', () => {
    // Landing on a page whose group is collapsed, with no visible indication of
    // where you are, is worse than the flat list this replaces.
    window.localStorage.setItem(NAV_KEY, JSON.stringify({ office: false }))
    mockPathname = '/admin/triage'
    renderShell()

    expect(screen.getByRole('button', { name: 'Back office' }))
      .toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('link', { name: /^triage$/i })).toBeInTheDocument()
  })

  it('rolls the Triage count onto the group header while the group is shut', async () => {
    getMock.mockResolvedValue({ total: 21, reasons: {} })
    renderShell()
    await waitFor(() => expect(getMock).toHaveBeenCalledWith('/triage/counts'))
    await screen.findByRole('link', { name: /triage/i })

    // Back office holds Triage; `/admin/inventory` is the active route, so it
    // is shuttable.
    const header = screen.getByRole('button', { name: 'Back office' })
    fireEvent.click(header)

    expect(screen.queryByRole('link', { name: /^triage$/i })).not.toBeInTheDocument()
    // A count nobody can see is the exact failure the badge exists to avoid.
    expect(header).toHaveTextContent('21')
  })

  it('rolls no badge onto a shut group when the queue is empty', async () => {
    renderShell()
    await waitFor(() => expect(getMock).toHaveBeenCalled())
    const header = screen.getByRole('button', { name: 'Back office' })
    fireEvent.click(header)
    expect(header).not.toHaveTextContent('0')
  })

  it('round-trips the expansion state through a VERSIONED localStorage key', () => {
    const first = renderShell()
    fireEvent.click(screen.getByRole('button', { name: 'Data' }))
    expect(JSON.parse(window.localStorage.getItem(NAV_KEY) ?? '{}'))
      .toMatchObject({ data: false })

    cleanup()
    void first
    renderShell()
    expect(screen.getByRole('button', { name: 'Data' }))
      .toHaveAttribute('aria-expanded', 'false')
  })

  it('shows no truncated group label in the 60px sidebar — a title, not a stub', () => {
    renderShell()
    fireEvent.click(screen.getByRole('button', { name: /collapse sidebar/i }))

    const header = screen.getByRole('button', { name: 'Back office' })
    expect(header).toHaveAttribute('title', 'Back office')
    expect(header.textContent).not.toMatch(/Back office/)
  })

  it('puts Unmatched in Back office, directly after Triage (RFC 0011 T8)', () => {
    // The two queues are read together — Triage is "this is wrong", Unmatched is
    // "there is nothing to point at" — and a card moves from one to the other.
    const wrapper = renderShell()
    const aside = wrapper.querySelector('aside')
    if (!aside) throw new Error('sidebar not found')
    const labels = Array.from(aside.querySelectorAll('a')).map((a) => a.textContent)

    expect(labels).toContain('Unmatched')
    expect(labels.indexOf('Unmatched')).toBe(labels.indexOf('Triage') + 1)
  })

  it('does not give Unmatched a second badge (RFC 0011 T8)', async () => {
    // Two amber counts in one group trains the eye to stop reading both. The
    // Triage badge stays Triage's; Unmatched's count lives in its page header
    // and on the dashboard widget.
    getMock.mockResolvedValue({ total: 21, reasons: {} })
    renderShell()
    await waitFor(() => expect(getMock).toHaveBeenCalledWith('/triage/counts'))
    // A badged link's accessible name is "Triage 21", so wait on the COUNT
    // landing rather than on a bare-name match that only holds before it does.
    const triage = await screen.findByRole('link', { name: /triage/i })
    expect(triage).toHaveTextContent('21')

    expect(screen.getByRole('link', { name: /^unmatched$/i })).not.toHaveTextContent('21')
  })

  it('gives the mobile nav four EXPLICIT entries, not a slice of the tree', () => {
    // RFC 0011 T16: Sell + Buy collapsed into one "Deal" entry.
    const wrapper = renderShell()
    const mobile = wrapper.querySelectorAll('nav')[1]
    const hrefs = Array.from(mobile.querySelectorAll('a')).map((a) => a.getAttribute('href'))
    expect(hrefs).toEqual([
      '/admin', '/admin/inventory', '/admin/trade', '/admin/slabs',
    ])
  })
})

// ===========================================================================
// RFC 0011 T16 — /admin/buy and /admin/sell retired into /admin/trade
// ===========================================================================

describe('AdminShell nav after Buy/Sell retirement (RFC 0011 T16)', () => {
  it('offers one Buy / Sell / Trade entry, not three', () => {
    renderShell()
    const group = screen.getByRole('group', { name: 'At the show' })
    const labels = within(group).getAllByRole('link').map((l) => l.textContent?.trim())
    expect(labels).toEqual(['Inventory', 'Buy / Sell / Trade', 'Slabs'])
  })

  it('points the mobile bar at the merged route', () => {
    // An explicit list, never a .slice() of the groups.
    renderShell()
    const bar = screen.getByRole('navigation', { name: /mobile/i })
    expect(within(bar).getByRole('link', { name: /deal/i }))
      .toHaveAttribute('href', '/admin/trade')
    expect(within(bar).queryByRole('link', { name: /^buy$/i })).not.toBeInTheDocument()
  })

  it('marks the group active for the merged route', () => {
    // The group holding the active route is forced open regardless of what was saved.
    mockPathname = '/admin/trade'
    renderShell()
    expect(screen.getByRole('group', { name: 'At the show' })).toBeVisible()
  })

  it('has no link anywhere to a retired route', () => {
    // A nav entry pointing at a deleted page is a 404 the owner finds mid-show.
    renderShell()
    for (const link of screen.getAllByRole('link')) {
      const href = link.getAttribute('href') ?? ''
      expect(href.startsWith('/admin/buy')).toBe(false)
      expect(href.startsWith('/admin/sell')).toBe(false)
    }
  })
})
