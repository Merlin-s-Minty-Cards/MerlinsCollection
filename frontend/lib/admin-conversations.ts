/**
 * The ADMIN analyst chat's client (RFC 0018).
 *
 * Deliberately thin: the conversation routes are byte-identical in contract to
 * the customer surface's, so this REBINDS the same factory to
 * `/admin/chat/conversations` rather than reimplementing id encoding, the
 * 204-on-delete gate and the 404-never-403 rule. A second copy of those three
 * would drift, and all three are easy to get subtly wrong and impossible to
 * notice when they are.
 *
 * The surfaces are separated on the SERVER by a stored `surface` tag, not by
 * which client called — so pointing this at the customer base path would not
 * leak anything, it would simply return the wrong list. The value of keeping
 * them apart here is that the admin panel never has to reason about it.
 */
import { apiFetch } from './api'
import { createConversationsClient } from './conversations'
import type { ChatResponse, RequestOptions, SendChatContext } from './inventory'

/** List / get / rename / remove / clear, bound to the admin surface. */
export const adminConversations = createConversationsClient('/admin/chat/conversations')

/**
 * Ask the analyst a question.
 *
 * The transcript is SERVER-owned: this sends a `conversation_id`, never a
 * history array, which is what stops a client forging assistant turns.
 *
 * Trailing slash matters — the backend route is `/admin/chat/` and a bare
 * `/admin/chat` costs a 307 round-trip on every message.
 */
export async function sendAdminChat(
  message: string,
  context: SendChatContext = {},
  opts: RequestOptions = {},
): Promise<ChatResponse> {
  const body: Record<string, unknown> = { message }
  if (context.conversationId) body.conversation_id = context.conversationId
  if (context.panelItemIds) body.panel_item_ids = context.panelItemIds

  return apiFetch<ChatResponse>('/admin/chat/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    token: opts.token,
  })
}
