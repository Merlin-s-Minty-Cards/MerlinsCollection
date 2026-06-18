export type UnderpricedCard = {
  id: string;
  name: string;
  set: string;
  listedPrice: number;
  marketPrice: number;
  discountPercent: number;
};

export type FlagUnderpricedResult = {
  flaggedCards: UnderpricedCard[];
  thresholdPercent: number;
};

export async function flagUnderpricedCards(thresholdPercent: number): Promise<FlagUnderpricedResult> {
  throw new Error("Not implemented");
}
