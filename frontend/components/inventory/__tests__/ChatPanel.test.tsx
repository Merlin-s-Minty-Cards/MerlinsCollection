import { render, screen } from '@testing-library/react'
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
import ChatPanel from '@/components/inventory/ChatPanel'

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

  it('includes prior turns in the history on a follow-up message', async () => {
    mockedApiFetch
      .mockResolvedValueOnce({ reply: 'First answer.' })
      .mockResolvedValueOnce({ reply: 'Second answer.' })
    render(<ChatPanel />)
    const box = screen.getByRole('textbox')

    await user.type(box, 'first question')
    await user.click(screen.getByRole('button', { name: /send/i }))
    expect(await screen.findByText('First answer.')).toBeInTheDocument()

    await user.type(box, 'second question')
    await user.click(screen.getByRole('button', { name: /send/i }))
    expect(await screen.findByText('Second answer.')).toBeInTheDocument()

    expect(mockedApiFetch).toHaveBeenLastCalledWith(
      '/chat/',
      expect.objectContaining({
        body: JSON.stringify({
          message: 'second question',
          history: [
            { role: 'user', content: 'first question' },
            { role: 'assistant', content: 'First answer.' },
          ],
          panel_item_ids: [],
        }),
      }),
    )
  })

  it('drops failed turns from history so one error cannot poison the conversation', async () => {
    // Converse requires strict user/assistant alternation — an unanswered user
    // turn in history would 502 every following request.
    mockedApiFetch
      .mockRejectedValueOnce(new Error('boom'))
      .mockResolvedValueOnce({ reply: 'Recovered.' })
    render(<ChatPanel />)
    const box = screen.getByRole('textbox')

    await user.type(box, 'doomed question')
    await user.click(screen.getByRole('button', { name: /send/i }))
    expect(await screen.findByText(/something went wrong/i)).toBeInTheDocument()

    await user.type(box, 'second question')
    await user.click(screen.getByRole('button', { name: /send/i }))
    expect(await screen.findByText('Recovered.')).toBeInTheDocument()

    expect(mockedApiFetch).toHaveBeenLastCalledWith(
      '/chat/',
      expect.objectContaining({
        body: JSON.stringify({
          message: 'second question',
          history: [],
          panel_item_ids: [],
        }),
      }),
    )
  })

  it('caps history at the backend limit of 20 turns, keeping the most recent pairs', async () => {
    for (let i = 0; i < 12; i++) {
      mockedApiFetch.mockResolvedValueOnce({ reply: `answer ${i}` })
    }
    render(<ChatPanel />)
    const box = screen.getByRole('textbox')

    for (let i = 0; i < 12; i++) {
      await user.type(box, `question ${i}`)
      await user.click(screen.getByRole('button', { name: /send/i }))
      expect(await screen.findByText(`answer ${i}`)).toBeInTheDocument()
    }

    const lastBody = JSON.parse(
      String((mockedApiFetch.mock.lastCall![1] as RequestInit).body),
    ) as { history: Array<{ role: string; content: string }> }
    // 11 completed exchanges = 22 turns; only the last 20 may be sent.
    expect(lastBody.history).toHaveLength(20)
    expect(lastBody.history[0]).toEqual({ role: 'user', content: 'question 1' })
    expect(lastBody.history[19]).toEqual({ role: 'assistant', content: 'answer 10' })
  })

  it('omits empty-content turns from history (backend rejects them)', async () => {
    mockedApiFetch
      .mockResolvedValueOnce({ reply: '' })
      .mockResolvedValueOnce({ reply: 'Real answer.' })
    render(<ChatPanel />)
    const box = screen.getByRole('textbox')

    await user.type(box, 'first question')
    await user.click(screen.getByRole('button', { name: /send/i }))

    await user.type(box, 'second question')
    await user.click(screen.getByRole('button', { name: /send/i }))
    expect(await screen.findByText('Real answer.')).toBeInTheDocument()

    expect(mockedApiFetch).toHaveBeenLastCalledWith(
      '/chat/',
      expect.objectContaining({
        body: JSON.stringify({
          message: 'second question',
          history: [],
          panel_item_ids: [],
        }),
      }),
    )
  })

  it('truncates an over-long assistant reply in history so the backend cap cannot 422 the next turn', async () => {
    // Backend ChatTurn.content caps at 4000 chars; an unbounded reply replayed
    // as history would 422 every following request and stick the conversation.
    const longReply = 'x'.repeat(5000)
    mockedApiFetch
      .mockResolvedValueOnce({ reply: longReply })
      .mockResolvedValueOnce({ reply: 'second answer' })
    render(<ChatPanel />)
    const box = screen.getByRole('textbox')

    await user.type(box, 'first question')
    await user.click(screen.getByRole('button', { name: /send/i }))
    expect(await screen.findByText(longReply)).toBeInTheDocument()

    await user.type(box, 'second question')
    await user.click(screen.getByRole('button', { name: /send/i }))
    expect(await screen.findByText('second answer')).toBeInTheDocument()

    const lastBody = JSON.parse(
      String((mockedApiFetch.mock.lastCall![1] as RequestInit).body),
    ) as { history: Array<{ role: string; content: string }> }
    expect(lastBody.history[1].role).toBe('assistant')
    expect(lastBody.history[1].content.length).toBeLessThanOrEqual(4000)
  })

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

