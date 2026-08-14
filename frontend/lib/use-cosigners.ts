'use client'

import { useEffect, useState } from 'react'
import { useAdminApi } from './admin-api'

export type CosignorOption = { value: string; label: string }

interface CosignorRow {
  consignor_id: string
  name: string
}

/**
 * Fetches assignable cosigners once. GET /admin/cosigners already excludes
 * archived cosigners by default (cosigners.py:111-124) — this never passes
 * include_archived, so an archived cosigner is never offered as an
 * assignment target, matching the archived-entity pattern used everywhere
 * else in this codebase.
 */
export function useCosigners(): { options: CosignorOption[]; loading: boolean } {
  const api = useAdminApi()
  const [options, setOptions] = useState<CosignorOption[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false

    api
      .get<CosignorRow[]>('/cosigners')
      .then((rows) => {
        if (!cancelled) setOptions(rows.map((r) => ({ value: r.consignor_id, label: r.name })))
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
