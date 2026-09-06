'use client'

import { useBatchedCardLookup } from './use-batched-card-lookup'

/**
 * Hook that bulk-resolves card images from card_ids via the admin API.
 * Caches results to avoid redundant requests. Batches lookups.
 *
 * A thin wrapper over `useBatchedCardLookup` — the batching/caching/
 * one-attempt-per-id logic lives there now (shared with `useCardNumbers`),
 * not duplicated here. `imageMap`/`getImageUrl`'s names and behavior are
 * unchanged, so every existing caller of this hook needed zero changes.
 */
export function useCardImages(cardIds: (string | null | undefined)[]) {
  const { map, get } = useBatchedCardLookup<string>(cardIds, '/inventory/card-images')
  return { imageMap: map, getImageUrl: get }
}
