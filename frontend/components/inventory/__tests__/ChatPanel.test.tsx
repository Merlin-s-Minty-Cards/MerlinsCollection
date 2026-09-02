import { createRef } from 'react'
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

// Keep ApiError real (error-detail rendering depends on instanceof) — mock only apiFetch.
vi.mock('@/lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/api')>()),
  apiFetch: vi.fn(),
}))

// The panel reads the Cognito access token from the NextAuth session.
vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { accessToken: 'test-token' },
    status: 'authenticated',
  }),
}))

import { apiFetch, ApiError } from '@/lib/api'
import ChatPanel, { type ChatPanelHandle } from '@/components/inventory/ChatPanel'

const mockedApiFetch = vi.mocked(apiFetch)

let user: ReturnType<typeof userEvent.setup>

beforeEach(() => {
  // `mockReset`, NOT `vi.clearAllMocks()`. Measured 2026-08-10: `clearAllMocks`
  // clears call records but leaves the `mockResolvedValueOnce` QUEUE intact, and
  // a queued Once value outranks a later `mockResolvedValue`. So any test that
  // ends without consuming everything it queued hands its leftovers to the next
  // test, which then sees another test's fixture. That is what turned one slow
  // test in here into five failures whose count changed run to run.
  mockedApiFetch.mockReset()

  // `delay: null` removes user-event's inter-keystroke wait. It sends the same
  // events in the same order — it just stops charging a macrotask per character.
  // The history-cap test types ~120 characters and re-renders the panel after
  // each one; at the default delay it took 3.3s of the 5s budget with the
  // machine otherwise idle, so under full-suite parallel load it timed out.
  user = userEvent.setup({ delay: null })
})

describe('ChatPanel', () => {
  it('sends the message to /chat/ and renders both bubbles', async () => {
    mockedApiFetch.mockResolvedValue({ reply: 'Charizard is about $250.' })
    render(<ChatPanel />)

    await user.type(screen.getByRole('textbox'), 'How much is Charizard?')
    await user.click(screen.getByRole('button', { name: /send/i }))

    expect(screen.getByText('How much is Charizard?')).toBeInTheDocument()
    expect(await screen.findByText('Charizard is about $250.')).toBeInTheDocument()
    expect(mockedApiFetch).toHaveBeenCalledWith(
      '/chat/',
      expect.objectContaining({ method: 'POST' }),
    )
  })






  /**
   * RFC 0017 retired five tests here, and they are not replaced one-for-one
   * because the behavior they covered no longer exists on this side of the
   * wire. `buildHistory()` built the replay window from local state and shipped
   * it on every request; the transcript is server-owned now, so the client has
   * no history to shape, bound or sanitize.
   *
   * Where each invariant went — all of them still tested, just not here:
   *   - replay is the SERVER's, from storage
   *       -> test_conversations.py::test_server_replays_stored_history_to_bedrock_not_client_sent_history
   *   - a client-sent history array is accepted and IGNORED
   *       -> test_conversations.py::test_client_sent_history_is_ignored
   *   - alternation, well-formedness, and the 20-turn cap
   *       -> services/conversations.py::replay_turns (MAX_REPLAY_TURNS)
   *   - empty turn content is rejected
   *       -> models/chat.py::ChatTurn.content (min_length=1)
   *
   * What replaced them here is the thread id itself: see the RFC 0017 describe
   * block below, in particular "sends the conversation_id the server returned
   * on the next message".
   */
  it('does not send an empty message', async () => {
    render(<ChatPanel />)
    await user.click(screen.getByRole('button', { name: /send/i }))
    expect(mockedApiFetch).not.toHaveBeenCalled()
  })

  it('forwards the Cognito access token from the session as a bearer token', async () => {
    mockedApiFetch.mockResolvedValue({ reply: 'ok' })
    render(<ChatPanel />)

    await user.type(screen.getByRole('textbox'), 'hi')
    await user.click(screen.getByRole('button', { name: /send/i }))
    expect(await screen.findByText('ok')).toBeInTheDocument()

    expect(mockedApiFetch).toHaveBeenCalledWith(
      '/chat/',
      expect.objectContaining({ token: 'test-token' }),
    )
  })

  it('shows the backend detail message when the API returns a typed error', async () => {
    mockedApiFetch.mockRejectedValue(
      new ApiError(429, 'Service is temporarily busy — please try again shortly.'),
    )
    render(<ChatPanel />)
    await user.type(screen.getByRole('textbox'), 'hi')
    await user.click(screen.getByRole('button', { name: /send/i }))
    expect(
      await screen.findByText(/temporarily busy/i),
    ).toBeInTheDocument()
  })

  it('shows a generic error bubble when the request fails without detail', async () => {
    mockedApiFetch.mockRejectedValue(new Error('boom'))
    render(<ChatPanel />)
    await user.type(screen.getByRole('textbox'), 'hi')
    await user.click(screen.getByRole('button', { name: /send/i }))
    expect(await screen.findByText(/something went wrong/i)).toBeInTheDocument()
  })

  it('renders markdown formatting in assistant replies', async () => {
    mockedApiFetch.mockResolvedValue({ reply: 'The **Charizard** is from Base Set.' })
    render(<ChatPanel />)

    await user.type(screen.getByRole('textbox'), 'How much is Charizard?')
    await user.click(screen.getByRole('button', { name: /send/i }))

    const strong = await screen.findByText('Charizard')
    expect(strong.tagName).toBe('STRONG')
  })

  it('renders literal asterisks in user bubbles, not markdown', async () => {
    mockedApiFetch.mockResolvedValue({ reply: 'Sure thing.' })
    render(<ChatPanel />)

    await user.type(screen.getByRole('textbox'), 'What about **this** card?')
    await user.click(screen.getByRole('button', { name: /send/i }))

    expect(await screen.findByText('What about **this** card?')).toBeInTheDocument()
  })
})


