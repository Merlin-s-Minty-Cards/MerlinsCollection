import { describe, expect, it } from "vitest";
import type { Card, PricePoint } from "../../repository.js";
import { getCardPriceHistory } from "../../tools/get-card-price-history.js";
import { card } from "../fixtures/card.js";
import { InMemoryInventoryRepository } from "../fixtures/in-memory-repository.js";

const cards: Card[] = [card({ id: "1", name: "Charizard" }), card({ id: "2", name: "Blastoise" })];

// Intentionally out of chronological order to prove the tool sorts.
const charizardHistory: PricePoint[] = [
  { date: "2026-03-01", price: 500, source: "eBay" },
  { date: "2026-01-15", price: 480, source: "TCGplayer" },
  { date: "2026-02-10", price: 490, source: "PriceCharting" },
];

const seed = () =>
  new InMemoryInventoryRepository(
    cards,
    new Map<string, PricePoint[]>([
      ["1", charizardHistory],
      ["2", []],
    ]),
  );

describe("getCardPriceHistory", () => {
  it("returns price history for a known card id", async () => {
    const result = await getCardPriceHistory(seed(), "1");

    expect(result.cardId).toBe("1");
    expect(result.cardName).toBe("Charizard");
    expect(result.history).toHaveLength(3);
  });

  it("returns history sorted chronologically (ascending)", async () => {
    const result = await getCardPriceHistory(seed(), "1");

    expect(result.history.map((point) => point.date)).toEqual([
      "2026-01-15",
      "2026-02-10",
      "2026-03-01",
    ]);
  });

  it("preserves input order for price points on the same date", async () => {
    const repo = new InMemoryInventoryRepository(
      [card({ id: "1", name: "Charizard" })],
      new Map<string, PricePoint[]>([
        [
          "1",
          [
            { date: "2026-02-01", price: 500, source: "eBay" },
            { date: "2026-02-01", price: 510, source: "TCGplayer" },
          ],
        ],
      ]),
    );

    const result = await getCardPriceHistory(repo, "1");

    expect(result.history.map((point) => point.source)).toEqual(["eBay", "TCGplayer"]);
  });

  it("includes a data source on each price point", async () => {
    const result = await getCardPriceHistory(seed(), "1");

    expect(result.history.map((point) => point.source)).toEqual([
      "TCGplayer",
      "PriceCharting",
      "eBay",
    ]);
  });

  it("returns empty history for a known card with no price points", async () => {
    const result = await getCardPriceHistory(seed(), "2");

    expect(result).toEqual({ cardId: "2", cardName: "Blastoise", history: [] });
  });

  it("throws when the card id does not exist", async () => {
    await expect(getCardPriceHistory(seed(), "999")).rejects.toThrow(/not found/i);
  });
});
