export type InventorySummaryResult = {
  totalCards: number;
  totalValue: number;
  uniqueSets: number;
  topValuedCards: Array<{ name: string; value: number }>;
};

export async function getInventorySummary(): Promise<InventorySummaryResult> {
  throw new Error("Not implemented");
}
