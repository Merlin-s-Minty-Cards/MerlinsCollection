'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { useAdminApi } from './admin-api'

/**
 * Hook that bulk-resolves card images from card_ids via the admin API.
 * Caches results to avoid redundant requests. Batches lookups.
 */
export function useCardImages(cardIds: (string | null | undefined)[]) {
  const api = useAdminApi()
  const [imageMap, setImageMap] = useState<Record<string, string | null>>({})
  const resolvedRef = useRef<Set<string>>(new Set())
  const pendingRef = useRef<Set<string>>(new Set())
  /**
   * Ids whose lookup already failed once.
   *
   * Callers pass a freshly-mapped array (`items.map(i => i.card_id)`), so this
   * hook's `resolve` is a new identity on every render and its effect re-runs
   * every render. Putting failed ids straight back in the queue therefore
   * means one POST per render — and on a page that re-renders per keystroke
   * (Trade's search boxes) that is a request storm aimed at an endpoint that
   * is already broken. Card art is decoration: one attempt per id, then the
   * placeholder. Remounting the page clears this and tries again.
   */
  const failedRef = useRef<Set<string>>(new Set())

  const resolve = useCallback(async () => {
    if (!api.isAuthenticated) return

    // Find card_ids not yet resolved
    const toResolve = cardIds.filter(
      (id): id is string =>
        typeof id === 'string' &&
        id.length > 0 &&
        !resolvedRef.current.has(id) &&
        !pendingRef.current.has(id) &&
        !failedRef.current.has(id)
    )

    if (toResolve.length === 0) return

    // Mark as pending
    toResolve.forEach((id) => pendingRef.current.add(id))

    try {
      const result = await api.post<Record<string, string | null>>(
        '/inventory/card-images',
        { card_ids: toResolve }
      )
      // Update resolved set and image map
      toResolve.forEach((id) => {
        resolvedRef.current.add(id)
        pendingRef.current.delete(id)
      })
      setImageMap((prev) => ({ ...prev, ...result }))
    } catch {
      // Clear pending and mark failed, so these ids are not re-queued on the
      // next render. `getImageUrl` returns null for them and the caller shows
      // its placeholder — the same thing it shows for a card with no art.
      toResolve.forEach((id) => {
        pendingRef.current.delete(id)
        failedRef.current.add(id)
      })
    }
  }, [api, cardIds])

  useEffect(() => {
    resolve()
  }, [resolve])

  /** Get image URL for a specific card_id */
  const getImageUrl = useCallback(
    (cardId: string | null | undefined): string | null => {
      if (!cardId) return null
      return imageMap[cardId] ?? null
    },
    [imageMap]
  )

  return { imageMap, getImageUrl }
}
