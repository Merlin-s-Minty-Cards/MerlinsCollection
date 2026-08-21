import { parseMoney } from './money'

export type BasisMode = 'transfer' | 'split' | 'manual'

const CASH_DISABLED_REASON = 'Unavailable while the trade includes cash — use Manual.'

/**
 * `IncomingLeg` carries no `market_value`, so Split has nothing to split
 * against and silently computes the same number as Transfer — see the RFC
 * 0011 T15 review. Per CLAUDE.md's escape-hatch rule, an option that claims
 * to do one thing and does another is disabled with a one-line reason next
 * to it rather than left selectable. Building real split math needs a wider
 * `IncomingLeg` and is out of scope here.
 */
const SPLIT_DISABLED_REASON = 'Split needs per-card values — use Transfer or Manual for now.'

/**
 * Returns the three basis modes with their current availability.
 * Transfer is disabled when the trade includes cash. Split is ALWAYS
 * disabled (see `SPLIT_DISABLED_REASON`), independent of `hasCash`.
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
      disabled: true,
      reason: SPLIT_DISABLED_REASON,
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
  // Split is always disabled (see `SPLIT_DISABLED_REASON`), so it can never
  // confirm — it should be unreachable via the UI, but this is the backstop.
  if (mode === 'split') return false
  if (mode === 'transfer') {
    return !hasCash
  }
  // mode === 'manual'
  if (manualBasis.trim() === '') return false
  // `Number('1,300')` is `NaN` — `parseMoney` is the one parser for money
  // text (CLAUDE.md's "MONEY INPUT" rule), so a legitimately comma-grouped
  // basis no longer greys out Confirm (final-review Important 6).
  const parsed = parseMoney(manualBasis)
  // `=== null`, never falsiness: a zero-basis trade of worthless bulk is
  // legitimate, so 0 must confirm.
  return parsed !== null
}
