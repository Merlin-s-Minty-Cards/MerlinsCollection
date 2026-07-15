import { describe, expect, it } from "vitest";
import { flagUnderpricedCards } from "../../tools/flag-underpriced-cards.js";
import { card } from "../fixtures/card.js";
import { InMemoryInventoryRepository } from "../fixtures/in-memory-repository.js";

const seed = () =>
  new InMemoryInventoryRepository([
    card({ id: "c1", name: "Charizard", value: 70, marketPrice: 100 }), // 70% of market
    card({ id: "c2", name: "Blastoise", value: 95, marketPrice: 100 }), // 95% of market
    card({ id: "c3", name: "Pikachu", value: 100, marketPrice: 100 }), // at market
    card({ id: "c4", name: "Mewtwo", value: 120, marketPrice: 100 }), // above market
    card({ id: "c5", name: "Corrupt", value: -5, marketPrice: 0 }), // non-positive market price
  ]);

const ids = (cards: Array<{ id: string }>) => cards.map((c) => c.id);

describe("flagUnderpricedCards", () => {
  it("flags cards listed below the threshold percentage of market price", async () => {
    const result = await flagUnderpricedCards(seed(), 80);

    expect(ids(result.flaggedCards)).toEqual(["c1"]); // only Charizard is below 80% of market
    expect(result.flaggedCards[0]).toEqual({
      id: "c1",
      name: "Charizard",
      set: "Base Set",
      listedPrice: 70,
      marketPrice: 100,
      discountPercent: 30,
    });
  });

  it("does not flag cards at or above market price", async () => {
    const result = await flagUnderpricedCards(seed(), 100);

    const flaggedIds = ids(result.flaggedCards);
    expect(flaggedIds).not.toContain("c3"); // at market
    expect(flaggedIds).not.toContain("c4"); // above market
  });

  it("does not flag a card listed exactly at the threshold (strict less-than)", async () => {
    const repo = new InMemoryInventoryRepository([
      card({ id: "boundary", value: 80, marketPrice: 100 }), // exactly 80% of market
    ]);

    const result = await flagUnderpricedCards(repo, 80);

    expect(result.flaggedCards).toEqual([]);
  });

  it("includes the (unrounded) discount percentage on each flagged card", async () => {
    const repo = new InMemoryInventoryRepository([
      card({ id: "frac", value: 70, marketPrice: 110 }), // discount = 40/110*100 = 36.3636...
    ]);

    const result = await flagUnderpricedCards(repo, 80);

    const discount = result.flaggedCards[0]?.discountPercent ?? 0;
    expect(discount).toBeCloseTo(36.3636, 3);
    expect(Number.isInteger(discount)).toBe(false); // not rounded
  });

  it("returns an empty array when no cards are underpriced", async () => {
    const result = await flagUnderpricedCards(seed(), 50);

    expect(result.flaggedCards).toEqual([]);
  });

  it("respects a custom threshold percentage", async () => {
    const at80 = await flagUnderpricedCards(seed(), 80);
    const at96 = await flagUnderpricedCards(seed(), 96);

    expect(ids(at80.flaggedCards)).not.toContain("c2"); // 95% is not below 80%
    expect(ids(at96.flaggedCards)).toContain("c2"); // 95% is below 96%
    expect(at96.thresholdPercent).toBe(96);
  });

  it("ignores cards with a non-positive market price", async () => {
    const result = await flagUnderpricedCards(seed(), 80);

    expect(ids(result.flaggedCards)).not.toContain("c5");
  });
});
