import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

// Keep ApiError real (error-detail rendering depends on instanceof) — mock only apiFetch.
vi.mock('@/lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/api')>()),
  apiFetch: vi.fn(),
}))

import { apiFetch, ApiError } from '@/lib/api'
import ChatPanel from '@/components/inventory/ChatPanel'

const mockedApiFetch = vi.mocked(apiFetch)

beforeEach(() => {
  vi.clearAllMocks()
})

describe('ChatPanel', () => {
  it('sends the message to /chat/ and renders both bubbles', async () => {
    mockedApiFetch.mockResolvedValue({ reply: 'Charizard is about $250.' })
    render(<ChatPanel />)

    await userEvent.type(screen.getByRole('textbox'), 'How much is Charizard?')
    await userEvent.click(screen.getByRole('button', { name: /send/i }))

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

    await userEvent.type(box, 'first question')
    await userEvent.click(screen.getByRole('button', { name: /send/i }))
    expect(await screen.findByText('First answer.')).toBeInTheDocument()

    await userEvent.type(box, 'second question')
    await userEvent.click(screen.getByRole('button', { name: /send/i }))
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

    await userEvent.type(box, 'doomed question')
    await userEvent.click(screen.getByRole('button', { name: /send/i }))
    expect(await screen.findByText(/something went wrong/i)).toBeInTheDocument()

    await userEvent.type(box, 'second question')
    await userEvent.click(screen.getByRole('button', { name: /send/i }))
    expect(await screen.findByText('Recovered.')).toBeInTheDocument()

    expect(mockedApiFetch).toHaveBeenLastCalledWith(
      '/chat/',
      expect.objectContaining({
        body: JSON.stringify({ message: 'second question', history: [] }),
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
      await userEvent.type(box, `question ${i}`)
      await userEvent.click(screen.getByRole('button', { name: /send/i }))
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

    await userEvent.type(box, 'first question')
    await userEvent.click(screen.getByRole('button', { name: /send/i }))

    await userEvent.type(box, 'second question')
    await userEvent.click(screen.getByRole('button', { name: /send/i }))
    expect(await screen.findByText('Real answer.')).toBeInTheDocument()

    expect(mockedApiFetch).toHaveBeenLastCalledWith(
      '/chat/',
      expect.objectContaining({
        body: JSON.stringify({ message: 'second question', history: [] }),
      }),
    )
  })

  it('does not send an empty message', async () => {
    render(<ChatPanel />)
    await userEvent.click(screen.getByRole('button', { name: /send/i }))
    expect(mockedApiFetch).not.toHaveBeenCalled()
  })

  it('shows the backend detail message when the API returns a typed error', async () => {
    mockedApiFetch.mockRejectedValue(
      new ApiError(429, 'Service is temporarily busy — please try again shortly.'),
    )
    render(<ChatPanel />)
    await userEvent.type(screen.getByRole('textbox'), 'hi')
    await userEvent.click(screen.getByRole('button', { name: /send/i }))
    expect(
      await screen.findByText(/temporarily busy/i),
    ).toBeInTheDocument()
  })

  it('shows a generic error bubble when the request fails without detail', async () => {
    mockedApiFetch.mockRejectedValue(new Error('boom'))
    render(<ChatPanel />)
    await userEvent.type(screen.getByRole('textbox'), 'hi')
    await userEvent.click(screen.getByRole('button', { name: /send/i }))
    expect(await screen.findByText(/something went wrong/i)).toBeInTheDocument()
  })

  it('renders markdown formatting in assistant replies', async () => {
    mockedApiFetch.mockResolvedValue({ reply: 'The **Charizard** is from Base Set.' })
    render(<ChatPanel />)

    await userEvent.type(screen.getByRole('textbox'), 'How much is Charizard?')
    await userEvent.click(screen.getByRole('button', { name: /send/i }))

    const strong = await screen.findByText('Charizard')
    expect(strong.tagName).toBe('STRONG')
  })

  it('renders literal asterisks in user bubbles, not markdown', async () => {
    mockedApiFetch.mockResolvedValue({ reply: 'Sure thing.' })
    render(<ChatPanel />)

    await userEvent.type(screen.getByRole('textbox'), 'What about **this** card?')
    await userEvent.click(screen.getByRole('button', { name: /send/i }))

    expect(await screen.findByText('What about **this** card?')).toBeInTheDocument()
  })
})
