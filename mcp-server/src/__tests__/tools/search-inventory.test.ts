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

const langSeed = () =>
  new InMemoryInventoryRepository([
    card({ id: "en", name: "Charizard", language: "EN" }),
    card({ id: "jp", name: "Charizard", language: "JP" }),
  ]);

const ids = (cards: Array<{ id: string }>) => cards.map((c) => c.id);

describe("searchInventory", () => {
  it("returns all cards when no filters are provided", async () => {
    const result = await searchInventory(seed(), {});

    expect(result).toEqual([
      { id: "1", item_id: "item-1", name: "Charizard", set: "Base Set", condition: "Near Mint", quantity: 1, currentValue: 500, marketPrice: 500, language: "EN" },
      { id: "2", item_id: "item-2", name: "Blastoise", set: "Base Set", condition: "Lightly Played", quantity: 1, currentValue: 300, marketPrice: 300, language: "EN" },
      { id: "3", item_id: "item-3", name: "Pikachu", set: "Jungle", condition: "Near Mint", quantity: 3, currentValue: 20, marketPrice: 20, language: "EN" },
      { id: "4", item_id: "item-4", name: "Charizard", set: "Jungle", condition: "Near Mint", quantity: 1, currentValue: 150, marketPrice: 150, language: "EN" },
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

  // RFC 0008 §D (T3): a card with no resolvable price carries a null value, and
  // a null cannot be compared against a bound. Left to JS coercion the two bounds
  // would disagree — `null < min` is true (excluded) but `null > max` is false
  // (kept, and returned with currentValue: null). A priced bound excludes it,
  // mirroring the backend's hidden_no_price behaviour on /inventory/search.
  it("excludes a card with no resolvable price from either value bound", async () => {
    const repo = new InMemoryInventoryRepository([
      card({ id: "priced", value: 150, marketPrice: 150 }),
      card({ id: "unpriced", value: null, marketPrice: null }),
    ]);

    expect(ids(await searchInventory(repo, { maxValue: 400 }))).toEqual(["priced"]);
    expect(ids(await searchInventory(repo, { minValue: 100 }))).toEqual(["priced"]);
    // With no bound at all it is still inventory and must still be listed.
    expect(ids(await searchInventory(repo, {}))).toEqual(["priced", "unpriced"]);
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

  it("carries the card's language on each result", async () => {
    const result = await searchInventory(langSeed(), {});

    expect(result.map((r) => r.language).sort()).toEqual(["EN", "JP"]);
  });

  it("filters by language (case-insensitive)", async () => {
    expect(ids(await searchInventory(langSeed(), { language: "JP" }))).toEqual(["jp"]);
    expect(ids(await searchInventory(langSeed(), { language: "en" }))).toEqual(["en"]);
  });

  it("AND-combines a language filter with the other filters", async () => {
    // Both Charizards, one EN one JP; name+language must both match.
    const result = await searchInventory(langSeed(), { name: "char", language: "JP" });

    expect(ids(result)).toEqual(["jp"]);
  });

  // --- LP+/LP- condition modifier filtering (Task 3.7) ---

  describe("LP+/LP- condition modifier filtering", () => {
    const conditionSeed = () =>
      new InMemoryInventoryRepository([
        card({ id: "lp-plain", name: "Bulbasaur", condition: "LP" }),
        card({ id: "lp-plus", name: "Ivysaur", condition: "LP+" }),
        card({ id: "lp-minus", name: "Venusaur", condition: "LP-" }),
        card({ id: "nm", name: "Charmander", condition: "NM" }),
        card({ id: "mp", name: "Squirtle", condition: "MP" }),
      ]);

    it("searching 'LP+' matches only LP+ items", async () => {
      const result = await searchInventory(conditionSeed(), { condition: "LP+" });

      expect(ids(result)).toEqual(["lp-plus"]);
    });

    it("searching 'LP-' matches only LP- items", async () => {
      const result = await searchInventory(conditionSeed(), { condition: "LP-" });

      expect(ids(result)).toEqual(["lp-minus"]);
    });

    it("searching plain 'LP' matches all LP tiers (LP, LP+, LP-)", async () => {
      const result = await searchInventory(conditionSeed(), { condition: "LP" });

      expect(ids(result)).toEqual(["lp-plain", "lp-plus", "lp-minus"]);
    });

    it("searching 'NM' still works as exact match when no modifier exists", async () => {
      const result = await searchInventory(conditionSeed(), { condition: "NM" });

      expect(ids(result)).toEqual(["nm"]);
    });

    it("condition modifier filtering is case-insensitive", async () => {
      const result = await searchInventory(conditionSeed(), { condition: "lp+" });

      expect(ids(result)).toEqual(["lp-plus"]);
    });

    it("plain tier search is case-insensitive and matches all tiers", async () => {
      const result = await searchInventory(conditionSeed(), { condition: "lp" });

      expect(ids(result)).toEqual(["lp-plain", "lp-plus", "lp-minus"]);
    });
  });
});
