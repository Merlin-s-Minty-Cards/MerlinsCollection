/**
 * Condition multipliers — a direct port of the backend's
 * `services/condition_pricing.py`.
 *
 * The catalog relays ONE market figure per finish and that figure is a Near Mint
 * price, so a Lightly Played card must not be quoted at the same number. The
 * backend applies this multiplier on the customer search path and in
 * `/inventory/summary`; chat mode reads DynamoDB directly and therefore has to
 * apply it itself, or the same card is priced two different ways depending on
 * which half of `/inventory` the customer is looking at.
 *
 * **This table is duplicated, not shared, and that is a known seam.** The
 * multipliers were researched and OWNER-APPROVED 2026-07-30 and have not moved
 * since.
 *
 * They are pinned across the seam by
 * `backend/tests/test_cross_boundary.py::test_condition_multipliers_match` and
 * `::test_condition_tier_order_matches`, which parse THIS file and compare it
 * to `services/condition_pricing.py`. Both are mutation-tested. If a tier is
 * ever re-tuned, both files change together or the backend suite goes red.
 *
 * **Until 2026-08-27 this paragraph claimed that pinning existed when it did
 * not** — `test_cross_boundary.py` covered the shard count, customer-visible
 * locations, the finish fallback order and the image-host allowlist, and not
 * these multipliers. Each side had only its own test with independently
 * hardcoded numbers, so re-tuning Python and its own test would have gone
 * green with this file stale, pricing the same card two ways depending on
 * which half of /inventory the customer was looking at. A comment asserting a
 * safety property is not the property; if you rely on one, go read the test it
 * names. See docs/plans/rfc-0008/follow-ups.md on the wider "vocabulary
 * declared in three places" problem.
 */

/** Anchor: NM = 1.00 — the catalog market figure IS a NM price. */
const TIER_MULTIPLIERS: Record<string, number> = {
  NM: 1.0,
  LP: 0.82,
  MP: 0.58,
  HP: 0.33,
  DMG: 0.15,
};

/** Best to worst, for the midpoint a `+`/`-` modifier resolves to. */
const TIER_ORDER = ["NM", "LP", "MP", "HP", "DMG"];

/** Round half-up to cents, matching Python's ROUND_HALF_UP quantize. */
function round2(value: number): number {
  return Math.round((value + Number.EPSILON) * 100) / 100;
}

/**
 * The multiplier for a condition tier plus optional modifier.
 *
 * `+` is the midpoint between this tier and the one above, `-` the midpoint
 * with the one below. NM+ clamps to NM and DMG- clamps to DMG (no tier beyond).
 * An unrecognized tier returns `null` — the caller then leaves the price alone
 * rather than silently defaulting to 1.0, which would quote a damaged card at
 * its NM figure.
 */
export function conditionMultiplier(
  condition: string | null | undefined,
  modifier?: string | null,
): number | null {
  if (condition == null) return null;
  const tier = String(condition).toUpperCase();
  const base = TIER_MULTIPLIERS[tier];
  if (base === undefined) return null;
  if (modifier !== "+" && modifier !== "-") return base;

  const idx = TIER_ORDER.indexOf(tier);
  const neighbourTier = TIER_ORDER[modifier === "+" ? idx - 1 : idx + 1];
  // NM+ / DMG- have no neighbour to average with; clamp to the tier itself.
  if (neighbourTier === undefined) return base;
  const neighbour = TIER_MULTIPLIERS[neighbourTier];
  if (neighbour === undefined) return base;
  return round2((base + neighbour) / 2);
}

/**
 * Scale a raw card's NM catalog figure by its condition.
 *
 * Returns the price unchanged when the condition is unknown, so a bad or
 * missing tier can never invent a discount.
 */
export function applyConditionAdjustment(
  marketPrice: number,
  condition: string | null | undefined,
  modifier?: string | null,
): number {
  const mult = conditionMultiplier(condition, modifier);
  if (mult === null) return marketPrice;
  return round2(marketPrice * mult);
}
