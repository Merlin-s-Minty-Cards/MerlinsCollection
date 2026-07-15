import { describe, expect, it } from "vitest";
import { searchInventory } from "../../tools/search-inventory.js";
import { card } from "../fixtures/card.js";
import { InMemoryInventoryRepository } from "../fixtures/in-memory-repository.js";

const seed = () =>
  new InMemoryInventoryRepository([
    card({ id: "1", name: "Charizard", set: "Base Set", condition: "Near Mint", value: 500 }),
    card({ id: "2", name: "Blastoise", set: "Base Set", condition: "Lightly Played", value: 300 }),
    card({ id: "3", name: "Pikachu", set: "Jungle", condition: "Near Mint", quantity: 3, value: 20 }),
    card({ id: "4", name: "Charizard", set: "Jungle", condition: "Near Mint", value: 150 }),
  ]);

const ids = (cards: Array<{ id: string }>) => cards.map((c) => c.id);

describe("searchInventory", () => {
  it("returns all cards when no filters are provided", async () => {
    const result = await searchInventory(seed(), {});

    expect(result).toEqual([
      { id: "1", name: "Charizard", set: "Base Set", condition: "Near Mint", quantity: 1, currentValue: 500 },
      { id: "2", name: "Blastoise", set: "Base Set", condition: "Lightly Played", quantity: 1, currentValue: 300 },
      { id: "3", name: "Pikachu", set: "Jungle", condition: "Near Mint", quantity: 3, currentValue: 20 },
      { id: "4", name: "Charizard", set: "Jungle", condition: "Near Mint", quantity: 1, currentValue: 150 },
    ]);
  });

  it("filters by card name (case-insensitive substring)", async () => {
    const result = await searchInventory(seed(), { name: "char" });

    expect(ids(result)).toEqual(["1", "4"]);
  });

  it("filters by set (case-insensitive)", async () => {
    const result = await searchInventory(seed(), { set: "base set" });

    expect(ids(result)).toEqual(["1", "2"]);
  });

  it("filters by condition (case-insensitive)", async () => {
    const result = await searchInventory(seed(), { condition: "lightly played" });

    expect(ids(result)).toEqual(["2"]);
  });

  it("filters by value range inclusively", async () => {
    const result = await searchInventory(seed(), { minValue: 100, maxValue: 400 });

    expect(ids(result)).toEqual(["2", "4"]); // 300 and 150; excludes 500 and 20
  });

  it("filters value range by per-unit value, not holding value", async () => {
    const repo = new InMemoryInventoryRepository([
      card({ id: "x", value: 150, quantity: 100 }), // unit 150 is in range; holding 15000 is not
    ]);

    const result = await searchInventory(repo, { minValue: 100, maxValue: 400 });

    expect(ids(result)).toEqual(["x"]);
  });

  it("returns empty when the value range is inverted (min greater than max)", async () => {
    const result = await searchInventory(seed(), { minValue: 400, maxValue: 100 });

    expect(result).toEqual([]);
  });

  it("applies multiple filters with AND semantics", async () => {
    const result = await searchInventory(seed(), { name: "char", set: "Jungle" });

    expect(ids(result)).toEqual(["4"]); // Charizard in Jungle only, not the Base Set Charizard
  });

  it("returns empty array when no cards match filters", async () => {
    const result = await searchInventory(seed(), { name: "Mewtwo" });

    expect(result).toEqual([]);
  });
});
