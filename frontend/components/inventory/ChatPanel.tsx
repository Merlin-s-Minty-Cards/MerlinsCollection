'use client'

import { useState } from 'react'
import { Send } from 'lucide-react'
import { ApiError } from '@/lib/api'
import { sendChat, type ChatMessage } from '@/lib/inventory'
import MarkdownMessage from '@/components/inventory/MarkdownMessage'

type Bubble = {
  role: 'user' | 'assistant' | 'error'
  content: string
}

const GENERIC_ERROR = 'Something went wrong. Try asking again.'

// The backend caps history at 20 turns (10 exchanges) — send only the newest.
const MAX_HISTORY_TURNS = 20

/**
 * Build the history the backend will replay into Bedrock. Converse demands
 * strict user/assistant alternation starting with a user turn, so only
 * completed exchanges survive: a user bubble immediately answered by a
 * non-empty assistant bubble. Failed or empty turns are dropped, and the
 * result is capped to the newest MAX_HISTORY_TURNS (an even slice of an even
 * list, so alternation is preserved).
 */
function buildHistory(messages: Bubble[]): ChatMessage[] {
  const turns: ChatMessage[] = []
  for (let i = 0; i < messages.length - 1; i++) {
    const question = messages[i]
    const answer = messages[i + 1]
    if (
      question.role === 'user' &&
      answer.role === 'assistant' &&
      question.content !== '' &&
      answer.content !== ''
    ) {
      turns.push(
        { role: 'user', content: question.content },
        { role: 'assistant', content: answer.content },
      )
      i++ // consume the pair
    }
  }
  return turns.slice(-MAX_HISTORY_TURNS)
}

export default function ChatPanel() {
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<Bubble[]>([])
  const [sending, setSending] = useState(false)

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault()
    const text = input.trim()
    if (!text || sending) return

    // Prior turns travel with the request — the backend replays them into the
    // Bedrock conversation so follow-up questions keep their context.
    const history = buildHistory(messages)

    setMessages((prev) => [...prev, { role: 'user', content: text }])
    setInput('')
    setSending(true)
    try {
      const res = await sendChat(text, history)
      setMessages((prev) => [...prev, { role: 'assistant', content: res.reply }])
    } catch (err) {
      // The backend sends actionable detail for 429/503/422 — show it.
      const detail = err instanceof ApiError && err.detail ? err.detail : GENERIC_ERROR
      setMessages((prev) => [...prev, { role: 'error', content: detail }])
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="flex h-[560px] flex-col rounded-2xl vault-panel">
      <div
        className="vault-scroll flex-1 space-y-4 overflow-y-auto p-4 sm:p-5"
        aria-live="polite"
        aria-atomic="false"
      >
        {messages.length === 0 && (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <p className="text-pine-100">Ask Merlin about the collection</p>
            <p className="mt-1 max-w-[42ch] text-sm text-pine-300">
              Try “What Charizards do you have under $300?” or “Show me holo cards from Base
              set.”
            </p>
          </div>
        )}

        {messages.map((m, i) => (
          <ChatBubble key={i} bubble={m} />
        ))}

        {sending && (
          <p className="font-mono text-xs text-mint" aria-live="polite">
            Merlin is thinking…
          </p>
        )}
      </div>

      <form
        onSubmit={onSubmit}
        className="flex items-center gap-2 border-t border-pine-700 p-3"
      >
        <input
          type="text"
          aria-label="Message"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about a card, set, or price…"
          disabled={sending}
          className="vault-field flex-1 rounded-lg px-3 py-2.5 text-sm disabled:opacity-60"
        />
        <button
          type="submit"
          disabled={sending}
          className="flex items-center gap-2 rounded-lg bg-mint px-4 py-2.5 text-sm font-semibold text-pine-950 transition-colors hover:bg-mint-soft disabled:cursor-not-allowed disabled:opacity-60"
        >
          <Send size={16} aria-hidden />
          Send
        </button>
      </form>
    </div>
  )
}

function ChatBubble({ bubble }: { bubble: Bubble }) {
  if (bubble.role === 'user') {
    return (
      <div className="flex justify-end">
        <p className="max-w-[80%] rounded-2xl rounded-br-sm bg-mint px-4 py-2.5 text-sm text-pine-950">
          {bubble.content}
        </p>
      </div>
    )
  }
  if (bubble.role === 'error') {
    return (
      <p className="max-w-[85%] rounded-2xl rounded-bl-sm bg-red-500/10 px-4 py-2.5 text-sm text-red-300">
        {bubble.content}
      </p>
    )
  }
  return (
    <div className="max-w-[85%] rounded-2xl rounded-bl-sm bg-pine-800 px-4 py-2.5 text-sm text-pine-100">
      <MarkdownMessage content={bubble.content} />
    </div>
  )
}
