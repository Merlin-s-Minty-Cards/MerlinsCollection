/**
 * Hand valuation — what a card is worth when the catalog has never heard of it.
 * docs/plans/rfc-0010/t16-unmatched-card-valuation.md
 *
 * The owner's question: *"what do we do when we have a card that doesn't have a
 * matching catalog card? We still are selling it and we need a price for it as
 * well as updating the sticker."*
 *
 * The capability already existed and nothing said so.
 * `refresh_inventory_market_values` opens with `if item.kind not in ("raw",
 * "graded") or item.card_id is None: continue`, so a figure typed onto an
 * unlinked item is never overwritten by the nightly denormalizer. That is the
 * load-bearing fact — without it, hand valuation would be a number that
 * disappears overnight.
 */

/**
 * Every admin row shape carries an index signature (`TriageItem`,
 * `PrepQueueItem`, the modal's `shown`), so this is the one type all of them
 * satisfy without a cast at the call site.
 */
export type ValuableItem = Record<string, unknown>

/**
 * Whether this item's value can only ever come from a human.
 *
 * DERIVED from the absence of a catalog link, never stored — a `manually_valued`
 * boolean would go stale the moment somebody re-points the card, which is the
 * same self-healing discipline Triage's reasons follow.
 *
 * Keyed on `card_id` alone, and deliberately not on "has a value AND no link":
 * the row that most needs the marker is the one that is *still blank*, where the
 * honest reading of an empty Market column is "no sync will ever fill this in",
 * not "the price has not synced yet". Sealed and bulk items have no `card_id` at
 * all and are correctly included — their values have always been hand-set.
 *
 * This matches the nightly job's skip condition exactly, which is what keeps the
 * marker true rather than merely plausible.
 */
export function isHandValued(item: ValuableItem | null | undefined): boolean {
  return item != null && !item.card_id
}

/**
 * The condition multiplier the SERVER computed for this row, or `null`.
 *
 * `services/condition_pricing.py` is the authority and `_serialize_item` sends
 * its answer as `condition_multiplier`. The table is deliberately NOT mirrored
 * here: it already has one duplicate (`mcp-server/src/condition-pricing.ts`) and
 * a third copy is how a re-tuned tier starts quoting two different prices for
 * one card.
 */
export function conditionMultiplierOf(
  item: ValuableItem | null | undefined,
): number | null {
  const raw = item?.condition_multiplier
  if (raw == null) return null
  const n = typeof raw === 'number' ? raw : Number(raw)
  return Number.isFinite(n) ? n : null
}

/**
 * Today, in the LOCAL zone.
 *
 * Not `toISOString().split('T')[0]`, which is the UTC date: measured at 6:30pm
 * Pacific on Aug 10 it yields `2026-08-11`, so an evening show stamps tomorrow.
 * T8 replaces every instance of that across the admin and will own a shared
 * helper; this is the one date T16 writes, and it is not going in wrong first.
 */
export function localToday(now: Date = new Date()): string {
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const day = String(now.getDate()).padStart(2, '0')
  return `${now.getFullYear()}-${month}-${day}`
}
