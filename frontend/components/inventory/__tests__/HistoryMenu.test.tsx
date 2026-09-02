import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@/lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/api')>()),
  apiFetch: vi.fn(),
}))

vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { accessToken: 'test-token' },
    status: 'authenticated',
  }),
}))

import { apiFetch } from '@/lib/api'
import HistoryMenu from '../HistoryMenu'

const mockedApiFetch = vi.mocked(apiFetch)

let user: ReturnType<typeof userEvent.setup>

function summary(overrides: Record<string, unknown> = {}) {
  return {
    conversation_id: '01JA',
    title: 'Charizards under $300',
    created_at: '2026-08-26T18:04:11Z',
    updated_at: '2026-08-26T18:22:40Z',
    message_count: 6,
    ...overrides,
  }
}

beforeEach(() => {
  // mockReset, not clearAllMocks — see ChatPanel.test.tsx for the measurement.
  mockedApiFetch.mockReset()
  user = userEvent.setup({ delay: null })
})

async function openWith(conversations: unknown[]) {
  mockedApiFetch.mockResolvedValue({ conversations })
  const utils = render(<HistoryMenu />)
  await user.click(screen.getByRole('button', { name: /history/i }))
  return utils
}

describe('HistoryMenu', () => {
  it('is closed by default, and fetches nothing until opened', () => {
    render(<HistoryMenu />)
    expect(screen.queryByText(/no past conversations/i)).toBeNull()
    expect(mockedApiFetch).not.toHaveBeenCalled()
  })

  it('shows an empty state when the caller has no threads', async () => {
    await openWith([])
    expect(await screen.findByText('No past conversations yet')).toBeInTheDocument()
  })

  it('lists the threads it fetched on open', async () => {
    await openWith([summary(), summary({ conversation_id: '01JB', title: 'Base set holos' })])
    expect(await screen.findByText('Charizards under $300')).toBeInTheDocument()
    expect(screen.getByText('Base set holos')).toBeInTheDocument()
  })

  /**
   * Fetching on OPEN rather than once on mount is what keeps this list out of
   * the session race that CLAUDE.md records ("A FETCH-ONCE ADMIN DROPDOWN HOOK
   * CAN LOSE THE SESSION RACE"): a mount-time fetch with `[]` deps that lands
   * during NextAuth's `loading` window 401s and never retries. It also keeps
   * the list fresh, since every sent message reorders and retitles it.
   */
  it('refetches on each open, so a stale list is never shown', async () => {
    await openWith([summary()])
    await screen.findByText('Charizards under $300')

    await user.click(screen.getByRole('button', { name: /history/i }))
    mockedApiFetch.mockResolvedValue({
      conversations: [summary({ title: 'Renamed elsewhere' })],
    })
    await user.click(screen.getByRole('button', { name: /history/i }))

    expect(await screen.findByText('Renamed elsewhere')).toBeInTheDocument()
  })

  it('surfaces a load failure instead of showing an empty list', async () => {
    mockedApiFetch.mockRejectedValue(new Error('network'))
    render(<HistoryMenu />)
    await user.click(screen.getByRole('button', { name: /history/i }))

    expect(await screen.findByText('Could not load conversations.')).toBeInTheDocument()
    expect(screen.queryByText('No past conversations yet')).toBeNull()
  })

  it('opens a thread and closes the flyout', async () => {
    const onSelect = vi.fn()
    mockedApiFetch.mockResolvedValue({ conversations: [summary()] })
    render(<HistoryMenu onSelect={onSelect} />)
    await user.click(screen.getByRole('button', { name: /history/i }))

    await user.click(await screen.findByText('Charizards under $300'))

    expect(onSelect).toHaveBeenCalledWith('01JA')
    await waitFor(() =>
      expect(screen.queryByText('Charizards under $300')).toBeNull(),
    )
  })

  it('marks the thread the chat currently has open', async () => {
    mockedApiFetch.mockResolvedValue({ conversations: [summary()] })
    render(<HistoryMenu activeConversationId="01JA" />)
    await user.click(screen.getByRole('button', { name: /history/i }))

    const row = (await screen.findByText('Charizards under $300')).closest('button')
    expect(row).toHaveAttribute('aria-current', 'true')
  })

  it('renames a thread in place', async () => {
    await openWith([summary()])
    await user.click(await screen.findByRole('button', { name: /rename/i }))

    const field = screen.getByLabelText('Conversation title')
    await user.clear(field)
    await user.type(field, 'Holo Charizards')
    await user.click(screen.getByRole('button', { name: 'Save title' }))

    expect(await screen.findByText('Holo Charizards')).toBeInTheDocument()
    const patch = mockedApiFetch.mock.calls.find((call) => call[1]?.method === 'PATCH')
    expect(patch?.[0]).toBe('/chat/conversations/01JA')
    expect(JSON.parse(String(patch?.[1]?.body))).toEqual({ title: 'Holo Charizards' })
  })

  it('abandons a rename on Escape without calling the API', async () => {
    await openWith([summary()])
    await user.click(await screen.findByRole('button', { name: /rename/i }))
    await user.type(screen.getByLabelText('Conversation title'), 'nope')
    fireEvent.keyDown(screen.getByLabelText('Conversation title'), { key: 'Escape' })

    expect(await screen.findByText('Charizards under $300')).toBeInTheDocument()
    expect(mockedApiFetch.mock.calls.some((call) => call[1]?.method === 'PATCH')).toBe(false)
  })

  /** Destructive actions confirm in place — never on the first click. */
  it('requires a confirmation before deleting a thread', async () => {
    await openWith([summary()])
    await user.click(await screen.findByRole('button', { name: /delete charizards/i }))

    expect(screen.getByText('Delete this conversation?')).toBeInTheDocument()
    expect(mockedApiFetch.mock.calls.some((call) => call[1]?.method === 'DELETE')).toBe(false)

    await user.click(screen.getByRole('button', { name: 'Delete' }))

    const del = mockedApiFetch.mock.calls.find((call) => call[1]?.method === 'DELETE')
    expect(del?.[0]).toBe('/chat/conversations/01JA')
    await waitFor(() => expect(screen.queryByText('Charizards under $300')).toBeNull())
  })

  it('cancels a delete without touching the API', async () => {
    await openWith([summary()])
    await user.click(await screen.findByRole('button', { name: /delete charizards/i }))
    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(await screen.findByText('Charizards under $300')).toBeInTheDocument()
    expect(mockedApiFetch.mock.calls.some((call) => call[1]?.method === 'DELETE')).toBe(false)
  })

  it('tells the parent which thread went away, so it can clear the chat', async () => {
    const onRemoved = vi.fn()
    mockedApiFetch.mockResolvedValue({ conversations: [summary()] })
    render(<HistoryMenu onRemoved={onRemoved} />)
    await user.click(screen.getByRole('button', { name: /history/i }))
    await user.click(await screen.findByRole('button', { name: /delete charizards/i }))
    await user.click(screen.getByRole('button', { name: 'Delete' }))

    await waitFor(() => expect(onRemoved).toHaveBeenCalledWith('01JA'))
  })

  it('requires a confirmation before clearing every thread', async () => {
    const onRemoved = vi.fn()
    mockedApiFetch.mockResolvedValue({ conversations: [summary()] })
    render(<HistoryMenu onRemoved={onRemoved} />)
    await user.click(screen.getByRole('button', { name: /history/i }))
    await user.click(await screen.findByRole('button', { name: 'Clear all' }))

    expect(screen.getByText('Delete all conversations?')).toBeInTheDocument()
    expect(mockedApiFetch.mock.calls.some((call) => call[1]?.method === 'DELETE')).toBe(false)

    await user.click(screen.getByRole('button', { name: 'Delete all' }))

    const del = mockedApiFetch.mock.calls.find((call) => call[1]?.method === 'DELETE')
    expect(del?.[0]).toBe('/chat/conversations')
    await waitFor(() => expect(onRemoved).toHaveBeenCalledWith('all'))
  })

  it('closes when the button is clicked again', async () => {
    await openWith([])
    expect(await screen.findByText('No past conversations yet')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /history/i }))
    expect(screen.queryByText(/no past conversations/i)).toBeNull()
  })

  it('closes on an outside click', async () => {
    mockedApiFetch.mockResolvedValue({ conversations: [] })
    render(
      <div>
        <HistoryMenu />
        <button>Elsewhere</button>
      </div>,
    )
    await user.click(screen.getByRole('button', { name: /history/i }))
    expect(await screen.findByText('No past conversations yet')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Elsewhere' }))
    expect(screen.queryByText(/no past conversations/i)).toBeNull()
  })

  it('closes on Escape', async () => {
    await openWith([])
    expect(await screen.findByText('No past conversations yet')).toBeInTheDocument()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByText(/no past conversations/i)).toBeNull()
  })

  it('filters the list by title as the operator types', async () => {
    await openWith([
      summary({ conversation_id: '01JA', title: 'Charizards under $300' }),
      summary({ conversation_id: '01JB', title: 'Base set holos' }),
    ])
    await screen.findByText('Charizards under $300')

    await user.type(screen.getByRole('textbox', { name: /search/i }), 'holo')

    expect(screen.queryByText('Charizards under $300')).toBeNull()
    expect(screen.getByText('Base set holos')).toBeInTheDocument()
  })

  it('says so when a search matches nothing, instead of the generic empty state', async () => {
    await openWith([summary({ title: 'Charizards under $300' })])
    await screen.findByText('Charizards under $300')

    await user.type(screen.getByRole('textbox', { name: /search/i }), 'zzz')

    expect(screen.queryByText('No past conversations yet')).toBeNull()
    expect(screen.getByText(/no conversations match/i)).toBeInTheDocument()
  })

  it('clears the search on close, so reopening starts unfiltered', async () => {
    await openWith([
      summary({ conversation_id: '01JA', title: 'Charizards under $300' }),
      summary({ conversation_id: '01JB', title: 'Base set holos' }),
    ])
    await screen.findByText('Charizards under $300')
    await user.type(screen.getByRole('textbox', { name: /search/i }), 'holo')
    expect(screen.queryByText('Charizards under $300')).toBeNull()

    await user.click(screen.getByRole('button', { name: /history/i })) // close
    mockedApiFetch.mockResolvedValue({
      conversations: [
        summary({ conversation_id: '01JA', title: 'Charizards under $300' }),
        summary({ conversation_id: '01JB', title: 'Base set holos' }),
      ],
    })
    await user.click(screen.getByRole('button', { name: /history/i })) // reopen

    expect(await screen.findByText('Charizards under $300')).toBeInTheDocument()
  })
})

