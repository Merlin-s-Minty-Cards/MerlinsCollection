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
 * since; they are pinned on both sides by tests so a silent divergence fails
 * loudly rather than mispricing stock. If a tier is ever re-tuned, both files
 * change together — see docs/plans/rfc-0008/follow-ups.md on the wider
 * "vocabulary declared in three places" problem.
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
