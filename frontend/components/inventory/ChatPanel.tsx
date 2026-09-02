'use client'

import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react'
import { useSession } from 'next-auth/react'
import { Send } from 'lucide-react'
import { ApiError } from '@/lib/api'
import {
  sendChat,
  displayedCardToPresentedCard,
  type DisplayedCard,
  type DisplayPanelState,
} from '@/lib/inventory'
import { getConversation } from '@/lib/conversations'
import { CARD_GRID_CLASS, CardPresentation } from './CardPresentation'
import type { ResultsView } from './ResultsPane'
import MarkdownMessage from './MarkdownMessage'

type Bubble = {
  role: 'user' | 'assistant' | 'error'
  content: string
  artifacts?: DisplayedCard[]
}

const GENERIC_ERROR = 'Something went wrong. Try asking again.'
const MISSING_THREAD_ERROR =
  'That conversation is no longer available. Starting a new one.'
const EMPTY_PANEL: DisplayPanelState = { cards: [], truncated: false }
const EMPTY_DISPLAY_MESSAGE = 'No cards in the display yet.'
const TRUNCATED_NOTICE = 'Limited to 50 cards. Some results are not shown.'

/** Build the shared right-pane view from the chat's own display-panel state. */
function toDisplayView(panel: DisplayPanelState): ResultsView {
  return {
    headerLabel: `Display (${panel.cards.length}${panel.truncated ? '+' : ''})`,
    cards: panel.cards.map(displayedCardToPresentedCard),
    status: 'success',
    emptyMessage: EMPTY_DISPLAY_MESSAGE,
    truncatedNotice: panel.truncated ? TRUNCATED_NOTICE : undefined,
  }
}

export interface ChatPanelProps {
  /**
   * RFC 0019: ChatPanel no longer renders its own display panel — it shares
   * one ResultsPane with filter mode. This fires whenever the set of
   * currently-displayed cards changes, carrying a normalized view for that
   * shared pane.
   */
  onDisplayChange?: (view: ResultsView) => void
  /**
   * RFC 0017: fires whenever the thread this panel is in changes — a new
   * thread's server-assigned id, a resumed one, or null after reset(). Lets
   * the header highlight the open thread and notice when it is deleted.
   */
  onConversationChange?: (conversationId: string | null) => void
}

export interface ChatPanelHandle {
  /** Clears the transcript, input, and display state — a fresh conversation. */
  reset: () => void
  /**
   * Clears only the "pinned" display cards (what round-trips as
   * `panel_item_ids` on the next turn), leaving the transcript untouched.
   * Used by the shared ResultsPane's "Clear display" control in chat mode.
   */
  clearDisplay: () => void
  /**
   * Opens a stored thread: replaces the transcript, the display panel and the
   * live thread id with that conversation's. Never rejects — a thread deleted
   * in another tab or aged out by the TTL is a routine 404, surfaced in the
   * transcript rather than thrown at the caller.
   */
  loadConversation: (conversationId: string) => Promise<void>
}