const displayCard = (itemId: string, name = 'Charizard') => ({
  item_id: itemId,
  kind: 'raw' as const,
  card: {
    card_id: `en:base1-${itemId}`,
    name,
    set_name: 'Base Set',
    number: '4',
    image_small: 'https://assets.tcgdex.net/en/base/base1/4/low.webp',
  },
  display_name: null,
  listed_price: '275.00',
  current_market_value: '450.00',
  condition: 'LP',
  company: null,
  grade: null,
  grade_label: null,
  cert_number: null,
  language: 'EN',
})

describe('ChatPanel display artifacts (RFC 0016, updated for RFC 0019)', () => {
  it('sends the currently displayed panel item IDs on the next turn', async () => {
    mockedApiFetch
      .mockResolvedValueOnce({
        reply: 'Opened three cards.',
        artifacts: [],
        panel: {
          cards: [displayCard('item-1'), displayCard('item-2'), displayCard('item-3')],
          truncated: false,
        },
      })
      .mockResolvedValueOnce({
        reply: 'Still open.',
        artifacts: [],
        panel: { cards: [displayCard('item-1')], truncated: false },
      })
    render(<ChatPanel />)
    const box = screen.getByRole('textbox')

    await user.type(box, 'show three')
    await user.click(screen.getByRole('button', { name: /send/i }))
    expect(await screen.findByText('Opened three cards.')).toBeInTheDocument()
    await user.type(box, 'what is open?')
    await user.click(screen.getByRole('button', { name: /send/i }))
    expect(await screen.findByText('Still open.')).toBeInTheDocument()

    const body = JSON.parse(
      String((mockedApiFetch.mock.lastCall![1] as RequestInit).body),
    ) as { panel_item_ids?: string[] }
    expect(body.panel_item_ids).toEqual(['item-1', 'item-2', 'item-3'])
  })

  it('renders inline artifacts from the response', async () => {
    mockedApiFetch.mockResolvedValue({
      reply: 'Here is one card.',
      artifacts: [displayCard('item-1')],
      panel: { cards: [], truncated: false },
    })
    render(<ChatPanel />)
    await user.type(screen.getByRole('textbox'), 'show one')
    await user.click(screen.getByRole('button', { name: /send/i }))
    expect(await screen.findByRole('heading', { name: 'Charizard' })).toBeInTheDocument()
    // listed_price ($275.00, displayCard's fixture) must win over
    // current_market_value ($450.00) — same precedence fix as DisplayPanel;
    // Council r2 self-review flagged both surfaces sharing the bug.
    expect(screen.getByText('$275.00')).toBeInTheDocument()
    expect(screen.queryByText('$450.00')).not.toBeInTheDocument()
  })

  it('caps inline artifacts to a bounded grid instead of the full chat width', async () => {
    // Owner report, 2026-08-25: a single inline card spanned nearly the
    // entire chat pane. The grid is shared with DisplayPanel (CARD_GRID_CLASS)
    // so a card renders the same size everywhere; `max-w-[85%]` matches the
    // width other chat bubbles already cap themselves to.
    mockedApiFetch.mockResolvedValue({
      reply: 'Here is one card.',
      artifacts: [displayCard('item-1')],
      panel: { cards: [], truncated: false },
    })
    render(<ChatPanel />)
    await user.type(screen.getByRole('textbox'), 'show one')
    await user.click(screen.getByRole('button', { name: /send/i }))
    const heading = await screen.findByRole('heading', { name: 'Charizard' })
    const grid = heading.closest('[class*="grid-cols-"]')
    expect(grid).not.toBeNull()
    expect(grid).toHaveClass('max-w-[85%]')
  })

  it('reports the display view via onDisplayChange when cards is non-empty', async () => {
    // RFC 0019: ChatPanel no longer renders DisplayPanel itself — it pushes a
    // normalized view up to the shared right-pane ResultsPane instead.
    mockedApiFetch.mockResolvedValue({
      reply: 'Panel open.',
      artifacts: [],
      panel: { cards: [displayCard('item-1')], truncated: false },
    })
    const onDisplayChange = vi.fn()
    render(<ChatPanel onDisplayChange={onDisplayChange} />)
    await user.type(screen.getByRole('textbox'), 'open panel')
    await user.click(screen.getByRole('button', { name: /send/i }))
    await screen.findByText('Panel open.')
    expect(onDisplayChange).toHaveBeenLastCalledWith(
      expect.objectContaining({
        headerLabel: 'Display (1)',
        cards: [expect.objectContaining({ title: 'Charizard' })],
      }),
    )
    // ChatPanel itself renders no heading for the display state anymore.
    expect(screen.queryByRole('heading', { name: /Display \(/ })).toBeNull()
  })

  it('reports an empty display view when cards is empty', async () => {
    mockedApiFetch.mockResolvedValue({
      reply: 'Panel hidden.',
      artifacts: [],
      panel: { cards: [], truncated: false },
    })
    const onDisplayChange = vi.fn()
    render(<ChatPanel onDisplayChange={onDisplayChange} />)
    await user.type(screen.getByRole('textbox'), 'hide panel')
    await user.click(screen.getByRole('button', { name: /send/i }))
    expect(await screen.findByText('Panel hidden.')).toBeInTheDocument()
    expect(onDisplayChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ headerLabel: 'Display (0)', cards: [] }),
    )
  })

  it('reports the display view alongside inline artifacts, independently', async () => {
    mockedApiFetch.mockResolvedValue({
      reply: 'One inline, one in the panel.',
      artifacts: [displayCard('inline-1', 'Pikachu')],
      panel: { cards: [displayCard('panel-1')], truncated: false },
    })
    const onDisplayChange = vi.fn()
    render(<ChatPanel onDisplayChange={onDisplayChange} />)
    await user.type(screen.getByRole('textbox'), 'show both')
    await user.click(screen.getByRole('button', { name: /send/i }))
    expect(await screen.findByText('One inline, one in the panel.')).toBeInTheDocument()
    // Inline artifact still renders directly in the transcript, unaffected.
    expect(screen.getByRole('heading', { name: 'Pikachu' })).toBeInTheDocument()
    expect(onDisplayChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ headerLabel: 'Display (1)' }),
    )
  })

  it('exposes clearDisplay() via ref, clearing panel IDs without touching the transcript', async () => {
    mockedApiFetch
      .mockResolvedValueOnce({
        reply: 'Panel open.',
        artifacts: [],
        panel: { cards: [displayCard('item-1')], truncated: false },
      })
      .mockResolvedValueOnce({
        reply: 'No panel.',
        artifacts: [],
        panel: { cards: [], truncated: false },
      })
    const ref = createRef<ChatPanelHandle>()
    render(<ChatPanel ref={ref} />)
    const box = screen.getByRole('textbox')
    await user.type(box, 'open')
    await user.click(screen.getByRole('button', { name: /send/i }))
    await screen.findByText('Panel open.')

    act(() => ref.current!.clearDisplay())

    await user.type(box, 'next')
    await user.click(screen.getByRole('button', { name: /send/i }))

    const body = JSON.parse(
      String((mockedApiFetch.mock.lastCall![1] as RequestInit).body),
    ) as { panel_item_ids?: string[] }
    expect(body.panel_item_ids).toEqual([])
    // The transcript survives clearDisplay() — only reset() wipes it.
    expect(screen.getByText('open')).toBeInTheDocument()
  })

  it('exposes reset() via ref, clearing the transcript, input, and display together', async () => {
    mockedApiFetch.mockResolvedValueOnce({
      reply: 'Panel open.',
      artifacts: [],
      panel: { cards: [displayCard('item-1')], truncated: false },
    })
    const onDisplayChange = vi.fn()
    const ref = createRef<ChatPanelHandle>()
    render(<ChatPanel ref={ref} onDisplayChange={onDisplayChange} />)
    await user.type(screen.getByRole('textbox'), 'open')
    await user.click(screen.getByRole('button', { name: /send/i }))
    await screen.findByText('Panel open.')

    act(() => ref.current!.reset())

    expect(screen.queryByText('open')).toBeNull()
    expect(screen.queryByText('Panel open.')).toBeNull()
    expect(onDisplayChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ headerLabel: 'Display (0)', cards: [] }),
    )
  })

  it('ignores an in-flight reply that resolves after reset(), so a stale answer cannot repopulate a fresh conversation', async () => {
    let resolveReply!: (value: { reply: string }) => void
    mockedApiFetch.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveReply = resolve
      }),
    )
    const onDisplayChange = vi.fn()
    const ref = createRef<ChatPanelHandle>()
    render(<ChatPanel ref={ref} onDisplayChange={onDisplayChange} />)

    await user.type(screen.getByRole('textbox'), 'doomed question')
    await user.click(screen.getByRole('button', { name: /send/i }))
    expect(screen.getByText('doomed question')).toBeInTheDocument()

    // New chat, before the in-flight request resolves.
    act(() => ref.current!.reset())
    expect(screen.queryByText('doomed question')).toBeNull()

    // The stale request now resolves — it must not repopulate the reset
    // transcript or overwrite the (already-cleared) display state.
    await act(async () => {
      resolveReply({ reply: 'Stale answer for a question nobody can see.' })
      await Promise.resolve()
    })
    expect(screen.queryByText('Stale answer for a question nobody can see.')).toBeNull()
    expect(screen.queryByText('doomed question')).toBeNull()
  })

  it('preserves multi-turn add/remove panel_item_ids transitions across turns', async () => {
    mockedApiFetch
      .mockResolvedValueOnce({
        reply: 'Added three.',
        artifacts: [],
        panel: {
          cards: [displayCard('item-1'), displayCard('item-2'), displayCard('item-3')],
          truncated: false,
        },
      })
      .mockResolvedValueOnce({
        reply: 'Removed one.',
        artifacts: [],
        panel: {
          cards: [displayCard('item-1'), displayCard('item-3')],
          truncated: false,
        },
      })
    render(<ChatPanel />)
    const box = screen.getByRole('textbox')

    const turns = [
      ['add three', 'Added three.'],
      ['remove second', 'Removed one.'],
    ] as const
    for (const [message, reply] of turns) {
      await user.type(box, message)
      await user.click(screen.getByRole('button', { name: /send/i }))
      expect(await screen.findByText(reply)).toBeInTheDocument()
    }

    const bodies = mockedApiFetch.mock.calls.map((call) =>
      JSON.parse(String((call[1] as RequestInit).body)),
    ) as Array<{ panel_item_ids?: string[] }>
    expect(bodies[0].panel_item_ids).toEqual([])
    expect(bodies[1].panel_item_ids).toEqual(['item-1', 'item-2', 'item-3'])
  })
})
/**
 * RFC 0017 item 8 — the transcript is SERVER-owned now. ChatPanel stops
 * shipping a `history` array it built from local state and instead carries a
 * `conversation_id` the server returns; the backend replays the thread from
 * storage, which is also what stops a client forging assistant turns.
 */
