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
  /** Case-insensitive exact match against the print language (EN/JP). */
  language?: string;
};

/** A single card as returned to search callers (the frontend's `currentValue` shape). */
export type CardResult = {
  id: string;
  /**
   * Per-unit inventory item ID (RFC 0016 checklist item 1). Snake_case,
   * unlike the rest of this shape's camelCase fields, to match what the
   * display tools (`display_card`/`set_display`) accept as input — the
   * model round-trips this exact field name from the search result straight
   * into a display-tool call.
   */
  item_id: string;
  name: string;
  set: string;
  condition: string;
  quantity: number;
  /** Per-unit market value; `null` when no price could be resolved for the card. */
  currentValue: number | null;
  /** Per-unit market price (same as currentValue — kept for backward compat). */
  marketPrice: number | null;
  /** Print language (EN/JP) — lets the model distinguish a JP print from its EN twin. */
  language: "EN" | "JP";
};

/**
 * LP+/LP- aware condition matching. When the filter includes a modifier
 * ("LP+", "LP-"), only that exact tier+modifier matches. When the filter is
 * a bare tier ("LP"), all variants of that tier match (LP, LP+, LP-).
 * Comparison is case-insensitive.
 */
function conditionMatches(cardCondition: string, filterCondition: string): boolean {
  const filter = filterCondition.trim();
  const lastChar = filter.slice(-1);
  const hasModifier = lastChar === "+" || lastChar === "-";

  if (hasModifier) {
    // Exact match: "LP+" must match only "LP+"
    return cardCondition.toLowerCase() === filter.toLowerCase();
  }

  // Bare tier: "LP" matches "LP", "LP+", "LP-"
  const cardLower = cardCondition.toLowerCase();
  const tierLower = filter.toLowerCase();
  if (!cardLower.startsWith(tierLower)) return false;
  const remainder = cardLower.slice(tierLower.length);
  return remainder === "" || remainder === "+" || remainder === "-";
}

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
    if (filters.condition !== undefined && !conditionMatches(card.condition, filters.condition)) {
      return false;
    }
    // A card with no resolvable price cannot satisfy a bound, so any bound at
    // all excludes it. This must be explicit: left to JS coercion the two bounds
    // would disagree — `null < min` is true (excluded) but `null > max` is false
    // (kept, and returned with a null currentValue). Mirrors the backend's
    // hidden_no_price behaviour on /inventory/search.
    if (filters.minValue !== undefined || filters.maxValue !== undefined) {
      if (card.marketPrice == null) return false;
      if (filters.minValue !== undefined && card.marketPrice < filters.minValue) return false;
      if (filters.maxValue !== undefined && card.marketPrice > filters.maxValue) return false;
    }
    if (
      filters.language !== undefined &&
      card.language.toLowerCase() !== filters.language.toLowerCase()
    ) {
      return false;
    }
    return true;
  });

  return matches.map((card) => ({
    id: card.id,
    item_id: card.itemId,
    name: card.name,
    set: card.set,
    condition: card.condition,
    quantity: card.quantity,
    currentValue: card.marketPrice,
    marketPrice: card.marketPrice,
    language: card.language,
  }));
}
