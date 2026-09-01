import { useRef } from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('next-auth/react', () => ({
  useSession: () => ({ data: { accessToken: 'admin-token' }, status: 'authenticated' }),
}))

const sendAdminChat = vi.hoisted(() => vi.fn())
const adminConversations = vi.hoisted(() => ({
  list: vi.fn(async () => []),
  get: vi.fn(),
  rename: vi.fn(),
  remove: vi.fn(),
  clear: vi.fn(),
}))

vi.mock('@/lib/admin-conversations', () => ({ sendAdminChat, adminConversations }))

import AdminChat from '../AdminChat'

/**
 * `AdminChat` no longer positions its own panel — it pushes AdminShell's
 * content pane by portalling into a slot AdminShell owns (a real flex sibling
 * of `<main>`, so the panel takes actual layout space instead of overlaying
 * it — the owner's "reduce the width instead of overlapping" report,
 * 2026-08-28). In production that slot always exists; these standalone tests
 * (no AdminShell) provide one of their own so `AdminChat` has somewhere real
 * to portal into.
 */
function AdminChatHarness() {
  const slotRef = useRef<HTMLDivElement>(null)
  return (
    <>
      <AdminChat slotRef={slotRef} />
      <div ref={slotRef} />
    </>
  )
}

const reply = (text: string, artifacts: unknown[] = []) => ({
  reply: text,
  artifacts,
  panel: { cards: [], truncated: false },
  conversation_id: '01ADMIN',
  title: 'Portland margin',
})

beforeEach(() => {
  sendAdminChat.mockReset()
  adminConversations.list.mockReset()
  adminConversations.list.mockResolvedValue([])
  window.localStorage.clear()
})

