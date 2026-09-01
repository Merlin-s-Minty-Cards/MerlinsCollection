'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { useSession } from 'next-auth/react'
import { Check, History, Pencil, Search, Trash2, X } from 'lucide-react'
import { ApiError } from '@/lib/api'
import {
  customerConversations,
  type ConversationsClient,
  type ConversationSummary,
} from '@/lib/conversations'
import { formatTimestamp } from '@/lib/dates'

/**
 * Icon-only control (lucide's `History` icon — never an emoji) opening an
 * anchored flyout of past conversations. RFC 0017 turned this from an honest
 * empty state into the real list.
 *
 * **The list is fetched on OPEN, never once on mount.** Two reasons, and the
 * first is a bug this repo has already paid for: a `useEffect(..., [])` fetch
 * can fire while NextAuth's client session is still `loading`, get a 401,
 * swallow it into an empty list, and — having no dependency to re-run on —
 * stay empty for the life of the page (CLAUDE.md, "A FETCH-ONCE ADMIN
 * DROPDOWN HOOK CAN LOSE THE SESSION RACE"). Fetching on open sidesteps the
 * race entirely rather than guarding against it. Second, a thread's title and
 * ordering change every time the user sends a message, so a list cached at
 * mount is stale by the time anyone opens it.
 */

export interface HistoryMenuProps {
  /** Open a thread. */
  onSelect?: (conversationId: string) => void
  /** The thread currently open in the chat, highlighted in the list. */
  activeConversationId?: string | null
  /**
   * Fires when threads are destroyed — one id, or `'all'`. Lets the parent
   * clear the chat if what it was showing no longer exists.
   */
  onRemoved?: (removed: string | 'all') => void
  /**
   * Which surface's conversation routes to read and write. Defaults to the
   * customer surface (`/chat/conversations`) so every pre-existing caller is
   * unaffected. The admin analyst chat (RFC 0018) passes `adminConversations`
   * here instead of hand-rolling its own dropdown — same contract, same
   * ownership rules, just a different base path (`lib/admin-conversations.ts`).
   */
  client?: ConversationsClient
}

const EMPTY_MESSAGE = 'No past conversations yet'
const NO_MATCHES_MESSAGE = 'No conversations match your search'
const LOAD_ERROR = 'Could not load conversations.'

