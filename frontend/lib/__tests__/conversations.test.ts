/**
 * Pure logic — no DOM. Runs in `node` rather than the default jsdom, for the
 * reason api.test.ts's docblock gives.
 *
 * RFC 0017 item 8: the typed client for the five conversation routes.
 *
 * @vitest-environment node
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@/lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/api')>()),
  apiFetch: vi.fn(),
}))

import { apiFetch } from '@/lib/api'
import {
  listConversations,
  getConversation,
  renameConversation,
  deleteConversation,
  clearConversations,
} from '@/lib/conversations'

const mockedApiFetch = vi.mocked(apiFetch)

beforeEach(() => {
  // mockReset, not clearAllMocks — see ChatPanel.test.tsx for the measurement.
  mockedApiFetch.mockReset()
})

describe('listConversations', () => {
  it('gets the caller’s own threads, forwarding the access token', async () => {
    mockedApiFetch.mockResolvedValue({ conversations: [] })

    await listConversations({ token: 'test-token' })

    const [path, init] = mockedApiFetch.mock.calls[0]
    expect(path).toBe('/chat/conversations')
    expect(init?.token).toBe('test-token')
  })

  it('returns the conversations array from the response envelope', async () => {
    const summary = {
      conversation_id: '01JD',
      title: 'What Charizards…',
      created_at: '2026-08-26T18:04:11Z',
      updated_at: '2026-08-26T18:22:40Z',
      message_count: 6,
    }
    mockedApiFetch.mockResolvedValue({ conversations: [summary] })

    await expect(listConversations()).resolves.toEqual([summary])
  })
})

describe('getConversation', () => {
  it('gets one thread by id', async () => {
    mockedApiFetch.mockResolvedValue({ conversation_id: '01JD', messages: [] })

    await getConversation('01JD', { token: 'test-token' })

    const [path, init] = mockedApiFetch.mock.calls[0]
    expect(path).toBe('/chat/conversations/01JD')
    expect(init?.token).toBe('test-token')
  })

  it('encodes the id so a crafted one cannot reach a different route', async () => {
    mockedApiFetch.mockResolvedValue({ conversation_id: 'x', messages: [] })

    await getConversation('../../admin/inventory')

    expect(mockedApiFetch.mock.calls[0][0]).toBe(
      '/chat/conversations/..%2F..%2Fadmin%2Finventory',
    )
  })
})

describe('renameConversation', () => {
  it('patches the thread with the new title as a JSON body', async () => {
    mockedApiFetch.mockResolvedValue({ conversation_id: '01JD', title: 'Renamed' })

    await renameConversation('01JD', 'Renamed', { token: 'test-token' })

    const [path, init] = mockedApiFetch.mock.calls[0]
    expect(path).toBe('/chat/conversations/01JD')
    expect(init?.method).toBe('PATCH')
    expect(JSON.parse(String(init?.body))).toEqual({ title: 'Renamed' })
    expect(init?.token).toBe('test-token')
  })
})

describe('deleteConversation', () => {
  it('deletes one thread by id', async () => {
    mockedApiFetch.mockResolvedValue(undefined)

    await deleteConversation('01JD', { token: 'test-token' })

    const [path, init] = mockedApiFetch.mock.calls[0]
    expect(path).toBe('/chat/conversations/01JD')
    expect(init?.method).toBe('DELETE')
    expect(init?.token).toBe('test-token')
  })
})

describe('clearConversations', () => {
  it('deletes every thread the caller owns', async () => {
    mockedApiFetch.mockResolvedValue(undefined)

    await clearConversations({ token: 'test-token' })

    const [path, init] = mockedApiFetch.mock.calls[0]
    expect(path).toBe('/chat/conversations')
    expect(init?.method).toBe('DELETE')
    expect(init?.token).toBe('test-token')
  })
})
