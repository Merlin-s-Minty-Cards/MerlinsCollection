import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import AdminShell from '../AdminShell'

vi.mock('next/navigation', () => ({
  usePathname: () => '/admin/inventory',
}))

vi.mock('next-auth/react', () => ({
  signOut: vi.fn(),
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