describe('AdminChat', () => {
  it('is closed until asked for, so it never covers the tab you are on', () => {
    render(<AdminChatHarness />)
    expect(screen.queryByRole('dialog', { name: /analyst/i })).toBeNull()
    expect(screen.getByRole('button', { name: /analyst/i })).toBeInTheDocument()
  })

  it('opens as a slide-over and can be closed again', async () => {
    const user = userEvent.setup({ delay: null })
    render(<AdminChatHarness />)

    await user.click(screen.getByRole('button', { name: /analyst/i }))
    expect(await screen.findByRole('dialog', { name: /analyst/i })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /close/i }))
    await waitFor(() =>
      expect(screen.queryByRole('dialog', { name: /analyst/i })).toBeNull(),
    )
  })

  it('closes on Escape', async () => {
    const user = userEvent.setup({ delay: null })
    render(<AdminChatHarness />)
    await user.click(screen.getByRole('button', { name: /analyst/i }))
    await screen.findByRole('dialog', { name: /analyst/i })

    await user.keyboard('{Escape}')
    await waitFor(() =>
      expect(screen.queryByRole('dialog', { name: /analyst/i })).toBeNull(),
    )
  })

  it('closes the whole panel on Escape even while the history flyout is open', async () => {
    // Deliberate simplification, flagged in adversarial review 2026-08-28:
    // HistoryMenu now owns its own open state, so AdminChat has nothing left
    // to check before deciding what one Escape press should do. It used to
    // close just the flyout first (two-step); now one Escape closes both.
    // Pinned here so that behavior is a tested choice, not an untested side
    // effect of the HistoryMenu refactor.
    const user = userEvent.setup({ delay: null })
    render(<AdminChatHarness />)
    await user.click(screen.getByRole('button', { name: /analyst/i }))
    await user.click(screen.getByRole('button', { name: /conversation history/i }))
    expect(await screen.findByText(/no past conversations/i)).toBeInTheDocument()

    await user.keyboard('{Escape}')

    await waitFor(() =>
      expect(screen.queryByRole('dialog', { name: /analyst/i })).toBeNull(),
    )
  })

  it('asks the ADMIN route and renders the answer', async () => {
    const user = userEvent.setup({ delay: null })
    sendAdminChat.mockResolvedValue(reply('Portland netted $1,330 (31.6%).'))
    render(<AdminChatHarness />)

    await user.click(screen.getByRole('button', { name: /analyst/i }))
    await user.type(
      screen.getByRole('textbox', { name: /ask/i }),
      'what did I net at Portland?',
    )
    await user.click(screen.getByRole('button', { name: /send/i }))

    expect(await screen.findByText(/Portland netted \$1,330/)).toBeInTheDocument()
    expect(sendAdminChat).toHaveBeenCalledWith(
      'what did I net at Portland?',
      expect.objectContaining({}),
      expect.objectContaining({ token: 'admin-token' }),
    )
  })

  it('renders card results INLINE with image, name and price', async () => {
    // Open Question 1: the answer and its evidence stay together, rather than
    // being pushed into the tab underneath. CLAUDE.md's absolute rule then
    // applies — a name alone never identifies a card.
    const user = userEvent.setup({ delay: null })
    sendAdminChat.mockResolvedValue(
      reply('These three are aging.', [
        {
          item_id: 'i1',
          kind: 'raw',
          card: {
            card_id: 'en:base1-4',
            name: 'Charizard',
            set_name: 'Base Set',
            number: '4',
            image_small: 'https://img.example/charizard.png',
          },
          display_name: null,
          listed_price: '250.00',
          current_market_value: '250.00',
          condition: 'NM',
          company: null,
          grade: null,
          grade_label: null,
          cert_number: null,
          language: 'EN',
        },
      ]),
    )
    render(<AdminChatHarness />)
    await user.click(screen.getByRole('button', { name: /analyst/i }))
    await user.type(screen.getByRole('textbox', { name: /ask/i }), 'aging stock?')
    await user.click(screen.getByRole('button', { name: /send/i }))

    expect(await screen.findByText('Charizard')).toBeInTheDocument()
    expect(screen.getByText(/250/)).toBeInTheDocument()
    const img = screen.getByRole('img', { name: /charizard/i })
    expect(img).toHaveAttribute('src', expect.stringContaining('charizard.png'))
  })

  it('carries the conversation id into the next message so the thread continues', async () => {
    const user = userEvent.setup({ delay: null })
    sendAdminChat.mockResolvedValue(reply('First.'))
    render(<AdminChatHarness />)
    await user.click(screen.getByRole('button', { name: /analyst/i }))

    const box = screen.getByRole('textbox', { name: /ask/i })
    await user.type(box, 'margin?')
    await user.click(screen.getByRole('button', { name: /send/i }))
    await screen.findByText('First.')

    sendAdminChat.mockResolvedValue(reply('Second.'))
    await user.type(box, 'and last month?')
    await user.click(screen.getByRole('button', { name: /send/i }))

    await waitFor(() => expect(sendAdminChat).toHaveBeenCalledTimes(2))
    expect(sendAdminChat.mock.calls[1][1]).toMatchObject({ conversationId: '01ADMIN' })
  })

  it('drops a dead conversation id on a 404 instead of wedging on it forever', async () => {
    // The customer chat's RFC-0017 lesson, inherited: `conversation_id` is set
    // unconditionally AFTER the broad except that swallows a persistence
    // failure, so an id can name a thread that was never written. Holding it
    // would 404 every later message permanently.
    const user = userEvent.setup({ delay: null })
    const { ApiError } = await import('@/lib/api')
    sendAdminChat.mockResolvedValue(reply('First.'))
    render(<AdminChatHarness />)
    await user.click(screen.getByRole('button', { name: /analyst/i }))

    const box = screen.getByRole('textbox', { name: /ask/i })
    await user.type(box, 'margin?')
    await user.click(screen.getByRole('button', { name: /send/i }))
    await screen.findByText('First.')

    sendAdminChat.mockRejectedValueOnce(new ApiError(404, 'Conversation not found.'))
    await user.type(box, 'again?')
    await user.click(screen.getByRole('button', { name: /send/i }))
    await waitFor(() => expect(sendAdminChat).toHaveBeenCalledTimes(2))

    sendAdminChat.mockResolvedValue(reply('Fresh.'))
    await user.type(box, 'third?')
    await user.click(screen.getByRole('button', { name: /send/i }))
    await waitFor(() => expect(sendAdminChat).toHaveBeenCalledTimes(3))

    expect(sendAdminChat.mock.calls[2][1].conversationId).toBeUndefined()
  })

  it('fetches thread history on OPEN, never once on mount', async () => {
    // CLAUDE.md: a `useEffect(..., [])` fetch that lands during NextAuth's
    // loading window 401s, is swallowed into an empty list, and has no
    // dependency to retry on. Fetching on open sidesteps the race entirely.
    // The history list itself is HistoryMenu's own (RFC 0017), so "open"
    // here is specifically the history flyout opening, not the whole panel —
    // opening the panel to send a message must not cost a conversations call.
    const user = userEvent.setup({ delay: null })
    render(<AdminChatHarness />)
    expect(adminConversations.list).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: /analyst/i }))
    expect(adminConversations.list).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: /conversation history/i }))
    await waitFor(() => expect(adminConversations.list).toHaveBeenCalled())
  })

  it('remembers its width across mounts', async () => {
    const user = userEvent.setup({ delay: null })
    const { unmount } = render(<AdminChatHarness />)
    await user.click(screen.getByRole('button', { name: /analyst/i }))
    const panel = await screen.findByRole('dialog', { name: /analyst/i })

    const handle = screen.getByRole('separator', { name: /resize/i })
    await user.click(handle)
    await user.keyboard('{ArrowLeft}')          // widen (the panel is right-anchored)
    const widened = (panel as HTMLElement).style.width
    expect(widened).not.toBe('')

    unmount()
    render(<AdminChatHarness />)
    await user.click(screen.getByRole('button', { name: /analyst/i }))
    const reopened = await screen.findByRole('dialog', { name: /analyst/i })
    expect((reopened as HTMLElement).style.width).toBe(widened)
  })
})

