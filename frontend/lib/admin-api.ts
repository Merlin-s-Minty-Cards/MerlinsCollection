'use client'

import { useSession } from 'next-auth/react'
import { useCallback, useRef } from 'react'

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

/** Error thrown by admin API calls with status and optional detail from backend. */
export class AdminApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail?: string,
  ) {
    super(detail ?? `Admin API error ${status}`)
    this.name = 'AdminApiError'
  }
}

type FetchOptions = {
  body?: unknown
  params?: Record<string, string | number | boolean | undefined | null>
}

/**
 * Hook providing authenticated admin API methods.
 * Reads the access token from the NextAuth session and sends it as a Bearer header.
 * Returns { get, post, put, patch, del } plus session loading state.
 */
export function useAdminApi() {
  const { data: session, status } = useSession()
  const tokenRef = useRef<string | undefined>(undefined)
  tokenRef.current = session?.accessToken

  const request = useCallback(
    async <T = unknown>(method: string, path: string, opts?: FetchOptions): Promise<T> => {
      const token = tokenRef.current
      if (!token) {
        throw new AdminApiError(401, 'No access token available')
      }

      const headers: Record<string, string> = {
        Authorization: `Bearer ${token}`,
      }

      let url = `${BASE_URL}/admin${path}`

      // Append query params for GET requests
      if (opts?.params) {
        const searchParams = new URLSearchParams()
        for (const [key, value] of Object.entries(opts.params)) {
          if (value !== undefined && value !== null) {
            searchParams.set(key, String(value))
          }
        }
        const qs = searchParams.toString()
        if (qs) url += `?${qs}`
      }

      const init: RequestInit = { method, headers }

      if (opts?.body !== undefined) {
        headers['Content-Type'] = 'application/json'
        init.body = JSON.stringify(opts.body)
      }

      const res = await fetch(url, init)

      if (!res.ok) {
        let detail: string | undefined
        try {
          const body = (await res.json()) as { detail?: unknown }
          if (typeof body?.detail === 'string') detail = body.detail
        } catch {
          // non-JSON error body
        }
        throw new AdminApiError(res.status, detail)
      }

      return res.json() as Promise<T>
    },
    [],
  )

  const get = useCallback(
    <T = unknown>(path: string, params?: FetchOptions['params']) =>
      request<T>('GET', path, { params }),
    [request],
  )

  const post = useCallback(
    <T = unknown>(path: string, body?: unknown) => request<T>('POST', path, { body }),
    [request],
  )

  const put = useCallback(
    <T = unknown>(path: string, body?: unknown) => request<T>('PUT', path, { body }),
    [request],
  )

  const patch = useCallback(
    <T = unknown>(path: string, body?: unknown) => request<T>('PATCH', path, { body }),
    [request],
  )

  const del = useCallback(
    <T = unknown>(path: string, params?: FetchOptions['params']) =>
      request<T>('DELETE', path, { params }),
    [request],
  )

  return {
    get,
    post,
    put,
    patch,
    del,
    isLoading: status === 'loading',
    isAuthenticated: status === 'authenticated' && !!session?.accessToken,
    session,
  }
}
