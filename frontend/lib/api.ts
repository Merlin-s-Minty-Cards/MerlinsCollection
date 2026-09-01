// Typed fetch wrapper for the FastAPI backend — implemented via TDD
import { API_BASE_URL, API_BASE_URL_IS_USABLE } from './api-base'

// Normalized in api-base.ts so `${BASE_URL}${path}` can never emit a double
// slash — see that module for the production 404 this prevents.
const BASE_URL = API_BASE_URL

/** Non-2xx response, carrying the backend's `detail` message when it sent one. */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail?: string,
  ) {
    super(detail ?? `API error ${status}`)
    this.name = 'ApiError'
  }
}

export type ApiInit = RequestInit & {
  /** Cognito access token; sent as an Authorization bearer header when present. */
  token?: string
}

export async function apiFetch<T>(path: string, init?: ApiInit): Promise<T> {
  // Fail before the request exists when the base URL is an unsubstituted
  // build-time placeholder. See api-base.ts's isUsableBaseUrl: handing this to
  // Next's ISR fetch wrapper hangs static generation instead of rejecting, and
  // every caller here already has a fallback for a rejection.
  if (!API_BASE_URL_IS_USABLE) {
    throw new ApiError(
      0,
      `Backend base URL is not usable at this point in the build (${API_BASE_URL}).`,
    )
  }

  const { token, ...rest } = init ?? {}
  const headers = new Headers(rest.headers)
  if (token) headers.set('Authorization', `Bearer ${token}`)

  const res = await fetch(`${BASE_URL}${path}`, { ...rest, headers })
  if (!res.ok) {
    let detail: string | undefined
    try {
      const body = (await res.json()) as { detail?: unknown }
      if (typeof body?.detail === 'string') detail = body.detail
    } catch {
      // non-JSON error body — the status alone will have to do
    }
    throw new ApiError(res.status, detail)
  }
  // 204 No Content carries no body, so `res.json()` would throw on a
  // SUCCESSFUL request — which is how both conversation DELETE routes answer.
  // Gated on the status exactly, never on the body looking empty: a malformed
  // empty 200 is a real failure and must keep failing loudly.
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}
