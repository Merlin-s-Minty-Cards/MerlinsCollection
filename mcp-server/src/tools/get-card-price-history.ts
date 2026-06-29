import type { InventoryRepository, PricePoint } from "../repository.js";

// Re-exported so existing direct importers of this module keep working after the
// canonical definition moved to repository.ts.
export type { PricePoint } from "../repository.js";

export type PriceHistoryResult = {
  cardId: string;
  cardName: string;
  /** Price points ordered oldest-to-newest. */
  history: PricePoint[];
};

/**
 * Returns a card's price history sorted chronologically (oldest first). Price
 * points sharing the same date keep their original repository order (the sort is
 * stable). Throws an `Error` if no card has the given id.
 */
export async function getCardPriceHistory(
  repo: InventoryRepository,
  cardId: string,
): Promise<PriceHistoryResult> {
  const cards = await repo.listCards();
  const card = cards.find((c) => c.id === cardId);
  if (card === undefined) {
    throw new Error(`Card not found: ${cardId}`);
  }

  const history = await repo.getPriceHistory(cardId);
  const sorted = [...history].sort((a, b) => Date.parse(a.date) - Date.parse(b.date));

  return { cardId, cardName: card.name, history: sorted };
}