const ChatPanel = forwardRef<ChatPanelHandle, ChatPanelProps>(function ChatPanel(
  { onDisplayChange, onConversationChange },
  ref,
) {
  const { data: session } = useSession()
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<Bubble[]>([])
  const [displayPanel, setDisplayPanel] = useState<DisplayPanelState>(EMPTY_PANEL)
  const [sending, setSending] = useState(false)
  // RFC 0017: the thread this panel is currently in. null means the next
  // message opens a new one, which the backend creates implicitly.
  const [conversationId, setConversationId] = useState<string | null>(null)
  // Monotonic id (same pattern as FilterPanel's requestId): bumped by both a
  // new send AND reset(), so a reply that resolves after either can never
  // write into a conversation it no longer belongs to. Without this, calling
  // the new reset() while a request is in flight let a stale reply reappear
  // in an otherwise-fresh, supposedly-empty conversation once it resolved.
  const requestId = useRef(0)

  // Push the current display state to the shared right-pane ResultsPane
  // whenever it changes — this is the ONLY place it reaches the DOM now;
  // ChatPanel itself never renders a card grid for it.
  useEffect(() => {
    onDisplayChange?.(toDisplayView(displayPanel))
    // onDisplayChange is intentionally omitted — see FilterPanel's identical
    // reasoning for onResultsChange.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [displayPanel])

  useEffect(() => {
    onConversationChange?.(conversationId)
    // onConversationChange is intentionally omitted — same reasoning as
    // onDisplayChange above.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId])

  useImperativeHandle(ref, () => ({
    reset: () => {
      requestId.current++
      setMessages([])
      setInput('')
      setDisplayPanel(EMPTY_PANEL)
      setConversationId(null)
    },
    clearDisplay: () => {
      setDisplayPanel(EMPTY_PANEL)
    },
    loadConversation: async (id: string) => {
      const requestNumber = ++requestId.current
      try {
        const detail = await getConversation(id, { token: session?.accessToken })
        if (requestNumber !== requestId.current) return
        // Replaced together, past the guard. Setting the thread id apart from
        // the transcript would leave the panel showing one thread while the
        // next message appends to another.
        setMessages(
          detail.messages.map((message) => ({
            role: message.role,
            content: message.content,
            artifacts: message.artifacts ?? [],
          })),
        )
        setDisplayPanel(detail.panel ?? EMPTY_PANEL)
        setConversationId(detail.conversation_id)
        setInput('')
      } catch (err) {
        if (requestNumber !== requestId.current) return
        // Routine, not exceptional: deleted in another tab, or TTL-expired.
        // The current thread is left exactly as it was.
        const detail =
          err instanceof ApiError && err.status === 404
            ? MISSING_THREAD_ERROR
            : err instanceof ApiError && err.detail
              ? err.detail
              : GENERIC_ERROR
        setMessages((prev) => [...prev, { role: 'error', content: detail }])
      }
    },
  }))

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault()
    const text = input.trim()
    if (!text || sending) return

    const id = ++requestId.current
    // Only stable item IDs round-trip. Every visible field is discarded and
    // re-hydrated by the backend on this request.
    const panelItemIds = displayPanel.cards.map((card) => card.item_id)

    setMessages((prev) => [...prev, { role: 'user', content: text }])
    setInput('')
    setSending(true)
    try {
      const res = await sendChat(
        text,
        { conversationId, panelItemIds },
        { token: session?.accessToken },
      )
      if (id !== requestId.current) return
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: res.reply, artifacts: res.artifacts ?? [] },
      ])
      setDisplayPanel(res.panel ?? EMPTY_PANEL)
      if (res.conversation_id) setConversationId(res.conversation_id)
    } catch (err) {
      if (id !== requestId.current) return
      // A 404 means this thread is gone — either deleted elsewhere, or never
      // actually persisted: the backend returns a well-formed conversation_id
      // even when the write that would have created the thread failed, because
      // it refuses to discard a paid-for Bedrock reply. Holding that id would
      // 404 every subsequent message forever, so it is dropped here and the
      // next message opens a fresh thread.
      const missingThread = err instanceof ApiError && err.status === 404
      if (missingThread) setConversationId(null)
      const detail = missingThread
        ? MISSING_THREAD_ERROR
        : err instanceof ApiError && err.detail
          ? err.detail
          : GENERIC_ERROR
      setMessages((prev) => [...prev, { role: 'error', content: detail }])
    } finally {
      // Always clears `sending`, even for a stale request — reset() doesn't
      // touch it, so without this a reset while a request is in flight would
      // leave the fresh conversation's input disabled until the browser tab
      // is reloaded.
      setSending(false)
    }
  }

  return (
    <div className="flex h-full flex-col rounded-2xl vault-panel">
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
  )
})

export default ChatPanel

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
        // Shared CARD_GRID_CLASS so an inline chat card is the same size as
        // one in the shared results pane — a single card used to span most
        // of the chat pane's width (owner report, 2026-08-25). Mapped through
        // displayedCardToPresentedCard (RFC 0019), the same shared helper the
        // right-pane display view uses — no more parallel title/condition
        // logic for the same DisplayedCard shape.
        <div className={`max-w-[85%] ${CARD_GRID_CLASS}`}>
          {bubble.artifacts.map(displayedCardToPresentedCard).map((card) => (
            <CardPresentation
              key={card.key}
              title={card.title}
              imageUrl={card.imageUrl}
              setName={card.setName}
              number={card.number}
              conditionLabel={card.conditionLabel}
              price={card.price}
              isJapanese={card.isJapanese}
            />
          ))}
        </div>
      )}
    </div>
  )
}
