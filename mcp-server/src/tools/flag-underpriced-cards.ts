import type { InventoryRepository } from "../repository.js";

export type UnderpricedCard = {
  id: string;
  name: string;
  set: string;
  /** The card's current listed value per unit. */
  listedPrice: number;
  /** The external market reference price per unit. */
  marketPrice: number;
  /** Unrounded percentage the listed price sits below market: (market - listed) / market x 100. */
  discountPercent: number;
};

export type FlagUnderpricedResult = {
  flaggedCards: UnderpricedCard[];
  /** Echoes the threshold the caller passed in, for traceability. */
  thresholdPercent: number;
};

/**
 * Flags cards listed below `thresholdPercent` of their market price — e.g. a
 * threshold of 80 flags anything listed under 80% of market. The comparison is a
 * strict less-than, so a card listed at exactly the threshold is not flagged.
 * Cards without a positive market reference are skipped (they have no meaningful
 * discount and would otherwise divide by zero).
 */
export async function flagUnderpricedCards(
  repo: InventoryRepository,
  thresholdPercent: number,
): Promise<FlagUnderpricedResult> {
  const cards = await repo.listCards();

  const flaggedCards: UnderpricedCard[] = [];
  for (const card of cards) {
    // Skip cards without a usable market reference (avoids divide-by-zero on the discount).
    if (card.marketPrice <= 0) {
      continue;
    }
    if (card.value < card.marketPrice * (thresholdPercent / 100)) {
      flaggedCards.push({
        id: card.id,
        name: card.name,
        set: card.set,
        listedPrice: card.value,
        marketPrice: card.marketPrice,
        discountPercent: ((card.marketPrice - card.value) / card.marketPrice) * 100,
      });
    }
  }

  return { flaggedCards, thresholdPercent };
}
