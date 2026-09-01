/**
 * Typed client for the five conversation routes (RFC 0017).
 *
 * The transcript is SERVER-owned: the client never sends a history array, it
 * sends a `conversation_id` and the backend replays the thread from storage.
 * That is also what stops a client forging assistant turns, so nothing here
 * should grow a way to push transcript content back up.
 *
 * Every route is customer-private and scoped to the caller's own Cognito
 * `sub`. A thread the caller does not own answers **404, never 403** — a 403
 * would confirm the id exists — so callers must treat 404 as "gone or never
 * yours", not as a bug.
 */
import { apiFetch } from './api'
import type { DisplayPanelState, DisplayedCard, RequestOptions } from './inventory'

/**
 * The customer surface's routes. RFC 0018 adds an ADMIN surface at
 * `/admin/chat/conversations` with an identical contract, so the client below
 * is built as a FACTORY and bound twice rather than copied — see
 * `createConversationsClient` and `lib/admin-conversations.ts`.
 *
 * A second copy would drift: id encoding, the 204-on-delete gate and the
 * "404 means gone or never yours" contract all live in one place because all
 * three are easy to get subtly wrong and impossible to notice when they are.
 */
const BASE = '/chat/conversations'

/** One thread as it appears in the history list. */
export interface ConversationSummary {
  conversation_id: string
  title: string
  /** ISO-8601 timestamps. Render through `lib/dates.ts`, never `new Date()`. */
  created_at: string
  updated_at: string
  message_count: number
}

/** One stored turn. `artifacts` are re-hydrated live by the backend. */
export interface ConversationMessage {
  seq: number
  role: 'user' | 'assistant'
  content: string
  artifacts: DisplayedCard[]
  created_at: string
}

/** A resumed thread: transcript plus its live-hydrated display panel. */
export interface ConversationDetail {
  conversation_id: string
  title: string
  created_at: string
  updated_at: string
  messages: ConversationMessage[]
  /** True when older turns exist beyond the most recent 200 returned. */
  truncated: boolean
  panel: DisplayPanelState
}

interface ConversationListResponse {
  conversations: ConversationSummary[]
}

/**
 * Encoded so a crafted id cannot climb out of this route and reach another
 * one with the caller's bearer token already attached.
 */
function pathFor(base: string, conversationId: string): string {
  return `${base}/${encodeURIComponent(conversationId)}`
}

/** Every conversation operation, bound to one surface's base path. */
export interface ConversationsClient {
  list(opts?: RequestOptions): Promise<ConversationSummary[]>
  get(conversationId: string, opts?: RequestOptions): Promise<ConversationDetail>
  rename(
    conversationId: string,
    title: string,
    opts?: RequestOptions,
  ): Promise<ConversationSummary>
  remove(conversationId: string, opts?: RequestOptions): Promise<void>
  clear(opts?: RequestOptions): Promise<void>
}

/**
 * Bind the conversation routes to a base path.
 *
 * Both surfaces have byte-identical contracts — same ownership rule, same
 * 404-never-403 on a thread id, same 204s on delete — so they are the same
 * code with a different prefix, never two implementations kept in step by
 * hand.
 */
export function createConversationsClient(base: string): ConversationsClient {
  return {
    async list(opts: RequestOptions = {}) {
      const res = await apiFetch<ConversationListResponse>(base, { token: opts.token })
      return res.conversations
    },
    get(conversationId, opts: RequestOptions = {}) {
      return apiFetch<ConversationDetail>(pathFor(base, conversationId), {
        token: opts.token,
      })
    },
    rename(conversationId, title, opts: RequestOptions = {}) {
      return apiFetch<ConversationSummary>(pathFor(base, conversationId), {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title }),
        token: opts.token,
      })
    },
    async remove(conversationId, opts: RequestOptions = {}) {
      await apiFetch<void>(pathFor(base, conversationId), {
        method: 'DELETE',
        token: opts.token,
      })
    },
    async clear(opts: RequestOptions = {}) {
      await apiFetch<void>(base, { method: 'DELETE', token: opts.token })
    },
  }
}

/**
 * The customer binding. Exported (not just used internally) so a caller that
 * wants the CLIENT OBJECT rather than the five loose functions below can ask
 * for it directly — `HistoryMenu`'s `client` prop defaults to this, which is
 * what lets the identical flyout also serve the admin surface by being handed
 * `adminConversations` (`lib/admin-conversations.ts`) instead.
 */
export const customerConversations = createConversationsClient(BASE)

/** The caller's own threads, at most 50, most recently used first. */
export function listConversations(
  opts: RequestOptions = {},
): Promise<ConversationSummary[]> {
  return customerConversations.list(opts)
}

/** One thread's transcript, with every card re-hydrated live. */
export function getConversation(
  conversationId: string,
  opts: RequestOptions = {},
): Promise<ConversationDetail> {
  return customerConversations.get(conversationId, opts)
}

/** Rename a thread. Does not count as use — `updated_at` is untouched. */
export function renameConversation(
  conversationId: string,
  title: string,
  opts: RequestOptions = {},
): Promise<ConversationSummary> {
  return customerConversations.rename(conversationId, title, opts)
}

/** Hard delete — index row first, then the message sweep. Answers 204. */
export function deleteConversation(
  conversationId: string,
  opts: RequestOptions = {},
): Promise<void> {
  return customerConversations.remove(conversationId, opts)
}

/** Delete every thread the caller owns. Irreversible; the UI confirms. */
export function clearConversations(opts: RequestOptions = {}): Promise<void> {
  return customerConversations.clear(opts)
}
