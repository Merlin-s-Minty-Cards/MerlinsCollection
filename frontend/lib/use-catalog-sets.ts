'use client'

import { useEffect, useState } from 'react'
import { useAdminApi } from './admin-api'
import type { ComboboxSet } from '@/components/shared/SetCombobox'

export interface CatalogSet {
  set_id: string
  set_name: string
  language: string
  card_count: number
  owned_count: number
}

/**
 * Every set in the CATALOG — not the sets present in inventory (RFC 0008 T8).
 *
 * The distinction is the owner's whole reason for asking: *"so we can double
 * check if there is a set in the catalog we have no cards of."* A facet over
 * inventory can never show a set with zero owned cards, so this reads
 * `GET /admin/catalog/sets`, which is backed by the `catalog_set` registry.
 *
 * Fetched ONCE on mount and narrowed in the browser, mirroring the public
 * filter panel. ~400 sets is a small payload, and refetching per keystroke
 * would put a full inventory read behind every letter the admin types.
 *
 * An empty list on failure is deliberate: a set filter that cannot load leaves
 * the rest of the (already numerous) admin filters working. There is no
 * hardcoded fallback the way `useLocations` has one — a stale hardcoded set
 * list is exactly the drift this endpoint exists to remove.
 *
 * Gated on `api.isAuthenticated` and re-runs when it flips — see
 * `useCosigners`'s docstring (lib/use-cosigners.ts) for why: a `[]`-deps
 * fetch effect can race NextAuth's client session hydration, fail once
 * before the token exists, and never get a second chance to retry.
 */
export function useCatalogSets(): { sets: CatalogSet[]; loading: boolean } {
  const api = useAdminApi()
  const [sets, setSets] = useState<CatalogSet[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!api.isAuthenticated) return
    let cancelled = false

    api
      .get<CatalogSet[]>('/catalog/sets')
      .then((result) => {
        // Array-checked, not just null-checked. A 200 carrying anything else —
        // an error envelope, a proxy's HTML, an older backend with no such
        // route — would otherwise reach `.map()` during render and blank the
        // ENTIRE inventory page over one optional filter.
        if (!cancelled) setSets(Array.isArray(result) ? result : [])
      })
      .catch(() => {
        if (!cancelled) setSets([])
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api.isAuthenticated])

  return { sets, loading }
}

/**
 * Registry rows as the shared combobox wants them.
 *
 * The language lives in the ANNOTATION, not in the name, for two reasons: the
 * name is what typing narrows against (folding "EN" into it would make one
 * keystroke match every English set), and the annotation is where the owned
 * count belongs anyway — the zero is the number the owner opens this list for.
 */
export function toComboboxSets(sets: CatalogSet[]): ComboboxSet[] {
  return sets.map((s) => ({
    id: s.set_id,
    name: s.set_name,
    annotation: `${s.language} · ${s.owned_count} owned`,
  }))
}
