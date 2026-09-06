'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { useAdminApi } from './admin-api'

/**
 * The shared batching/caching core behind every card_id -> T admin lookup —
 * `useCardImages` and `useCardNumbers` are both thin wrappers over this
 * rather than two copies of the same resolved/pending/failed bookkeeping.
 * Extracted when `useCardNumbers` was added (RFC 0023 follow-up, card
 * number display) rather than duplicated: this logic already has a
 * debugged, non-obvious correctness property (see `failedRef` below) that a
 * second hand-copy would have been one more place to get subtly wrong.
 *
 * One attempt per id, ever, per hook instance — CLAUDE.md's rule for card
 * art ("card art is decoration... one attempt per id, then the placeholder")
 * applies identically to any other derived-from-catalog display value: a
 * failed lookup must not be re-queued on every render, or a page that
 * re-renders per keystroke (Trade's search boxes) turns one failure into a
 * request storm.
 */
export function useBatchedCardLookup<T>(
  cardIds: (string | null | undefined)[],
  endpoint: string,
) {
  const api = useAdminApi()
  const [map, setMap] = useState<Record<string, T | null>>({})
  const resolvedRef = useRef<Set<string>>(new Set())
  const pendingRef = useRef<Set<string>>(new Set())
  const failedRef = useRef<Set<string>>(new Set())

  const resolve = useCallback(async () => {
    if (!api.isAuthenticated) return

    const toResolve = cardIds.filter(
      (id): id is string =>
        typeof id === 'string' &&
        id.length > 0 &&
        !resolvedRef.current.has(id) &&
        !pendingRef.current.has(id) &&
        !failedRef.current.has(id)
    )

    if (toResolve.length === 0) return

    toResolve.forEach((id) => pendingRef.current.add(id))

    try {
      const result = await api.post<Record<string, T | null>>(endpoint, {
        card_ids: toResolve,
      })
      toResolve.forEach((id) => {
        resolvedRef.current.add(id)
        pendingRef.current.delete(id)
      })
      setMap((prev) => ({ ...prev, ...result }))
    } catch {
      // Clear pending and mark failed, so these ids are not re-queued on the
      // next render. `get` returns null for them and the caller shows
      // whatever it shows for "no value" — the same thing it shows for a
      // card genuinely lacking this data.
      toResolve.forEach((id) => {
        pendingRef.current.delete(id)
        failedRef.current.add(id)
      })
    }
  }, [api, cardIds, endpoint])

  useEffect(() => {
    resolve()
  }, [resolve])

  const get = useCallback(
    (cardId: string | null | undefined): T | null => {
      if (!cardId) return null
      return map[cardId] ?? null
    },
    [map]
  )

  return { map, get }
}
