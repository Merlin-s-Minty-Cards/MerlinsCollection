import PriceDisplay from './PriceDisplay'

/**
 * A ledger amount with its direction on the front of it.
 * docs/plans/rfc-0010/t9-signed-ledger-amounts.md
 *
 * Owner report: *"In Show analytics, there needs to be a +/- for sales and buys.
 * i.e., sold is +$ and buying a card is -$."*
 *
 * **This is presentation only. Nothing here changes a stored sign.**
 * `Transaction.amount` is stored UNSIGNED with direction carried by `type`, and
 * every existing aggregate (`summarize_transactions`, `sell_through_rate`, the
 * show snapshot generator, the dashboard) reads it as a magnitude and applies
 * direction itself. Making some rows negative in storage would silently move
 * every one of those numbers, including snapshots already written.
 *
 * **The sign is TEXT, not colour.** Colour alone is not an accessible carrier of
 * meaning, and the owner reads these on a phone in show lighting. The colour is
 * a second, redundant cue.
 */

/** U+2212. Not a hyphen — it aligns in the monospace column this table sets. */
const MINUS = '−'

type Direction = 'in' | 'out' | 'neutral'

const STYLES: Record<Direction, { sign: string; className: string }> = {
  in: { sign: '+', className: 'text-mint' },
  out: { sign: MINUS, className: 'text-red-400' },
  neutral: { sign: '', className: 'text-pine-200' },
}

interface SignedAmountProps {
  value: string | number | null | undefined
  /**
   * The transaction type. `sale` is money in, `purchase` money out.
   *
   * **Anything else renders UNSIGNED, including a type this component has not
   * been taught.** The archive is deliberately raw, and guessing a direction on
   * a money figure is worse than showing none. Trade cash legs are not special
   * cased for the same reason: if a leg's type says purchase it renders
   * negative, and that is what was written.
   */
  type?: string
  /**
   * For a figure that is ALREADY signed — a net total, which genuinely can go
   * either way on a buying-heavy day and has no transaction type to key on.
   * Takes the direction from the number and renders its magnitude.
   */
  fromValue?: boolean
  className?: string
}

function toNumber(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === '') return null
  const num = typeof value === 'string' ? parseFloat(value) : value
  return Number.isNaN(num) ? null : num
}

function directionOf(
  num: number | null,
  type: string | undefined,
  fromValue: boolean | undefined,
): Direction {
  // An absent or zero amount gets no sign. `+$0.00` on a voided or free row
  // claims a direction the number does not have.
  if (num === null || num === 0) return 'neutral'
  if (fromValue) return num > 0 ? 'in' : 'out'
  if (type === 'sale') return 'in'
  if (type === 'purchase') return 'out'
  return 'neutral'
}

/**
 * Composes `PriceDisplay` rather than formatting currency itself — two money
 * formatters is one too many, and `PriceDisplay` already owns the em-dash for
 * an absent value.
 */
export default function SignedAmount({
  value,
  type,
  fromValue,
  className = '',
}: SignedAmountProps) {
  const num = toNumber(value)
  const direction = directionOf(num, type, fromValue)
  const { sign, className: tone } = STYLES[direction]
  // The magnitude: the sign is rendered once, by us. A stored `-160.00` under
  // `fromValue` must not come out as `−$-160.00`.
  const magnitude = num === null ? value : Math.abs(num)

  return (
    <span
      data-testid="signed-amount"
      className={`inline-flex items-baseline font-mono ${tone} ${className}`}
    >
      {sign}
      <PriceDisplay value={magnitude} className={tone} />
    </span>
  )
}