describe('ChatPanel conversation history (RFC 0017)', () => {
  function chatReply(overrides: Record<string, unknown> = {}) {
    return {
      reply: 'ok',
      artifacts: [],
      panel: { cards: [], truncated: false },
      conversation_id: '01JD',
      title: 'A thread',
      ...overrides,
    }
  }

  function bodyOf(callIndex: number) {
    const init = mockedApiFetch.mock.calls[callIndex][1]
    return JSON.parse(String(init?.body))
  }

  it('starts a new thread by sending no conversation_id, and no client history', async () => {
    mockedApiFetch.mockResolvedValue(chatReply())
    render(<ChatPanel />)

    await user.type(screen.getByRole('textbox'), 'first')
    await user.click(screen.getByRole('button', { name: /send/i }))

    const body = bodyOf(0)
    expect(body.conversation_id).toBeUndefined()
    expect(body).not.toHaveProperty('history')
  })

  it('sends the conversation_id the server returned on the next message', async () => {
    mockedApiFetch.mockResolvedValue(chatReply())
    render(<ChatPanel />)

    await user.type(screen.getByRole('textbox'), 'first')
    await user.click(screen.getByRole('button', { name: /send/i }))
    await user.type(screen.getByRole('textbox'), 'second')
    await user.click(screen.getByRole('button', { name: /send/i }))

    expect(bodyOf(1).conversation_id).toBe('01JD')
  })

  it('reset() drops the thread so the next message starts a fresh one', async () => {
    mockedApiFetch.mockResolvedValue(chatReply())
    const ref = createRef<ChatPanelHandle>()
    render(<ChatPanel ref={ref} />)

    await user.type(screen.getByRole('textbox'), 'first')
    await user.click(screen.getByRole('button', { name: /send/i }))
    act(() => ref.current!.reset())
    await user.type(screen.getByRole('textbox'), 'after reset')
    await user.click(screen.getByRole('button', { name: /send/i }))

    expect(bodyOf(1).conversation_id).toBeUndefined()
  })

  /**
   * The blocking finding from this task's pre-change adversarial review.
   *
   * `routers/chat.py` sets `response.conversation_id` unconditionally, AFTER a
   * deliberately-broad `except` that swallows a persistence failure so a
   * paid-for Bedrock reply is never discarded. So a new thread whose
   * `append_exchange` failed hands back a well-formed id for a conversation
   * that was never written. Storing it verbatim and sending it again 404s at
   * the ownership check — and would go on 404ing forever, wedging the chat
   * with no way out but a page reload.
   */
  it('recovers from a 404 by dropping the dead thread id, not by wedging', async () => {
    mockedApiFetch.mockResolvedValueOnce(chatReply({ conversation_id: 'never-persisted' }))
    mockedApiFetch.mockRejectedValueOnce(new ApiError(404, 'Conversation not found.'))
    mockedApiFetch.mockResolvedValueOnce(chatReply({ conversation_id: '01JNEW' }))
    render(<ChatPanel />)

    await user.type(screen.getByRole('textbox'), 'first')
    await user.click(screen.getByRole('button', { name: /send/i }))
    await user.type(screen.getByRole('textbox'), 'second')
    await user.click(screen.getByRole('button', { name: /send/i }))
    await user.type(screen.getByRole('textbox'), 'third')
    await user.click(screen.getByRole('button', { name: /send/i }))

    // The second message carried the (doomed) id — proving it was stored at all.
    expect(bodyOf(1).conversation_id).toBe('never-persisted')
    // The third must not, or the chat 404s forever on a thread that never existed.
    expect(bodyOf(2).conversation_id).toBeUndefined()
  })

  it('loadConversation() replaces the transcript, display and thread id together', async () => {
    mockedApiFetch.mockResolvedValue({
      conversation_id: '01JOLD',
      title: 'Resumed',
      created_at: '2026-08-26T18:04:11Z',
      updated_at: '2026-08-26T18:22:40Z',
      truncated: false,
      messages: [
        { seq: 1, role: 'user', content: 'older question', artifacts: [], created_at: '2026-08-26T18:04:11Z' },
        { seq: 2, role: 'assistant', content: 'older answer', artifacts: [], created_at: '2026-08-26T18:04:12Z' },
      ],
      panel: { cards: [], truncated: false },
    })
    const ref = createRef<ChatPanelHandle>()
    render(<ChatPanel ref={ref} />)

    await act(async () => {
      await ref.current!.loadConversation('01JOLD')
    })

    expect(screen.getByText('older question')).toBeInTheDocument()
    expect(screen.getByText('older answer')).toBeInTheDocument()

    mockedApiFetch.mockResolvedValue(chatReply({ conversation_id: '01JOLD' }))
    await user.type(screen.getByRole('textbox'), 'follow up')
    await user.click(screen.getByRole('button', { name: /send/i }))

    expect(bodyOf(1).conversation_id).toBe('01JOLD')
  })

  /**
   * A 404 here is routine, not exceptional: the thread was deleted in another
   * tab, or aged out by the six-month TTL. It must not escape the imperative
   * handle as an unhandled rejection, and it must not half-replace the state.
   */
  it('leaves the current thread untouched when loadConversation() 404s', async () => {
    mockedApiFetch.mockResolvedValueOnce(chatReply({ conversation_id: '01JKEEP' }))
    const ref = createRef<ChatPanelHandle>()
    render(<ChatPanel ref={ref} />)

    await user.type(screen.getByRole('textbox'), 'keep me')
    await user.click(screen.getByRole('button', { name: /send/i }))
    expect(screen.getByText('keep me')).toBeInTheDocument()

    mockedApiFetch.mockRejectedValue(new ApiError(404, 'Conversation not found.'))
    await act(async () => {
      await expect(ref.current!.loadConversation('gone')).resolves.toBeUndefined()
    })

    // Transcript survives, and the live thread id is still the one we had.
    expect(screen.getByText('keep me')).toBeInTheDocument()

    mockedApiFetch.mockResolvedValue(chatReply({ conversation_id: '01JKEEP' }))
    await user.type(screen.getByRole('textbox'), 'still here')
    await user.click(screen.getByRole('button', { name: /send/i }))
    expect(bodyOf(mockedApiFetch.mock.calls.length - 1).conversation_id).toBe('01JKEEP')
  })
})
