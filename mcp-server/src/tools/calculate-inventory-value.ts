import type { InventoryRepository } from "../repository.js";

export type InventoryValueResult = {
  /** Total holding value across all cards (sum of per-unit value x quantity). */
  totalValue: number;
  /** Holding value grouped by set; every set present is a key, even at zero. */
  valueBySet: Record<string, number>;
  /** Holding value grouped by condition; every condition present is a key, even at zero. */
  valueByCondition: Record<string, number>;
  /** ISO-8601 timestamp of when this valuation was computed. */
  calculatedAt: string;
};

/**
 * Computes the full holding value of the inventory (per-unit value x quantity),
 * along with breakdowns grouped by set and by condition. Every set and condition
 * that appears is included in its breakdown, even when its subtotal is zero.
 */
export async function calculateInventoryValue(
  repo: InventoryRepository,
): Promise<InventoryValueResult> {
  const cards = await repo.listCards();

  let totalValue = 0;
  const valueBySet: Record<string, number> = {};
  const valueByCondition: Record<string, number> = {};

  for (const card of cards) {
    const holdingValue = card.value * card.quantity;
    totalValue += holdingValue;
    valueBySet[card.set] = (valueBySet[card.set] ?? 0) + holdingValue;
    valueByCondition[card.condition] = (valueByCondition[card.condition] ?? 0) + holdingValue;
  }

  return {
    totalValue,
    valueBySet,
    valueByCondition,
    calculatedAt: new Date().toISOString(),
  };
}
