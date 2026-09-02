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
  vi.unstubAllEnvs()
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

describe('apiFetch URL construction', () => {
  // Reproduces the production 404, 2026-08-26. The deployed
  // NEXT_PUBLIC_API_URL is a Lambda Function URL, which ALWAYS ends in a
  // slash; every caller's `path` starts with one. `${BASE_URL}${path}` then
  // requests `//inventory/search`, which FastAPI's router 404s (measured
  // live: `/health` -> 200, `//health` -> 404). BASE_URL is read once at
  // module load, so the env var has to be stubbed before a fresh import.
  it('never produces a double slash when the base URL has a trailing slash', async () => {
    vi.stubEnv('NEXT_PUBLIC_API_URL', 'https://abc123.lambda-url.us-east-1.on.aws/')
    vi.resetModules()
    const { apiFetch: freshApiFetch } = await import('@/lib/api')

    fetchMock.mockResolvedValue(jsonResponse({}))
    await freshApiFetch('/inventory/search')

    const [url] = fetchMock.mock.calls[0]
    expect(String(url)).toBe('https://abc123.lambda-url.us-east-1.on.aws/inventory/search')
  })
})

describe('apiFetch against an unsubstituted build-time placeholder', () => {
  /**
   * The real, measured cause of this project's "known, unresolved" build
   * flakiness — the thing `next.config.ts`'s staticPageGenerationTimeout: 180
   * was buffering against, and which `frontend-stack.ts` records as a
   * suspected "proxy/DNS/socket difference on Windows". It is neither.
   *
   * During `next build`, NEXT_PUBLIC_API_URL is the literal placeholder
   * `{{ NEXT_PUBLIC_API_URL }}`. Raw `fetch` rejects that in ~23ms — but
   * lib/public.ts calls it with `next: { revalidate: 300 }`, and inside Next's
   * ISR fetch wrapper the rejection becomes a HANG. Static generation then
   * burns the full 180s watchdog, three times, and fails the build on
   * whichever public page got there first (measured: `/` on one run, `/shows`
   * on the next — the "different page each time" signature already noted).
   *
   * The page-level `try { … } catch { fall back to static cards }` never
   * saves it, because A HANG IS NOT AN ERROR. So: never hand Next's fetch an
   * unusable base URL. Reject before the request exists, and the fallback
   * that was already written does its job.
   */
  it('rejects without ever calling fetch, so a caller fallback can run', async () => {
    vi.stubEnv('NEXT_PUBLIC_API_URL', '{{ NEXT_PUBLIC_API_URL }}')
    vi.resetModules()
    const { apiFetch: freshApiFetch } = await import('@/lib/api')

    await expect(freshApiFetch('/public/shows')).rejects.toThrow()
    expect(fetchMock).not.toHaveBeenCalled()
  })
})

/**
 * RFC 0017 item 8: two of the five conversation routes answer 204 No Content
 * (`DELETE /chat/conversations/{id}` and `DELETE /chat/conversations`). A 204
 * carries no body, so the unconditional `res.json()` this wrapper used to end
 * on threw `SyntaxError: Unexpected end of JSON input` on a SUCCESSFUL delete
 * — a success path that raises.
 *
 * Gated on the status being exactly 204, never on the body looking empty: a
 * malformed empty 200 is a real failure and must keep failing loudly.
 */
describe('apiFetch on a 204 No Content', () => {
  it('resolves instead of throwing on an empty body', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      status: 204,
      json: async () => {
        throw new SyntaxError('Unexpected end of JSON input')
      },
    })

    await expect(apiFetch('/chat/conversations/01JD', { method: 'DELETE' })).resolves
      .toBeUndefined()
  })

  it('still fails loudly when a 200 carries an unparseable body', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => {
        throw new SyntaxError('Unexpected end of JSON input')
      },
    })

    await expect(apiFetch('/inventory/summary')).rejects.toThrow(SyntaxError)
  })
})
