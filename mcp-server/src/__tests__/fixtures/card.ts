import type { Card } from "../../repository.js";

/** Builds a Card with sensible defaults; pass overrides for the fields a test cares about. */
export const card = (overrides: Partial<Card> = {}): Card => ({
  id: "id",
  name: "Card",
  set: "Base Set",
  condition: "Near Mint",
  quantity: 1,
  value: 10,
  marketPrice: 12,
  language: "EN",
  ...overrides,
});
