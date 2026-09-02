// @vitest-environment node
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { adminConversations, sendAdminChat } from '../admin-conversations'
import { listConversations } from '../conversations'

const fetchMock = vi.fn()
vi.stubGlobal('fetch', fetchMock)

function ok(body: unknown, status = 200) {
  return { ok: true, status, json: async () => body } as unknown as Response
}

beforeEach(() => {
  fetchMock.mockReset()
})

describe('the admin conversation client', () => {
  it('talks to the ADMIN routes, never the customer ones', async () => {
    fetchMock.mockResolvedValue(ok({ conversations: [] }))
    await adminConversations.list({ token: 't' })

    const url = String(fetchMock.mock.calls[0][0])
    expect(url).toContain('/admin/chat/conversations')
    // The whole point of the surface split: an admin thread list must never be
    // fetched from the customer route, where it would not appear anyway.
    expect(url).not.toMatch(/(?<!\/admin)\/chat\/conversations/)
  })

  it('is the SAME implementation as the customer client, only rebound', async () => {
    // A second copy would drift — the customer client already encodes ids,
    // handles 204 on delete, and treats 404 as "gone or never yours". Rebinding
    // the base path keeps one implementation of all of that.
    fetchMock.mockResolvedValue(ok({ conversations: [] }))
    await listConversations({ token: 't' })
    const customerUrl = String(fetchMock.mock.calls[0][0])

    fetchMock.mockReset()
    fetchMock.mockResolvedValue(ok({ conversations: [] }))
    await adminConversations.list({ token: 't' })
    const adminUrl = String(fetchMock.mock.calls[0][0])

    expect(customerUrl.endsWith('/chat/conversations')).toBe(true)
    expect(adminUrl.endsWith('/admin/chat/conversations')).toBe(true)
  })

  it('encodes a crafted conversation id rather than letting it climb the path', async () => {
    fetchMock.mockResolvedValue(ok({ conversation_id: 'x' }))
    await adminConversations.get('../../inventory/search', { token: 't' })

    const url = String(fetchMock.mock.calls[0][0])
    expect(url).toContain('%2F')
    expect(url).not.toContain('/inventory/search')
  })

  it('sends a chat message to /admin/chat/ with the trailing slash', async () => {
    fetchMock.mockResolvedValue(ok({ reply: 'ok', artifacts: [], panel: { cards: [] } }))
    await sendAdminChat('what did I net at Portland?', {}, { token: 't' })

    const [url, init] = fetchMock.mock.calls[0]
    // A bare /admin/chat costs a 307 round-trip on every message.
    expect(String(url).endsWith('/admin/chat/')).toBe(true)
    expect((init as RequestInit).method).toBe('POST')
  })

  it('passes a conversation id through so the server can replay the thread', async () => {
    fetchMock.mockResolvedValue(ok({ reply: 'ok', artifacts: [], panel: { cards: [] } }))
    await sendAdminChat('and last month?', { conversationId: '01ADMIN' }, { token: 't' })

    const body = JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body))
    expect(body.conversation_id).toBe('01ADMIN')
    // The transcript is server-owned — the client must never send turns.
    expect(body.history).toBeUndefined()
  })

  it('returns nothing rather than throwing when a delete answers 204', async () => {
    fetchMock.mockResolvedValue({ ok: true, status: 204 } as unknown as Response)
    await expect(adminConversations.remove('01ADMIN', { token: 't' })).resolves.toBeUndefined()
  })
})
