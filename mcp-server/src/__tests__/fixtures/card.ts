import type { Card } from "../../repository.js";

/**
 * Builds a Card with sensible defaults; pass overrides for the fields a test
 * cares about. When only one of `value`/`marketPrice` is provided, the other
 * defaults to match (since listed_price is dead, they are normally the same).
 * When BOTH are explicitly provided, they are kept distinct — tests for
 * `flag_underpriced_cards` rely on this to simulate a value/market discrepancy.
 */
export const card = (overrides: Partial<Card> = {}): Card => {
  const hasValue = "value" in overrides;
  const hasMarket = "marketPrice" in overrides;
  let value: number;
  let marketPrice: number;

  if (hasValue && hasMarket) {
    // Both explicitly set — keep them distinct (needed for underpriced-card tests).
    value = overrides.value!;
    marketPrice = overrides.marketPrice!;
  } else if (hasValue) {
    value = overrides.value!;
    marketPrice = overrides.value!;
  } else if (hasMarket) {
    value = overrides.marketPrice!;
    marketPrice = overrides.marketPrice!;
  } else {
    value = 12;
    marketPrice = 12;
  }

  return {
    id: overrides.id ?? "id",
    name: overrides.name ?? "Card",
    set: overrides.set ?? "Base Set",
    condition: overrides.condition ?? "Near Mint",
    quantity: overrides.quantity ?? 1,
    value,
    marketPrice,
    language: overrides.language ?? "EN",
  };
};
