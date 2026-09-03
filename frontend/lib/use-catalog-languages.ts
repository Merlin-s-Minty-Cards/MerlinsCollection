'use client'

import { useEffect, useState } from 'react'
import { useAdminApi } from './admin-api'

export interface CatalogLanguage {
  code: string
  label: string
  sets: number
}

/**
 * Languages that ACTUALLY have catalog rows — `GET /admin/catalog/languages`
 * (RFC 0023 T2), backed by the `catalog_set` registry, not the 19-member
 * `Language` enum. Offering every enum member here would let an admin pick a
 * language the catalog search can only ever return nothing for (T2's own
 * reasoning, mirrored on the frontend).
 *
 * Same shape as `useCatalogSets` (lib/use-catalog-sets.ts) deliberately —
 * fetched once on mount, gated on `api.isAuthenticated` and re-run when it
 * flips (CLAUDE.md documents four admin dropdown hooks that shipped
 * permanently empty from a `[]`-deps effect racing NextAuth's client session
 * hydration), and an empty list on any failure so one broken filter never
 * blanks the rest of the admin panel.
 */
export function useCatalogLanguages(): { languages: CatalogLanguage[]; loading: boolean } {
  const api = useAdminApi()
  const [languages, setLanguages] = useState<CatalogLanguage[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!api.isAuthenticated) return
    let cancelled = false

    api
      .get<CatalogLanguage[]>('/catalog/languages')
      .then((result) => {
        if (!cancelled) setLanguages(Array.isArray(result) ? result : [])
      })
      .catch(() => {
        if (!cancelled) setLanguages([])
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api.isAuthenticated])

  return { languages, loading }
}
