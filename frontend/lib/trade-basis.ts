export type BasisMode = 'transfer' | 'split' | 'manual'

const CASH_DISABLED_REASON = 'Unavailable while the trade includes cash — use Manual.'

/**
 * Returns the three basis modes with their current availability.
 * Transfer and Split are disabled when the trade includes cash.
 */
export function availableModes(hasCash: boolean): { mode: BasisMode; disabled: boolean; reason: string | null }[] {
  return [
    {
      mode: 'transfer',
      disabled: hasCash,
      reason: hasCash ? CASH_DISABLED_REASON : null,
    },
    {
      mode: 'split',
      disabled: hasCash,
      reason: hasCash ? CASH_DISABLED_REASON : null,
    },
    {
      mode: 'manual',
      disabled: false,
      reason: null,
    },
  ]
}

/**
 * Whether the trade can be confirmed under the given basis mode.
 *
 * - transfer/split: allowed only without cash (the amount is server-computed).
 * - manual: requires a valid numeric string (including '0' — a zero-basis
 *   trade of worthless bulk is legitimate).
 */
export function canConfirmBasis(mode: BasisMode, hasCash: boolean, manualBasis: string): boolean {
  if (mode === 'transfer' || mode === 'split') {
    return !hasCash
  }
  // mode === 'manual'
  if (manualBasis.trim() === '') return false
  const parsed = Number(manualBasis)
  // NaN and Infinity are not valid amounts; 0 IS valid
  return Number.isFinite(parsed) && parsed >= 0
}
