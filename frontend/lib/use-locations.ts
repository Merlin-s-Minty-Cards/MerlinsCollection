'use client'

import { useEffect, useState } from 'react'
import { useAdminApi } from './admin-api'
import { LOCATION_OPTIONS } from './constants'

type LocationOption = { value: string; label: string }

/**
 * Hook that fetches selectable inventory locations from the API, falling
 * back to the hardcoded LOCATION_OPTIONS list so dropdowns are never empty.
 */
export function useLocations(): { options: LocationOption[]; loading: boolean } {
  const api = useAdminApi()
  const [options, setOptions] = useState<LocationOption[]>(LOCATION_OPTIONS as unknown as LocationOption[])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
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
  }, [])

  return { options, loading }
}
