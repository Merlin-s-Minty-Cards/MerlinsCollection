import type { InventoryRepository } from "../repository.js";

export type InventorySummaryResult = {
  /** Total number of physical cards held (sum of every card's quantity). */
  totalCards: number;
  /** Total holding value of the inventory (sum of per-unit value x quantity). */
  totalValue: number;
  /** Number of distinct sets represented in the inventory. */
  uniqueSets: number;
  /** Highest per-unit-value cards, descending, capped at {@link TOP_VALUED_LIMIT}. */
  topValuedCards: Array<{ name: string; value: number }>;
};

/** How many cards `topValuedCards` is capped at. */
const TOP_VALUED_LIMIT = 5;

/**
 * Produces a high-level snapshot of the whole inventory: how many cards are held,
 * their total value, how many distinct sets are represented, and the most
 * valuable cards.
 *
 * `totalCards` sums quantities (40 Pikachus count as 40), while `totalValue` is
 * the holding value (per-unit value x quantity). `topValuedCards` ranks by
 * per-unit value rather than holding value, capped at the top five, with ties
 * broken by repository order (the underlying sort is stable).
 *
 * A card with no resolvable price (`value === null`) is still HELD — it counts
 * toward `totalCards` and `uniqueSets` — but contributes nothing to `totalValue`
 * and cannot appear in `topValuedCards`. Left to JS coercion a null would sort
 * as 0 and be advertised as a $0 "top valued card". (The backend's own
 * `/inventory/summary` no longer computes a value total at all as of RFC
 * 0025 T5 — `est_value` was removed, not merely renamed — so this tool's
 * `totalValue` has no backend equivalent to stay in sync with any more; it
 * is now this tool's own figure, over `value` = `sticker_price`.)
 */
export async function getInventorySummary(
  repo: InventoryRepository,
): Promise<InventorySummaryResult> {
  const cards = await repo.listCards();

  const totalCards = cards.reduce((sum, card) => sum + card.quantity, 0);
  const uniqueSets = new Set(cards.map((card) => card.set)).size;

  const priced = cards.flatMap((card) =>
    card.value == null ? [] : [{ name: card.name, value: card.value, quantity: card.quantity }],
  );
  const totalValue = priced.reduce((sum, card) => sum + card.value * card.quantity, 0);
  const topValuedCards = [...priced]
    .sort((a, b) => b.value - a.value)
    .slice(0, TOP_VALUED_LIMIT)
    .map((card) => ({ name: card.name, value: card.value }));

  return { totalCards, totalValue, uniqueSets, topValuedCards };
}
