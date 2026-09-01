'use client'

import { useCallback, useEffect, useRef, useState, type RefObject } from 'react'
import { createPortal } from 'react-dom'
import { useSession } from 'next-auth/react'
import { MessageSquare, Send, X } from 'lucide-react'
import { ApiError } from '@/lib/api'
import { adminConversations, sendAdminChat } from '@/lib/admin-conversations'
import { displayedCardToPresentedCard, type DisplayedCard } from '@/lib/inventory'
import { CARD_GRID_CLASS, CardPresentation } from '../inventory/CardPresentation'
import HistoryMenu from '../inventory/HistoryMenu'
import MarkdownMessage from '../inventory/MarkdownMessage'

/**
 * The admin analyst chat (RFC 0018) — a SIDE PANEL, not a route.
 *
 * Owner decision 2: the tab underneath stays mounted and visible, because the
 * questions worth asking are about the rows you are looking at, and a route
 * makes you leave them. Nothing here unmounts or navigates.
 *
 * Open Question 1: card results render INLINE, as a compact grid inside this
 * panel — the answer and its evidence stay together, and no admin tab has to
 * learn how to accept a pushed row set.
 *
 * **It PUSHES the content pane rather than overlaying it** (owner report
 * 2026-08-28: "the sidebar overlaps the existing tab, when it should reduce
 * the width of the tab... with no overlap"). That requires the panel to take
 * real layout space in the SAME flex row as `<main>` — a `position: fixed`
 * overlay cannot do that by definition, it is removed from flow entirely. So
 * this portals into `slotRef` (a node `AdminShell` renders as a flex sibling
 * of `<main>`, not into `document.body`), and the panel itself is ordinary
 * flow content, not `fixed`.
 *
 * Two things keep that safe on a phone, where there is no room to push:
 *   1. width is `min(<configured>, 100vw)`, so the panel can never demand
 *      more than the screen has — on a narrow phone this degrades to
 *      exactly 100vw, `<main>` shrinks to 0 (via its own `min-w-0`), and the
 *      visible result is indistinguishable from the old full-screen overlay;
 *   2. `pb-20 md:pb-0` mirrors the exact classes `<main>` already carries to
 *      clear the `fixed`, always-on-top mobile bottom nav — a NORMAL-FLOW
 *      element has no way to out-rank a positioned sibling by z-index, so the
 *      composer is kept clear by reserving space above the nav's band rather
 *      than by trying to win a stacking fight it structurally cannot win.
 *
 * This also RETIRES the `backdrop-blur` containing-block trap the panel used
 * to be portalled around (roadmap item 9b) — that trap is specific to
 * `position: fixed` descendants, and a normal-flow sibling is not one.
 */

type Bubble = {
  role: 'user' | 'assistant' | 'error'
  content: string
  artifacts?: DisplayedCard[]
}

const MIN_WIDTH = 380
const MAX_WIDTH = 900
const DEFAULT_WIDTH = 480
const KEYBOARD_STEP = 20
const WIDTH_KEY = 'merlins.adminChat.width'

const GENERIC_ERROR = 'Something went wrong. Try asking again.'
const MISSING_THREAD_ERROR = 'That conversation is no longer available. Starting a new one.'

const clampWidth = (w: number) => Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, w))

/** Read the remembered width. Never throws — a private window has no storage. */
function storedWidth(): number {
  try {
    const raw = window.localStorage.getItem(WIDTH_KEY)
    const parsed = raw === null ? NaN : Number(raw)
    return Number.isFinite(parsed) ? clampWidth(parsed) : DEFAULT_WIDTH
  } catch {
    return DEFAULT_WIDTH
  }
}

export interface AdminChatProps {
  /**
   * Where the panel portals into — a node `AdminShell` renders as a flex
   * sibling of `<main>`, so the panel takes real layout space there instead
   * of overlaying the page from `document.body`. Optional so a standalone
   * render (a test with no `AdminShell`) still works: falls back to
   * `document.body`, the old behaviour, purely as a defensive default —
   * production always provides a real slot.
   */
  slotRef?: RefObject<HTMLDivElement | null>
}

