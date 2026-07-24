import { describe, expect, it } from "vitest";
import { calculateInventoryValue } from "../../tools/calculate-inventory-value.js";
import { card } from "../fixtures/card.js";
import { InMemoryInventoryRepository } from "../fixtures/in-memory-repository.js";

const seed = () =>
  new InMemoryInventoryRepository([
    card({ id: "1", set: "Base Set", condition: "Near Mint", quantity: 1, value: 500 }),
    card({ id: "2", set: "Base Set", condition: "Lightly Played", quantity: 2, value: 300 }),
    card({ id: "3", set: "Jungle", condition: "Near Mint", quantity: 3, value: 20 }),
    card({ id: "4", set: "Fossil", condition: "Damaged", quantity: 5, value: 0 }), // zero-value card
  ]);

describe("calculateInventoryValue", () => {
  it("calculates total value across all cards (unit value x quantity)", async () => {
    const result = await calculateInventoryValue(seed());

    expect(result.totalValue).toBeCloseTo(1160); // 500 + 600 + 60 + 0
  });

  it("breaks down value by set, including zero-value sets", async () => {
    const result = await calculateInventoryValue(seed());

    expect(result.valueBySet).toEqual({
      "Base Set": 1100, // 500 + 600
      Jungle: 60,
      Fossil: 0,
    });
  });

  it("breaks down value by condition, including zero-value conditions", async () => {
    const result = await calculateInventoryValue(seed());

    expect(result.valueByCondition).toEqual({
      "Near Mint": 560, // 500 + 60
      "Lightly Played": 600,
      Damaged: 0,
    });
  });

  it("includes a valid ISO-8601 timestamp on the result", async () => {
    const result = await calculateInventoryValue(seed());

    expect(result.calculatedAt).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$/);
    expect(Number.isNaN(Date.parse(result.calculatedAt))).toBe(false);
  });

  it("returns zero and empty breakdowns for an empty inventory", async () => {
    const result = await calculateInventoryValue(new InMemoryInventoryRepository([]));

    expect(result.totalValue).toBe(0);
    expect(result.valueBySet).toEqual({});
    expect(result.valueByCondition).toEqual({});
  });

  it("values a JP card at its listed/sheet value, not its (0) English market", async () => {
    // A JP print has no English market price (marketPrice 0), but it still has a
    // real listed value from the sheet — it must count that, not $0.
    const repo = new InMemoryInventoryRepository([
      card({ id: "jp", language: "JP", value: 250, marketPrice: 0, set: "Japanese Base" }),
    ]);

    const result = await calculateInventoryValue(repo);

    expect(result.totalValue).toBe(250);
    expect(result.valueBySet["Japanese Base"]).toBe(250);
  });
});
