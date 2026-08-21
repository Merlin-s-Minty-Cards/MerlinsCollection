/**
 * Pure logic — no DOM. Runs in `node` rather than the default jsdom:
 * constructing a jsdom per file was the single largest cost in this
 * suite (215s cumulative `environment` time against 55s of actual tests).
 * If this file ever renders a component or touches window/document,
 * delete this docblock rather than stubbing the DOM by hand.
 *
 * @vitest-environment node
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

import { apiFetch, ApiError } from '@/lib/api'

const fetchMock = vi.fn()

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock)
  fetchMock.mockReset()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

function jsonResponse(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  }
}

describe('apiFetch', () => {
  it('returns the parsed JSON body', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ total: 0, items: [] }))
    await expect(apiFetch('/inventory/search')).resolves.toEqual({ total: 0, items: [] })
  })

  it('attaches an Authorization bearer header when a token is given', async () => {
    fetchMock.mockResolvedValue(jsonResponse({}))
    await apiFetch('/inventory/search', { token: 'jwt-123' })

    const [, init] = fetchMock.mock.calls[0]
    expect(new Headers(init.headers).get('Authorization')).toBe('Bearer jwt-123')
  })

  it('sends no Authorization header when no token is given', async () => {
    fetchMock.mockResolvedValue(jsonResponse({}))
    await apiFetch('/inventory/search')

    const [, init] = fetchMock.mock.calls[0]
    expect(new Headers(init?.headers).get('Authorization')).toBeNull()
  })

  it('keeps caller-supplied headers alongside the token', async () => {
    fetchMock.mockResolvedValue(jsonResponse({}))
    await apiFetch('/chat/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      token: 'jwt-123',
    })

    const [, init] = fetchMock.mock.calls[0]
    const headers = new Headers(init.headers)
    expect(headers.get('Content-Type')).toBe('application/json')
    expect(headers.get('Authorization')).toBe('Bearer jwt-123')
  })

  it('throws an ApiError carrying the backend detail message on non-2xx', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ detail: 'Service is temporarily busy — please try again shortly.' }, 429),
    )
    const err = await apiFetch('/chat/').catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err.status).toBe(429)
    expect(err.detail).toBe('Service is temporarily busy — please try again shortly.')
  })

  it('still throws a useful ApiError when the error body is not JSON', async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 502,
      json: async () => {
        throw new SyntaxError('not json')
      },
    })
    const err = await apiFetch('/chat/').catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err.status).toBe(502)
  })
})
