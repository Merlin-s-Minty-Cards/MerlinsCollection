/**
 * Money parsing and display for admin input fields.
 *
 * NEVER use `parseFloat` in here, or anywhere near a money field.
 * `parseFloat("1,300")` is `1` — not `NaN` — so it slips past every `isNaN`
 * guard in this codebase and turns a loud 500 into a silent $1,299 loss. A
 * wrong number that passes validation is strictly worse than a crash.
 *
 *   input        Number(v)   parseFloat(v)
 *   1,300        NaN         1
 *   1,300.50     NaN         1
 *   1.2.3        NaN         1.2
 *
 * The other rejected fix was `type="number"`: a native number input cannot
 * receive a comma at all, so `1,300` becomes un-typeable rather than correct.
 * It satisfies the machine and fails the person who asked. See
 * docs/plans/rfc-0010/t0-money-input-and-partial-write.md.
 */

/**
 * Digits, or digits grouped in threes, with an optional decimal part.
 *
 * The grouping arm is what makes `1,30` a rejection rather than a plausible
 * wrong number: a separator must be followed by exactly three digits. An
 * exponent, a sign and a second separator all fall outside this on purpose.
 */
const AMOUNT = /^(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d*)?$/

/** A leading-point decimal (`.5`), which the main pattern deliberately excludes. */
const LEADING_POINT = /^\.\d+$/

/**
 * Parse what a human typed into a money field.
 *
 * Returns `null`, never a guess, for anything ambiguous — including a negative
 * amount, which is rejected here rather than at each call site. `0` is a real
 * answer, so callers must test `=== null` and never falsiness.
 */
export function parseMoney(raw: string): number | null {
  if (typeof raw !== 'string') return null
  const trimmed = raw.trim().replace(/^\$/, '').trim()
  if (!AMOUNT.test(trimmed) && !LEADING_POINT.test(trimmed)) return null
  const n = Number(trimmed.replace(/,/g, ''))
  return Number.isFinite(n) ? n : null
}

/**
 * The canonical string for an input field: two decimals, no grouping, so the
 * value round-trips back through `parseMoney` unchanged.
 */
export function formatMoneyInput(n: number): string {
  return n.toFixed(2)
}

/**
 * The display string: grouped and prefixed. Grouping is done by hand rather
 * than through `toLocaleString` so the output does not depend on which ICU data
 * the runtime shipped with.
 */
export function formatMoney(n: number): string {
  const [whole, frac] = Math.abs(n).toFixed(2).split('.')
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  return `${n < 0 ? '-' : ''}$${grouped}.${frac}`
}
