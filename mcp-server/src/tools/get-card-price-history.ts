export type PricePoint = {
  date: string;
  price: number;
  source: string;
};

export type PriceHistoryResult = {
  cardId: string;
  cardName: string;
  history: PricePoint[];
};

export async function getCardPriceHistory(cardId: string): Promise<PriceHistoryResult> {
  throw new Error("Not implemented");
}