export default function HistoryMenu({
  onSelect,
  activeConversationId,
  onRemoved,
  client = customerConversations,
}: HistoryMenuProps = {}) {
  const { data: session } = useSession()
  const [open, setOpen] = useState(false)
  const [conversations, setConversations] = useState<ConversationSummary[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Which row is mid-rename, and the draft title for it.
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [draftTitle, setDraftTitle] = useState('')
  // Destructive actions confirm in place rather than through window.confirm,
  // which a flyout cannot style and a test cannot read.
  const [confirmingDeleteId, setConfirmingDeleteId] = useState<string | null>(null)
  const [confirmingClearAll, setConfirmingClearAll] = useState(false)
  const [query, setQuery] = useState('')
  const rootRef = useRef<HTMLDivElement>(null)

  const token = session?.accessToken

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setConversations(await client.list({ token }))
    } catch {
      setError(LOAD_ERROR)
    } finally {
      setLoading(false)
    }
  }, [token, client])

  const filtered = conversations.filter((c) =>
    c.title.toLowerCase().includes(query.trim().toLowerCase()),
  )

  useEffect(() => {
    if (!open) return
    void refresh()
  }, [open, refresh])

  useEffect(() => {
    if (!open) return

    function onPointerDown(event: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false)
      }
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') setOpen(false)
    }

    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  // Every transient sub-state belongs to one opening of the flyout — the
  // search query too, so reopening always starts from the full list rather
  // than silently carrying over a filter from three questions ago.
  useEffect(() => {
    if (open) return
    setRenamingId(null)
    setConfirmingDeleteId(null)
    setConfirmingClearAll(false)
    setQuery('')
  }, [open])

  async function commitRename(conversationId: string) {
    const title = draftTitle.trim()
    setRenamingId(null)
    if (!title) return
    // Optimistic: the row is already on screen and the server's only answer is
    // the same title back.
    setConversations((prev) =>
      prev.map((c) => (c.conversation_id === conversationId ? { ...c, title } : c)),
    )
    try {
      await client.rename(conversationId, title, { token })
    } catch {
      await refresh()
    }
  }

  async function confirmDelete(conversationId: string) {
    setConfirmingDeleteId(null)
    setConversations((prev) => prev.filter((c) => c.conversation_id !== conversationId))
    try {
      await client.remove(conversationId, { token })
    } catch (err) {
      // A 404 means it was already gone — the row is correctly removed either
      // way, so only a real failure is worth re-syncing over.
      if (!(err instanceof ApiError && err.status === 404)) {
        await refresh()
        // The thread survived, so the row comes back and the parent must NOT
        // be told it vanished — telling it here would reset a chat whose
        // thread is still very much alive.
        return
      }
    }
    onRemoved?.(conversationId)
  }

  async function confirmClearAll() {
    setConfirmingClearAll(false)
    setConversations([])
    try {
      await client.clear({ token })
    } catch {
      // Same rule as the single delete: nothing was destroyed, so the list is
      // restored and the parent is not told to clear anything.
      await refresh()
      return
    }
    onRemoved?.('all')
  }

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        aria-label="Conversation history"
        aria-expanded={open}
        className="rounded-md p-2 text-pine-300 transition-colors hover:bg-pine-800 hover:text-mint focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-mint"
      >
        <History size={16} aria-hidden />
      </button>

      {open && (
        // w-80, not w-64: a title plus two actions truncates to uselessness at
        // the narrower width.
        <div className="absolute right-0 top-full z-20 mt-2 w-80 rounded-xl border border-pine-700 bg-pine-900 p-2 shadow-2xl">
          {loading && <p className="p-2 text-sm text-pine-300">Loading…</p>}
          {!loading && error && <p className="p-2 text-sm text-red-300">{error}</p>}
          {!loading && !error && conversations.length === 0 && (
            <p className="p-2 text-sm text-pine-300">{EMPTY_MESSAGE}</p>
          )}

          {!loading && !error && conversations.length > 0 && (
            <div className="relative mb-1 px-1 pt-1">
              <Search
                size={14}
                aria-hidden
                className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-pine-400"
              />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                aria-label="Search conversations"
                placeholder="Search conversations…"
                className="w-full rounded-md border border-pine-700 bg-pine-950 py-1.5 pl-8 pr-2 text-sm text-pine-100 placeholder:text-pine-500 focus:outline-none focus:ring-1 focus:ring-mint"
              />
            </div>
          )}

          {!loading && !error && conversations.length > 0 && filtered.length === 0 && (
            <p className="p-2 text-sm text-pine-300">{NO_MATCHES_MESSAGE}</p>
          )}

          {!loading && !error && filtered.length > 0 && (
            <ul className="vault-scroll max-h-80 space-y-0.5 overflow-y-auto">
              {filtered.map((conversation) => {
                const id = conversation.conversation_id
                const isActive = id === activeConversationId
                return (
                  <li key={id} className="group relative rounded-lg">
                    {renamingId === id ? (
                      <form
                        className="flex items-center gap-1 p-1"
                        onSubmit={(event) => {
                          event.preventDefault()
                          void commitRename(id)
                        }}
                      >
                        <input
                          autoFocus
                          value={draftTitle}
                          aria-label="Conversation title"
                          onChange={(event) => setDraftTitle(event.target.value)}
                          onKeyDown={(event) => {
                            if (event.key !== 'Escape') return
                            // Escape cancels the RENAME, not the flyout. Without
                            // stopping it here the key reaches the document
                            // listener above and shuts the whole menu, throwing
                            // the user out of a list they were editing. A second
                            // Escape, with no rename in progress, still closes.
                            event.stopPropagation()
                            setRenamingId(null)
                          }}
                          className="min-w-0 flex-1 rounded-md border border-pine-700 bg-pine-950 px-2 py-1 text-sm text-pine-100 focus:outline-none focus:ring-1 focus:ring-mint"
                        />
                        <button
                          type="submit"
                          aria-label="Save title"
                          className="rounded-md p-1 text-pine-300 hover:text-mint"
                        >
                          <Check size={14} aria-hidden />
                        </button>
                        <button
                          type="button"
                          aria-label="Cancel rename"
                          onClick={() => setRenamingId(null)}
                          className="rounded-md p-1 text-pine-300 hover:text-mint"
                        >
                          <X size={14} aria-hidden />
                        </button>
                      </form>
                    ) : confirmingDeleteId === id ? (
                      <div className="flex items-center gap-2 p-2">
                        <span className="min-w-0 flex-1 truncate text-sm text-pine-100">
                          Delete this conversation?
                        </span>
                        <button
                          type="button"
                          onClick={() => void confirmDelete(id)}
                          className="rounded-md px-2 py-1 text-xs font-medium text-red-300 hover:bg-red-500/10"
                        >
                          Delete
                        </button>
                        <button
                          type="button"
                          onClick={() => setConfirmingDeleteId(null)}
                          className="rounded-md px-2 py-1 text-xs text-pine-300 hover:text-mint"
                        >
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <div className="flex items-center">
                        <button
                          type="button"
                          onClick={() => {
                            onSelect?.(id)
                            setOpen(false)
                          }}
                          aria-current={isActive ? 'true' : undefined}
                          className={`min-w-0 flex-1 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-pine-800 ${
                            isActive ? 'bg-pine-800' : ''
                          }`}
                        >
                          <span className="block truncate text-sm text-pine-100">
                            {conversation.title}
                          </span>
                          <span className="block truncate text-xs text-pine-400">
                            {formatTimestamp(conversation.updated_at)}
                          </span>
                        </button>
                        {/*
                          Revealed on hover AND on keyboard focus — `opacity-0`
                          alone would leave these reachable by Tab but
                          invisible to the person tabbing to them.
                        */}
                        <span className="flex items-center gap-0.5 pr-1 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
                          <button
                            type="button"
                            aria-label={`Rename ${conversation.title}`}
                            onClick={() => {
                              setDraftTitle(conversation.title)
                              setRenamingId(id)
                            }}
                            className="rounded-md p-1.5 text-pine-300 hover:text-mint focus-visible:opacity-100"
                          >
                            <Pencil size={14} aria-hidden />
                          </button>
                          <button
                            type="button"
                            aria-label={`Delete ${conversation.title}`}
                            onClick={() => setConfirmingDeleteId(id)}
                            className="rounded-md p-1.5 text-pine-300 hover:text-red-300 focus-visible:opacity-100"
                          >
                            <Trash2 size={14} aria-hidden />
                          </button>
                        </span>
                      </div>
                    )}
                  </li>
                )
              })}
            </ul>
          )}

          {!loading && !error && conversations.length > 0 && (
            <div className="mt-1 border-t border-pine-700 pt-1">
              {confirmingClearAll ? (
                <div className="flex items-center gap-2 p-2">
                  <span className="min-w-0 flex-1 text-sm text-pine-100">
                    Delete all conversations?
                  </span>
                  <button
                    type="button"
                    onClick={() => void confirmClearAll()}
                    className="rounded-md px-2 py-1 text-xs font-medium text-red-300 hover:bg-red-500/10"
                  >
                    Delete all
                  </button>
                  <button
                    type="button"
                    onClick={() => setConfirmingClearAll(false)}
                    className="rounded-md px-2 py-1 text-xs text-pine-300 hover:text-mint"
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => setConfirmingClearAll(true)}
                  className="w-full rounded-lg px-2 py-1.5 text-left text-sm text-pine-300 transition-colors hover:bg-pine-800 hover:text-red-300"
                >
                  Clear all
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
