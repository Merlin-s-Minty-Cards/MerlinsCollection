'use client'

import { useEffect, useState } from 'react'
import { useAdminApi } from './admin-api'

export type AdminDocCategory = { id: string; label: string }

export type AdminDocArticle = {
  id: string
  category: string
  title: string
  summary: string
  body: string
  keywords: string[]
  related_routes: string[]
}

type AdminDocsResponse = { categories: AdminDocCategory[]; articles: AdminDocArticle[] }

/**
 * Fetches the admin operations knowledge base (`GET /admin/docs`, RFC 0026)
 * — the same content the `search_admin_docs` MCP tool reads.
 *
 * Gated on `api.isAuthenticated` and re-runs when it flips — see
 * `use-locations.ts`/`use-cosigners.ts`'s docstrings for why: a `[]`-deps
 * fetch effect can race NextAuth's client session hydration, fail once
 * before the token exists, and never get a second chance to retry.
 *
 * Unlike `useLocations`, there is no hardcoded content to fall back to on
 * failure — a knowledge base has no sensible default — so a failed fetch
 * reports `error: true` with empty lists, and the UI shows a visible
 * "couldn't load" state rather than silently rendering nothing.
 */
export function useAdminDocs(): {
  categories: AdminDocCategory[]
  articles: AdminDocArticle[]
  loading: boolean
  error: boolean
} {
  const api = useAdminApi()
  const [categories, setCategories] = useState<AdminDocCategory[]>([])
  const [articles, setArticles] = useState<AdminDocArticle[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  useEffect(() => {
    if (!api.isAuthenticated) return
    let cancelled = false

    api
      .get<AdminDocsResponse>('/docs')
      .then((result) => {
        if (cancelled) return
        setCategories(result.categories)
        setArticles(result.articles)
        setError(false)
      })
      .catch(() => {
        if (cancelled) return
        setCategories([])
        setArticles([])
        setError(true)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api.isAuthenticated])

  return { categories, articles, loading, error }
}
