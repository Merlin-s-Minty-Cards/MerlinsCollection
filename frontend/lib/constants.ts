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
