import type { InventoryRepository } from "../repository.js";

/**
 * Optional filters for {@link searchInventory}. Every provided filter must match
 * (AND semantics); omitted filters are ignored.
 */
export type SearchFilters = {
  /** Case-insensitive substring match against the card name. */
  name?: string;
  /** Case-insensitive exact match against the set. */
  set?: string;
  /** Case-insensitive exact match against the condition. */
  condition?: string;
  /** Inclusive lower bound on per-unit value. */
  minValue?: number;
  /** Inclusive upper bound on per-unit value. */
  maxValue?: number;
};

/** A single card as returned to search callers (the frontend's `currentValue` shape). */
export type CardResult = {
  id: string;
  name: string;
  set: string;
  condition: string;
  quantity: number;
  /** Per-unit listed value (mirrors `Card.value`). */
  currentValue: number;
};

/**
 * Returns the cards matching every provided filter (AND semantics); omitted
 * filters are ignored, so an empty `filters` object returns every card. Name
 * matching is a case-insensitive substring; set and condition are
 * case-insensitive exact matches; `minValue`/`maxValue` bound the per-unit value
 * inclusively (an inverted range simply matches nothing).
 */
export async function searchInventory(
  repo: InventoryRepository,
  filters: SearchFilters,
): Promise<CardResult[]> {
  const cards = await repo.listCards();

  const matches = cards.filter((card) => {
    if (
      filters.name !== undefined &&
      !card.name.toLowerCase().includes(filters.name.toLowerCase())
    ) {
      return false;
    }
    if (filters.set !== undefined && card.set.toLowerCase() !== filters.set.toLowerCase()) {
      return false;
    }
    if (
      filters.condition !== undefined &&
      card.condition.toLowerCase() !== filters.condition.toLowerCase()
    ) {
      return false;
    }
    if (filters.minValue !== undefined && card.value < filters.minValue) {
      return false;
    }
    if (filters.maxValue !== undefined && card.value > filters.maxValue) {
      return false;
    }
    return true;
  });

  return matches.map((card) => ({
    id: card.id,
    name: card.name,
    set: card.set,
    condition: card.condition,
    quantity: card.quantity,
    currentValue: card.value,
  }));
}
