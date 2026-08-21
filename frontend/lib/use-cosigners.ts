'use client'

import { useEffect, useState } from 'react'
import { useAdminApi } from './admin-api'

export type CosignorOption = { value: string; label: string }

interface CosignorRow {
  consignor_id: string
  name: string
}

/**
 * Fetches assignable cosigners once authenticated. GET /admin/cosigners already
 * excludes archived cosigners by default (cosigners.py:111-124) — this never
 * passes include_archived, so an archived cosigner is never offered as an
 * assignment target, matching the archived-entity pattern used everywhere
 * else in this codebase.
 *
 * Gated on `api.isAuthenticated` and re-runs when it flips. The admin
 * SessionProvider is mounted with no initial `session` prop
 * (components/providers/SessionProvider.tsx), so `useSession()` genuinely
 * starts at `status: 'loading'` on every fresh page load — even on a route
 * the SERVER already gated behind a valid admin session
 * (app/(admin)/layout.tsx's own `auth()` call tells you nothing about the
 * CLIENT SessionProvider's timing). A fetch effect with `[]` deps that fires
 * before the token is ready 401s once, gets caught, and — with no dependency
 * to ever re-run on — never retries: this dropdown stayed empty for the rest
 * of the page's life even though `/admin/cosigners` had real rows. Depending
 * on `api.isAuthenticated` instead is what lets it retry the moment the
 * session resolves, the same pattern `useCardImages` and the Cosigners admin
 * page's own fetch already use.
 */
export function useCosigners(): { options: CosignorOption[]; loading: boolean } {
  const api = useAdminApi()
  const [options, setOptions] = useState<CosignorOption[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!api.isAuthenticated) return
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
  }, [api.isAuthenticated])

  return { options, loading }
}
