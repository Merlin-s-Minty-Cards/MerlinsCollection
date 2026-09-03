/**
 * Shared constants for admin UI dropdowns.
 * Condition options include modifier variants (LP+, LP-) that map to
 * separate condition + condition_modifier fields on the backend.
 */

/** All selectable condition values for admin forms. */
export const CONDITION_OPTIONS = [
  'NM',
  'LP+',
  'LP',
  'LP-',
  'MP',
  'HP',
  'DMG',
] as const

/**
 * Parse a combined condition string (e.g. "LP+") into the backend's
 * separate condition and condition_modifier fields.
 */
export function parseCondition(value: string): {
  condition: string
  condition_modifier: string | null
} {
  if (value.endsWith('+')) {
    return { condition: value.slice(0, -1), condition_modifier: '+' }
  }
  if (value.endsWith('-')) {
    return { condition: value.slice(0, -1), condition_modifier: '-' }
  }
  return { condition: value, condition_modifier: null }
}

/**
 * Format a condition + modifier pair back into a display string.
 */
export function formatCondition(
  condition: string,
  modifier?: string | null,
): string {
  return `${condition}${modifier ?? ''}`
}

/** Predefined inventory locations (mirrors backend InventoryLocation enum). */
export const LOCATION_OPTIONS = [
  { value: 'glass', label: 'Glass' },
  { value: 'toploader', label: 'Toploader' },
  { value: 'binder', label: 'Binder' },
  { value: 'storage', label: 'Storage' },
  { value: 'show_box_a', label: 'Show Box A' },
  { value: 'show_box_b', label: 'Show Box B' },
  { value: 'display_case', label: 'Display Case' },
  { value: 'grading_pile', label: 'Grading Pile' },
  { value: 'sold_pile', label: 'Sold Pile' },
] as const

/** Just the location values for quick lookups. */
export const LOCATION_VALUES = LOCATION_OPTIONS.map((o) => o.value)

/**
 * Every language a physical item can be recorded in — mirrors backend
 * `LANGUAGE_LABELS` (models/inventory.py) CHARACTER FOR CHARACTER: 18 real
 * TCGdex codes plus `OTHER`, the manual escape hatch for a card TCGdex does
 * not carry at all. `JP` stays `JP`, not `JA` — the API code (`ja`) is a
 * separate translation the backend's `LANGUAGE_API_CODE` carries, not this
 * field's stored value. See RFC 0023 §1.1.
 */
export const LANGUAGE_OPTIONS = [
  { value: 'EN', label: 'English' },
  { value: 'JP', label: 'Japanese' },
  { value: 'FR', label: 'French' },
  { value: 'DE', label: 'German' },
  { value: 'ES', label: 'Spanish' },
  { value: 'ES-MX', label: 'Spanish (Mexico)' },
  { value: 'IT', label: 'Italian' },
  { value: 'PT', label: 'Portuguese' },
  { value: 'PT-BR', label: 'Portuguese (Brazil)' },
  { value: 'PT-PT', label: 'Portuguese (Portugal)' },
  { value: 'NL', label: 'Dutch' },
  { value: 'PL', label: 'Polish' },
  { value: 'RU', label: 'Russian' },
  { value: 'KO', label: 'Korean' },
  { value: 'ZH-TW', label: 'Chinese (Traditional)' },
  { value: 'ZH-CN', label: 'Chinese (Simplified)' },
  { value: 'ID', label: 'Indonesian' },
  { value: 'TH', label: 'Thai' },
  { value: 'OTHER', label: 'Other / unsupported' },
] as const

/**
 * The priced-finish vocabulary offered by `FinishPicker` (RFC 0023 §2.1) —
 * mirrors `PRICED_FINISHES` in `backend/models/inventory.py` CHARACTER FOR
 * CHARACTER. Measured from the live catalog 2026-09-02, not typed — see that
 * constant's own docstring and `docs/plans/rfc-0023/progress.md`'s T4
 * summary for the full measurement. A UI list, not a validator: `finish`
 * itself still accepts any string on write, because the provider adds keys
 * this list has not caught up to yet.
 */
export const PRICED_FINISHES = [
  'normal', 'holofoil', 'reverseHolofoil',
  '1stEdition', 'unlimited', 'unlimitedHolofoil',
  '1stEditionHolofoil', '1stEditionNormal',
] as const

/**
 * Suggested (not enforced) `finish_attributes` chips — RFC 0023 §2.2's own
 * list verbatim. Free text is always accepted alongside these: the operator
 * is standing at a table with a card in hand, and a closed vocabulary is the
 * exact failure this field exists to fix.
 */
export const FINISH_ATTRIBUTE_SUGGESTIONS = [
  '1st Edition', 'Shadowless', 'Unlimited', 'Stamped (Prerelease)', 'Staff',
  'Promo', 'Full Art', 'Alt Art', 'Illustration Rare', 'Special Illustration Rare',
  'Gold / Secret Rare', 'Rainbow Rare', 'Textured', 'Cosmos Holo',
  'Poké Ball Pattern', 'Master Ball Pattern', 'Jumbo', 'Error / Miscut', 'Signed',
] as const