describe('ChatPanel display artifacts (RFC 0016 RED)', () => {
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

  it('renders the display panel when cards is non-empty', async () => {
    mockedApiFetch.mockResolvedValue({
      reply: 'Panel open.',
      artifacts: [],
      panel: { cards: [displayCard('item-1')], truncated: false },
    })
    render(<ChatPanel />)
    await user.type(screen.getByRole('textbox'), 'open panel')
    await user.click(screen.getByRole('button', { name: /send/i }))
    expect(await screen.findByRole('heading', { name: 'Display (1)' })).toBeInTheDocument()
  })

  it('does not render the display panel when cards is empty', async () => {
    mockedApiFetch.mockResolvedValue({
      reply: 'Panel hidden.',
      artifacts: [],
      panel: { cards: [], truncated: false },
    })
    render(<ChatPanel />)
    await user.type(screen.getByRole('textbox'), 'hide panel')
    await user.click(screen.getByRole('button', { name: /send/i }))
    expect(await screen.findByText('Panel hidden.')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: /Display \(/ })).toBeNull()
  })

  it('handles reply, inline artifacts, and panel cards together', async () => {
    mockedApiFetch.mockResolvedValue({
      reply: 'One inline, one in the panel.',
      artifacts: [displayCard('inline-1', 'Pikachu')],
      panel: { cards: [displayCard('panel-1')], truncated: false },
    })
    render(<ChatPanel />)
    await user.type(screen.getByRole('textbox'), 'show both')
    await user.click(screen.getByRole('button', { name: /send/i }))
    expect(await screen.findByText('One inline, one in the panel.')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Pikachu' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Display (1)' })).toBeInTheDocument()
  })

  it('clears local panel IDs after the user closes the panel', async () => {
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
    render(<ChatPanel />)
    const box = screen.getByRole('textbox')
    await user.type(box, 'open')
    await user.click(screen.getByRole('button', { name: /send/i }))
    await user.click(await screen.findByRole('button', { name: 'Close' }))
    await user.type(box, 'next')
    await user.click(screen.getByRole('button', { name: /send/i }))

    const body = JSON.parse(
      String((mockedApiFetch.mock.lastCall![1] as RequestInit).body),
    ) as { panel_item_ids?: string[] }
    expect(body.panel_item_ids).toEqual([])
  })

  it('preserves multi-turn add, remove, and close state transitions', async () => {
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
      .mockResolvedValueOnce({
        reply: 'Closed.',
        artifacts: [],
        panel: { cards: [], truncated: false },
      })
    render(<ChatPanel />)
    const box = screen.getByRole('textbox')

    const turns = [
      ['add three', 'Added three.'],
      ['remove second', 'Removed one.'],
      ['close panel', 'Closed.'],
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
    expect(bodies[2].panel_item_ids).toEqual(['item-1', 'item-3'])
    expect(screen.queryByRole('heading', { name: /Display \(/ })).toBeNull()
  })

  it('ignores a model-authored fullscreen field until the user clicks fullscreen', async () => {
    mockedApiFetch.mockResolvedValue({
      reply: 'Panel open.',
      artifacts: [],
      panel: {
        cards: [displayCard('item-1')],
        truncated: false,
        fullscreen: true,
      },
    })
    render(<ChatPanel />)
    await user.type(screen.getByRole('textbox'), 'open panel')
    await user.click(screen.getByRole('button', { name: /send/i }))
    expect(await screen.findByRole('button', { name: 'Fullscreen' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Dock' })).toBeNull()
  })
})