describe('AdminChat inside AdminShell', () => {
  it('is reachable from every admin tab, with the tab still mounted underneath', async () => {
    // Decision 2: a slide-over, not a route. The page you were on must still be
    // rendered while the panel is open — that is the whole reason this is not
    // `/admin/chat`.
    vi.doMock('next/navigation', () => ({ usePathname: () => '/admin/inventory' }))
    vi.doMock('@/lib/admin-api', () => ({
      useAdminApi: () => ({ get: vi.fn(async () => ({})), isAuthenticated: true }),
    }))
    const { default: AdminShell } = await import('../AdminShell')

    const user = userEvent.setup({ delay: null })
    render(
      <AdminShell>
        <p>Inventory tab content</p>
      </AdminShell>,
    )

    expect(screen.getByText('Inventory tab content')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /analyst/i }))

    expect(await screen.findByRole('dialog', { name: /analyst/i })).toBeInTheDocument()
    expect(screen.getByText('Inventory tab content')).toBeInTheDocument()
  })

  it('renders the panel OUTSIDE the blurred sticky header', async () => {
    // Measured in a real browser 2026-08-27 (roadmap item 9b), not theorised.
    // The toggle lives in a `sticky ... z-30 ... backdrop-blur-md` wrapper, and
    // `backdrop-filter` does two things at once to any `position: fixed`
    // descendant:
    //
    //   1. it becomes their CONTAINING BLOCK, so `fixed top-0` anchored to the
    //      header rather than the viewport — measured at y=67 when anything sat
    //      above `<main>`, putting the composer below the fold;
    //   2. it opens a STACKING CONTEXT, so the panel's own `z-40` could never
    //      out-rank a sibling of the header. `AdminShell`'s mobile bottom nav
    //      is `z-50`, so on every phone width `document.elementFromPoint` at the
    //      centre of the message input returned the nav's link, not the input:
    //      the analyst chat could be opened and read but never typed into.
    //
    // Both go away if the dialog is not a descendant of that wrapper. This test
    // pins the structural half — a browser has to check the stacking half, which
    // is why the measurement is recorded above rather than asserted here.
    vi.doMock('next/navigation', () => ({ usePathname: () => '/admin/inventory' }))
    vi.doMock('@/lib/admin-api', () => ({
      useAdminApi: () => ({ get: vi.fn(async () => ({})), isAuthenticated: true }),
    }))
    const { default: AdminShell } = await import('../AdminShell')

    const user = userEvent.setup({ delay: null })
    render(
      <AdminShell>
        <p>Inventory tab content</p>
      </AdminShell>,
    )
    await user.click(screen.getByRole('button', { name: /analyst/i }))
    const dialog = await screen.findByRole('dialog', { name: /analyst/i })

    const blurred = document.querySelector('.backdrop-blur-md.sticky')
    expect(blurred).not.toBeNull()
    expect(blurred!.contains(dialog)).toBe(false)
  })

  it('pushes the content pane instead of overlaying it', async () => {
    // Owner report 2026-08-28: "the sidebar overlaps the existing tab, when
    // it should reduce the width of the tab to fit the sidebar with no
    // overlap." The panel used to be `position: fixed`, which by definition
    // takes no layout space from anything — <main> never even knew it was
    // open. It is now a normal-flow flex sibling of <main>, portalled into a
    // slot AdminShell renders in the SAME row, so opening it genuinely
    // shrinks <main> instead of drawing over it.
    vi.doMock('next/navigation', () => ({ usePathname: () => '/admin/inventory' }))
    vi.doMock('@/lib/admin-api', () => ({
      useAdminApi: () => ({ get: vi.fn(async () => ({})), isAuthenticated: true }),
    }))
    const { default: AdminShell } = await import('../AdminShell')

    const user = userEvent.setup({ delay: null })
    render(
      <AdminShell>
        <p>Inventory tab content</p>
      </AdminShell>,
    )
    await user.click(screen.getByRole('button', { name: /analyst/i }))
    const dialog = await screen.findByRole('dialog', { name: /analyst/i })
    const main = screen.getByRole('main')

    expect(dialog.className).not.toMatch(/\bfixed\b/)
    expect(dialog.closest('main')).toBeNull()
    // A flex SIBLING of <main>, in the same row AdminShell lays <aside> and
    // <main> out in — not merely "somewhere in document.body".
    expect(main.parentElement?.contains(dialog)).toBe(true)
  })

  it('caps its own width at the viewport, so a phone gets full coverage instead of clipping', async () => {
    // The panel is no longer anchored with `right: 0` — its position in the
    // page comes from ordinary DOM order now, and its width is expressed as
    // `min(<configured>, 100vw)` so it can never demand more than the screen
    // actually has. On a desktop-sized jsdom window this stays comfortably
    // under 100vw; the CSS `min()` itself is what protects a narrow phone,
    // which is a browser fact CLAUDE.md's own lesson says jsdom cannot check.
    vi.doMock('next/navigation', () => ({ usePathname: () => '/admin/inventory' }))
    vi.doMock('@/lib/admin-api', () => ({
      useAdminApi: () => ({ get: vi.fn(async () => ({})), isAuthenticated: true }),
    }))
    const { default: AdminShell } = await import('../AdminShell')

    const user = userEvent.setup({ delay: null })
    render(
      <AdminShell>
        <p>Inventory tab content</p>
      </AdminShell>,
    )
    await user.click(screen.getByRole('button', { name: /analyst/i }))
    const dialog = await screen.findByRole('dialog', { name: /analyst/i })

    expect((dialog as HTMLElement).style.width).toMatch(/^min\(\d+px,\s*100vw\)$/)
  })

  it('shows conversation history through the shared HistoryMenu, scoped to the admin client', async () => {
    // The history dropdown used to be hand-rolled inside AdminChat itself —
    // no click-outside-to-close, no last-edited date, no search — missing
    // everything the customer surface's HistoryMenu (RFC 0017) already had.
    // Reusing that component fixes all three at once instead of reimplementing
    // them a second time, worse.
    vi.doMock('next/navigation', () => ({ usePathname: () => '/admin/inventory' }))
    vi.doMock('@/lib/admin-api', () => ({
      useAdminApi: () => ({ get: vi.fn(async () => ({})), isAuthenticated: true }),
    }))
    const { default: AdminShell } = await import('../AdminShell')
    adminConversations.list.mockResolvedValue([
      {
        conversation_id: '01ADMIN',
        title: 'Portland margin',
        created_at: '2026-08-20T00:00:00Z',
        updated_at: '2026-08-27T18:22:40Z',
        message_count: 4,
      },
    ])

    const user = userEvent.setup({ delay: null })
    render(
      <AdminShell>
        <p>Inventory tab content</p>
      </AdminShell>,
    )
    await user.click(screen.getByRole('button', { name: /analyst/i }))
    await user.click(screen.getByRole('button', { name: /conversation history/i }))

    expect(await screen.findByText('Portland margin')).toBeInTheDocument()
    expect(adminConversations.list).toHaveBeenCalled()

    await user.click(screen.getByText('Portland margin'))
    await waitFor(() => expect(adminConversations.get).toHaveBeenCalledWith(
      '01ADMIN',
      expect.objectContaining({}),
    ))
  })
})
