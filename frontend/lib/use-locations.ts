'use client'

import { useEffect, useState } from 'react'
import { useAdminApi } from './admin-api'
import { LOCATION_OPTIONS } from './constants'

type LocationOption = { value: string; label: string }

/**
 * Hook that fetches selectable inventory locations from the API, falling
 * back to the hardcoded LOCATION_OPTIONS list so dropdowns are never empty.
 *
 * Gated on `api.isAuthenticated` and re-runs when it flips — see
 * `useCosigners`'s docstring (lib/use-cosigners.ts) for why: a `[]`-deps
 * fetch effect can race NextAuth's client session hydration, fail once
 * before the token exists, and never get a second chance to retry.
 */
export function useLocations(): { options: LocationOption[]; loading: boolean } {
  const api = useAdminApi()
  const [options, setOptions] = useState<LocationOption[]>(LOCATION_OPTIONS as unknown as LocationOption[])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!api.isAuthenticated) return
    let cancelled = false

    api
      .get<LocationOption[]>('/locations')
      .then((result) => {
        if (!cancelled) setOptions(result)
      })
      .catch(() => {
        if (!cancelled) setOptions(LOCATION_OPTIONS as unknown as LocationOption[])
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api.isAuthenticated])

  return { options, loading }
}
