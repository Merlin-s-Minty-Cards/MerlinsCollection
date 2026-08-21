/**
 * Client-side sort utility for the Vault table.
 *
 * Numeric-aware: values are parsed with `parseFloat(String(value))`; values
 * that don't parse to a number (missing, null, non-numeric) sort LAST,
 * regardless of sort direction.
 *
 * Condition-aware: the `condition` key orders by the display-string tier
 * `CONDITION_TIER_ORDER`. Rows may carry either a single combined display
 * string (e.g. "LP+") in `condition`, or the backend's two-field storage
 * (`condition` tier + `condition_modifier`) — both are normalized via
 * `formatCondition` before ranking. Unrecognized condition strings sort
 * last, regardless of direction, same as numeric NaN.
 *
 * All other keys fall back to `localeCompare` on the string representation.
 */
import { formatCondition } from './constants'

const CONDITION_TIER_ORDER = ['NM', 'LP+', 'LP', 'LP-', 'MP', 'HP', 'DMG'] as const

function conditionDisplay(item: Record<string, unknown>): string {
  const condition = typeof item.condition === 'string' ? item.condition : ''
  const modifierRaw = item.condition_modifier
  const modifier = typeof modifierRaw === 'string' ? modifierRaw : null
  return formatCondition(condition, modifier)
}

function conditionRank(item: Record<string, unknown>): number {
  return CONDITION_TIER_ORDER.indexOf(conditionDisplay(item) as (typeof CONDITION_TIER_ORDER)[number])
}

/** Compares two "rank" numbers where -1 means "not found" and sorts last, unconditionally. */
function compareRanked(aRank: number, bRank: number, sign: number): number {
  const aMissing = aRank === -1
  const bMissing = bRank === -1
  if (aMissing && bMissing) return 0
  if (aMissing) return 1
  if (bMissing) return -1
  return sign * (aRank - bRank)
}

/** Compares two numbers where NaN sorts last, unconditionally. */
function compareNumeric(aNum: number, bNum: number, sign: number): number {
  const aNaN = Number.isNaN(aNum)
  const bNaN = Number.isNaN(bNum)
  if (aNaN && bNaN) return 0
  if (aNaN) return 1
  if (bNaN) return -1
  return sign * (aNum - bNum)
}

export function sortVaultItems<T extends Record<string, unknown>>(
  items: T[],
  key: string,
  dir: 'asc' | 'desc',
): T[] {
  const sign = dir === 'asc' ? 1 : -1

  return [...items].sort((a, b) => {
    if (key === 'condition') {
      return compareRanked(conditionRank(a), conditionRank(b), sign)
    }

    const aNum = parseFloat(String(a[key]))
    const bNum = parseFloat(String(b[key]))
    if (!Number.isNaN(aNum) || !Number.isNaN(bNum)) {
      return compareNumeric(aNum, bNum, sign)
    }

    const aStr = String(a[key] ?? '')
    const bStr = String(b[key] ?? '')
    return sign * aStr.localeCompare(bStr)
  })
}
