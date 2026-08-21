'use client'

import { useState } from 'react'
import { useSession } from 'next-auth/react'
import { Send } from 'lucide-react'
import { ApiError } from '@/lib/api'
import {
  sendChat,
  type ChatMessage,
  type DisplayedCard,
  type DisplayPanelState,
} from '@/lib/inventory'
import { CardPresentation } from './CardPresentation'
import { DisplayPanel } from './DisplayPanel'
import MarkdownMessage from './MarkdownMessage'

type Bubble = {
  role: 'user' | 'assistant' | 'error'
  content: string
  artifacts?: DisplayedCard[]
}

const GENERIC_ERROR = 'Something went wrong. Try asking again.'
const MAX_HISTORY_TURNS = 20
const MAX_TURN_CHARS = 4000
const EMPTY_PANEL: DisplayPanelState = { open: null, cards: [], truncated: false }

/** Build completed, bounded user/assistant exchanges for Bedrock replay. */
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
        { role: 'user', content: question.content.slice(0, MAX_TURN_CHARS) },
        { role: 'assistant', content: answer.content.slice(0, MAX_TURN_CHARS) },
      )
      i++
    }
  }
  return turns.slice(-MAX_HISTORY_TURNS)
}

function artifactTitle(card: DisplayedCard): string {
  return card.display_name || card.card?.name || 'Unknown card'
}

function artifactCondition(card: DisplayedCard): string {
  if (card.condition) return card.condition
  if (card.kind === 'graded') {
    if (card.grade_label) return card.grade_label
    const slabGrade = [card.company, card.grade].filter(Boolean).join(' ')
    if (slabGrade) return slabGrade
  }
  return card.kind === 'sealed' ? 'Sealed' : 'N/A'
}

export default function ChatPanel() {
  const { data: session } = useSession()
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<Bubble[]>([])
  const [displayPanel, setDisplayPanel] = useState<DisplayPanelState>(EMPTY_PANEL)
  const [sending, setSending] = useState(false)

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault()
    const text = input.trim()
    if (!text || sending) return

    const history = buildHistory(messages)
    // Only stable item IDs round-trip. Every visible field is discarded and
    // re-hydrated by the backend on this request.
    const panelItemIds = displayPanel.cards.map((card) => card.item_id)

    setMessages((prev) => [...prev, { role: 'user', content: text }])
    setInput('')
    setSending(true)
    try {
      const res = await sendChat(text, history, panelItemIds, {
        token: session?.accessToken,
      })
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: res.reply, artifacts: res.artifacts ?? [] },
      ])
      setDisplayPanel(res.panel ?? EMPTY_PANEL)
    } catch (err) {
      const detail = err instanceof ApiError && err.detail ? err.detail : GENERIC_ERROR
      setMessages((prev) => [...prev, { role: 'error', content: detail }])
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="relative">
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

          {messages.map((message, index) => (
            <ChatBubble key={index} bubble={message} />
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
            onChange={(event) => setInput(event.target.value)}
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

      {displayPanel.open === true && (
        <DisplayPanel
          open={displayPanel.open}
          cards={displayPanel.cards}
          truncated={displayPanel.truncated}
          onClose={() =>
            setDisplayPanel({ open: false, cards: [], truncated: false })
          }
        />
      )}
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
    <div className="space-y-3">
      <div className="max-w-[85%] rounded-2xl rounded-bl-sm bg-pine-800 px-4 py-2.5 text-sm text-pine-100">
        <MarkdownMessage content={bubble.content} />
      </div>
      {bubble.artifacts && bubble.artifacts.length > 0 && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {bubble.artifacts.map((card) => (
            <CardPresentation
              key={card.item_id}
              title={artifactTitle(card)}
              imageUrl={card.card?.image_small || undefined}
              setName={card.card?.set_name ?? 'Unknown set'}
              number={card.card?.number}
              conditionLabel={artifactCondition(card)}
              price={card.current_market_value ?? card.listed_price ?? 'Price N/A'}
              isJapanese={card.card?.card_id.startsWith('ja:') ?? false}
            />
          ))}
        </div>
      )}
    </div>
  )
}