describe('HistoryMenu bound to an alternate client', () => {
  it('reads and writes through the client it is given, not the customer default', async () => {
    // The admin analyst chat (RFC 0018) reuses this component rather than
    // hand-rolling its own dropdown, so the same flyout has to be able to
    // point at `/admin/chat/conversations` instead of `/chat/conversations`.
    const { createConversationsClient } = await import('@/lib/conversations')
    const adminLikeClient = createConversationsClient('/admin/chat/conversations')
    mockedApiFetch.mockResolvedValue({ conversations: [summary()] })

    render(<HistoryMenu client={adminLikeClient} />)
    await user.click(screen.getByRole('button', { name: /history/i }))

    await screen.findByText('Charizards under $300')
    expect(mockedApiFetch).toHaveBeenCalledWith(
      '/admin/chat/conversations',
      expect.objectContaining({}),
    )
  })
})

/**
 * Found in this task's post-change adversarial pass: `onRemoved` used to fire
 * after the await regardless of outcome, so a delete that FAILED still told
 * the parent the thread was gone — resetting a chat whose thread is alive and
 * whose row the list had just restored.
 */
describe('HistoryMenu when a destructive call fails', () => {
  it('keeps the row and does not tell the parent anything vanished', async () => {
    const onRemoved = vi.fn()
    mockedApiFetch.mockResolvedValueOnce({ conversations: [summary()] })
    render(<HistoryMenu onRemoved={onRemoved} />)
    await user.click(screen.getByRole('button', { name: /history/i }))
    await user.click(await screen.findByRole('button', { name: /delete charizards/i }))

    mockedApiFetch.mockRejectedValueOnce(new Error('network'))
    mockedApiFetch.mockResolvedValueOnce({ conversations: [summary()] })
    await user.click(screen.getByRole('button', { name: 'Delete' }))

    expect(await screen.findByText('Charizards under $300')).toBeInTheDocument()
    expect(onRemoved).not.toHaveBeenCalled()
  })

  it('does not clear the chat when clear-all fails', async () => {
    const onRemoved = vi.fn()
    mockedApiFetch.mockResolvedValueOnce({ conversations: [summary()] })
    render(<HistoryMenu onRemoved={onRemoved} />)
    await user.click(screen.getByRole('button', { name: /history/i }))
    await user.click(await screen.findByRole('button', { name: 'Clear all' }))

    mockedApiFetch.mockRejectedValueOnce(new Error('network'))
    mockedApiFetch.mockResolvedValueOnce({ conversations: [summary()] })
    await user.click(screen.getByRole('button', { name: 'Delete all' }))

    expect(await screen.findByText('Charizards under $300')).toBeInTheDocument()
    expect(onRemoved).not.toHaveBeenCalled()
  })
})
