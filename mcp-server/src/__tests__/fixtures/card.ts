import type { Card } from "../../repository.js";

/**
 * Builds a Card with sensible defaults; pass overrides for the fields a test
 * cares about. When only one of `value`/`marketPrice` is provided, the other
 * defaults to match (since listed_price is dead, they are normally the same).
 * When BOTH are explicitly provided, they are kept distinct — tests for
 * `flag_underpriced_cards` rely on this to simulate a value/market discrepancy.
 * Either may be `null` to stand for a card whose price could not be resolved
 * from any source (RFC 0008 §D) — distinct from a genuine 0.
 */
export const card = (overrides: Partial<Card> = {}): Card => {
  const hasValue = "value" in overrides;
  const hasMarket = "marketPrice" in overrides;
  let value: number | null;
  let marketPrice: number | null;

  if (hasValue && hasMarket) {
    // Both explicitly set — keep them distinct (needed for underpriced-card tests).
    value = overrides.value ?? null;
    marketPrice = overrides.marketPrice ?? null;
  } else if (hasValue) {
    value = overrides.value ?? null;
    marketPrice = overrides.value ?? null;
  } else if (hasMarket) {
    value = overrides.marketPrice ?? null;
    marketPrice = overrides.marketPrice ?? null;
  } else {
    value = 12;
    marketPrice = 12;
  }

  return {
    id: overrides.id ?? "id",
    itemId: overrides.itemId ?? `item-${overrides.id ?? "id"}`,
    name: overrides.name ?? "Card",
    set: overrides.set ?? "Base Set",
    condition: overrides.condition ?? "Near Mint",
    quantity: overrides.quantity ?? 1,
    value,
    marketPrice,
    language: overrides.language ?? "EN",
  };
};
