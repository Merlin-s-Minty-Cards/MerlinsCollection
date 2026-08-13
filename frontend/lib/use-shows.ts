'use client'

import { useEffect, useState } from 'react'
import { useAdminApi } from './admin-api'

export interface ShowOption {
  show_id: string
  name: string
  date: string
}

/**
 * The show list, as `{value, label}` options for a filter dropdown (RFC 0011 T4).
 *
 * `acquired_show_id` stores an opaque id, so a filter over it has to offer
 * names — an admin does not know which id last Saturday's show got. Archived
 * shows are INCLUDED: an item acquired at a show that has since been archived
 * still carries that id, and hiding the name would leave those rows filterable
 * only by an id nothing on screen shows.
 *
 * An empty list on failure, like `useCatalogSets`: one optional filter that
 * cannot load must not take the rest of the panel with it.
 */
export function useShows(): { options: { value: string; label: string }[]; loading: boolean } {
  const api = useAdminApi()
  const [options, setOptions] = useState<{ value: string; label: string }[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false

    api
      .get<ShowOption[]>('/shows', { include_archived: true })
      .then((result) => {
        // Array-checked, not just null-checked. A 200 carrying an error
        // envelope or a proxy's HTML would otherwise reach `.map()` during
        // render and blank the entire inventory page over one filter.
        if (cancelled) return
        setOptions(
          Array.isArray(result)
            ? result.map((s) => ({ value: s.show_id, label: s.name }))
            : [],
        )
      })
      .catch(() => {
        if (!cancelled) setOptions([])
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return { options, loading }
}