export default function AdminChat({ slotRef }: AdminChatProps = {}) {
  const { data: session } = useSession()
  const token = session?.accessToken

  const [open, setOpen] = useState(false)
  // `createPortal` needs a real `document`, which does not exist during SSR or
  // the first hydration pass. Gate on a mount-only flag rather than on
  // `typeof window`: a render that disagrees with the server's markup is a
  // hydration error, and this component ships on every admin page.
  const [mounted, setMounted] = useState(false)
  const [width, setWidth] = useState(DEFAULT_WIDTH)
  const [messages, setMessages] = useState<Bubble[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [conversationId, setConversationId] = useState<string | null>(null)
  const dragStart = useRef<{ x: number; width: number } | null>(null)

  // Restored on mount rather than in useState's initializer: this component
  // renders on the server too, and localStorage does not exist there.
  useEffect(() => {
    setWidth(storedWidth())
    setMounted(true)
  }, [])

  useEffect(() => {
    try {
      window.localStorage.setItem(WIDTH_KEY, String(width))
    } catch {
      // A viewer with site data blocked simply does not get a remembered width.
    }
  }, [width])

  // Escape closes the whole panel. `HistoryMenu` closes its own flyout on its
  // own Escape listener first (registered later, while it is open) — pressing
  // Escape with the history flyout open now closes both in one press rather
  // than the flyout alone, a deliberate simplification: HistoryMenu owns its
  // open state internally, so this component has no state left to check
  // before deciding whether to act.
  useEffect(() => {
    if (!open) return
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open])

  // Drag-to-resize. The panel is anchored to the RIGHT edge, so moving the
  // handle left makes it wider — hence the negated delta.
  useEffect(() => {
    function onMove(event: MouseEvent) {
      if (!dragStart.current) return
      const delta = dragStart.current.x - event.clientX
      setWidth(clampWidth(dragStart.current.width + delta))
    }
    function onUp() {
      if (!dragStart.current) return
      dragStart.current = null
      document.body.style.userSelect = ''
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
      document.body.style.userSelect = ''
    }
  }, [])

  const onHandleKeyDown = useCallback((event: React.KeyboardEvent) => {
    // Right-anchored: ArrowLeft widens. Same ARIA window-splitter contract as
    // SplitWorkspace's handle — focusable, arrow-operable, reports its value.
    const step =
      event.key === 'ArrowLeft' ? KEYBOARD_STEP
        : event.key === 'ArrowRight' ? -KEYBOARD_STEP
          : 0
    if (step !== 0) {
      event.preventDefault()
      setWidth((w) => clampWidth(w + step))
      return
    }
    if (event.key === 'Home') {
      event.preventDefault()
      setWidth(MIN_WIDTH)
    } else if (event.key === 'End') {
      event.preventDefault()
      setWidth(MAX_WIDTH)
    }
  }, [])

  async function ask() {
    const text = input.trim()
    if (!text || busy) return
    setInput('')
    setMessages((prev) => [...prev, { role: 'user', content: text }])
    setBusy(true)
    try {
      const res = await sendAdminChat(
        text,
        conversationId ? { conversationId } : {},
        { token },
      )
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: res.reply, artifacts: res.artifacts ?? [] },
      ])
      if (res.conversation_id) setConversationId(res.conversation_id)
    } catch (err) {
      // A 404 means the thread is gone — deleted elsewhere, TTL-expired, or
      // never actually written (the backend returns a conversation_id even when
      // persistence failed, because Bedrock was already billed). HOLDING the id
      // would 404 every later message forever, recoverable only by a reload.
      if (err instanceof ApiError && err.status === 404) {
        setConversationId(null)
        setMessages((prev) => [...prev, { role: 'error', content: MISSING_THREAD_ERROR }])
      } else {
        const detail = err instanceof ApiError ? err.detail ?? GENERIC_ERROR : GENERIC_ERROR
        setMessages((prev) => [...prev, { role: 'error', content: detail }])
      }
    } finally {
      setBusy(false)
    }
  }

  async function openThread(id: string) {
    try {
      const detail = await adminConversations.get(id, { token })
      setConversationId(detail.conversation_id)
      setMessages(
        detail.messages.map((m) => ({
          role: m.role,
          content: m.content,
          artifacts: m.artifacts,
        })),
      )
    } catch {
      setMessages((prev) => [...prev, { role: 'error', content: MISSING_THREAD_ERROR }])
    }
  }

  function newThread() {
    setConversationId(null)
    setMessages([])
    setInput('')
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        aria-label="Analyst chat"
        aria-expanded={open}
        className="flex items-center gap-1.5 rounded-md px-2.5 py-2 text-sm font-medium text-pine-300 transition-colors hover:bg-pine-800 hover:text-mint focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-mint"
      >
        <MessageSquare size={16} aria-hidden />
        <span className="hidden sm:inline">Analyst</span>
      </button>

      {/* Portals into `slotRef` — a flex sibling of `<main>` that AdminShell
          renders, not `document.body`. See the file header comment for why:
          this is what makes opening the panel shrink `<main>` instead of
          drawing over it, and it is also what retires the old backdrop-blur
          containing-block trap (roadmap item 9b) — that trap only affects
          `position: fixed` descendants, and this is ordinary flow content. */}
      {open && mounted && createPortal(
        <div
          role="dialog"
          aria-label="Analyst chat"
          // `min(..., 100vw)`, not a bare pixel value: the panel can never
          // demand more than the screen has. On a phone this collapses to
          // exactly 100vw — <main> shrinks to 0 via its own `min-w-0` and the
          // visible result matches the old full-screen overlay.
          style={{ width: `min(${width}px, 100vw)` }}
          // `relative`, not `fixed`: this is ordinary flow content now, so the
          // resize handle's `absolute` needs a positioning context of its own.
          // `pb-20 md:pb-0` mirrors <main>'s own classes for the exact same
          // reason — clearing the fixed, always-on-top mobile bottom nav by
          // reserving space above its band, since normal-flow content has no
          // way to out-rank a positioned sibling by z-index.
          className="vault-scope relative flex h-full flex-col border-l border-pine-700 bg-pine-950 pb-20 shadow-2xl md:pb-0"
        >
          <div
            role="separator"
            aria-label="Resize analyst panel"
            aria-orientation="vertical"
            aria-valuenow={width}
            aria-valuemin={MIN_WIDTH}
            aria-valuemax={MAX_WIDTH}
            tabIndex={0}
            onMouseDown={(e) => {
              dragStart.current = { x: e.clientX, width }
              document.body.style.userSelect = 'none'
            }}
            onKeyDown={onHandleKeyDown}
            className="absolute left-0 top-0 h-full w-1.5 cursor-col-resize bg-pine-700 transition-colors hover:bg-mint/40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-mint"
          />

          <header className="flex items-center justify-between gap-2 border-b border-pine-700 px-4 py-3 pl-6">
            <h2 className="font-serif text-lg text-pine-100">Analyst</h2>
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={newThread}
                className="rounded-md px-2 py-1.5 text-sm text-pine-300 hover:bg-pine-800 hover:text-mint"
              >
                New
              </button>
              {/* Reused, not reimplemented — same component the customer
                  chat uses (RFC 0017), just pointed at the admin client. Gets
                  click-outside-to-close, last-edited date, rename, delete and
                  search for free instead of a second, thinner copy of all
                  five (owner report 2026-08-28). */}
              <HistoryMenu
                client={adminConversations}
                activeConversationId={conversationId}
                onSelect={(id) => void openThread(id)}
                onRemoved={(removed) => {
                  if (removed === 'all' || removed === conversationId) newThread()
                }}
              />
              <button
                type="button"
                onClick={() => setOpen(false)}
                aria-label="Close analyst chat"
                className="rounded-md p-2 text-pine-300 hover:bg-pine-800 hover:text-mint"
              >
                <X size={16} aria-hidden />
              </button>
            </div>
          </header>

          <div className="vault-scroll flex-1 space-y-4 overflow-y-auto px-4 py-4 pl-6">
            {messages.length === 0 && (
              <div className="pt-10 text-center">
                <p className="font-medium text-pine-100">Ask about your numbers</p>
                <p className="mt-1 text-sm text-pine-300">
                  Try &ldquo;what did I net at Portland?&rdquo; or &ldquo;what&rsquo;s been
                  sitting longest over $100?&rdquo;
                </p>
              </div>
            )}
            {messages.map((m, i) => (
              <div key={i}>
                {m.role === 'user' ? (
                  <p className="ml-auto max-w-[85%] rounded-2xl bg-pine-800 px-3 py-2 text-sm text-pine-100">
                    {m.content}
                  </p>
                ) : m.role === 'error' ? (
                  <p className="text-sm text-red-300">{m.content}</p>
                ) : (
                  <div className="max-w-full text-sm text-pine-200">
                    <MarkdownMessage content={m.content} />
                    {m.artifacts && m.artifacts.length > 0 && (
                      <div className={`mt-3 ${CARD_GRID_CLASS}`}>
                        {m.artifacts.map((card) => {
                          // Destructured rather than spread whole: the mapper
                          // returns a `key` field, and React warns (correctly)
                          // when a key arrives via spread instead of directly.
                          const { key, ...presented } = displayedCardToPresentedCard(card)
                          return <CardPresentation key={key} {...presented} />
                        })}
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>

          <form
            onSubmit={(e) => {
              e.preventDefault()
              void ask()
            }}
            className="flex items-center gap-2 border-t border-pine-700 px-4 py-3 pl-6"
          >
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              aria-label="Ask the analyst"
              placeholder="Ask about profit, aging stock, consignors…"
              className="vault-field min-w-0 flex-1 rounded-lg px-3 py-2 text-sm"
            />
            <button
              type="submit"
              disabled={busy}
              className="flex items-center gap-1.5 rounded-lg bg-mint/15 px-3 py-2 text-sm font-medium text-mint disabled:opacity-50"
            >
              <Send size={14} aria-hidden />
              Send
            </button>
          </form>
        </div>,
        slotRef?.current ?? document.body,
      )}
    </>
  )
}
