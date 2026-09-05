'use client'

import { useBatchedCardLookup } from './use-batched-card-lookup'

/**
 * Hook that bulk-resolves catalog print numbers ("25" in "sv1-25") from
 * card_ids via the admin API. Same shape as `useCardImages` — both are thin
 * wrappers over `useBatchedCardLookup` — but backed by its OWN endpoint,
 * `/admin/inventory/card-numbers`, rather than folded into `/card-images`'s
 * response: the admin inventory table gates each lookup on its own column's
 * visibility (mirrors the Image column's `showImages` gate), so an admin
 * viewing Card # without Images (or vice versa) should not pay for a fetch
 * of data they didn't ask to see.
 */
export function useCardNumbers(cardIds: (string | null | undefined)[]) {
  const { map, get } = useBatchedCardLookup<string>(cardIds, '/inventory/card-numbers')
  return { numberMap: map, getCardNumber: get }
}
