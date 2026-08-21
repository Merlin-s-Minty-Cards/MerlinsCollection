/**
 * The name an admin sees for an inventory item — the ONE place that decides it.
 *
 * Every admin surface used to inline `display_name || product_name || name`,
 * which meant none of them knew about `display_name_override`. An admin could
 * type an English name for a Japanese card in Triage, watch the customer site
 * update, and still see the Japanese name everywhere in the admin panel —
 * reading exactly like an edit that failed to save (RFC 0008 follow-up, T10
 * row 2; owner decision 2026-08-06: the override wins everywhere).
 *
 * Mirrors `itemTitle` in `lib/inventory.ts`, which does the same job for the
 * customer tile. The two are kept deliberately separate because the fallback
 * chains differ — the customer side has an enriched `card.name` from the catalog
 * join, the admin list responses generally do not — but the FIRST rung, the
 * override, must be identical on both.
 */

/** The name-bearing fields an admin list row may carry. All optional: the admin
 *  endpoints return several different item shapes. */
export type AdminNamedItem = {
  display_name_override?: string | null
  display_name?: string | null
  product_name?: string | null
  name?: string | null
  card_id?: string | null
  item_id?: string | null
}

/**
 * Resolve the admin-facing name.
 *
 * Order: the admin's own override, then the import-materialized `display_name`,
 * then a sealed product's `product_name`, then a catalog `name` if the response
 * carried one, then the card id, and `fallback` only when nothing else exists.
 *
 * The override is checked with a trim, not `??` or `||` on the raw value: a
 * whitespace-only override would otherwise render a blank, nameless row.
 */
export function adminItemName(
  item: AdminNamedItem | null | undefined,
  fallback = '(unnamed)',
): string {
  if (!item) return fallback
  const override = item.display_name_override?.trim()
  if (override) return override
  return (
    item.display_name || item.product_name || item.name || item.card_id || fallback
  )
}
