// Typed fetch wrapper for the FastAPI backend — implemented via TDD
const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

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
  return res.json() as Promise<T>
}
