/**
 * Acquisition economics — RFC 0024 T1.
 *
 * The TypeScript mirror of
 * `backend/src/merlins_collection/services/acquisition.py`'s
 * `acquisition_ratio`. Two implementations, deliberately, in the same shape
 * as `itemTitle` / `adminItemName` / `admin_item_name` / MCP's `toCard` — one
 * rule, several implementations, kept in sync on purpose. The two are pinned
 * together by a shared fixture rather than by trust: see
 * `frontend/lib/__tests__/acquisition.test.ts` and
 * `backend/tests/test_cross_boundary.py`, both of which load
 * `shared/test-fixtures/acquisition-ratio-cases.json`.
 *
 * `acquisitionRatio` is never stored — it is derived from two figures already
 * on the wire (`market_value_at_purchase`, `cost_basis`) and would go stale
 * the moment either changes. Compute it at render time, every time.
 */

function toAmount(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === '') return null
  const n = typeof value === 'string' ? Number(value) : value
  return Number.isFinite(n) ? n : null
}

/**
 * `marketValueAtPurchase / costBasis`, as a PERCENT.
 *
 * `null` when either figure is absent, or when `costBasis` is zero — a free
 * card (a throw-in, a bulk lot) is routine at a buy table, and its ratio is
 * undefined, not infinite and not zero. Every caller must handle `null` and
 * render an em dash (or, for a chip, render nothing at all — see
 * `ratioTone`).
 *
 * Rounded to two decimal places, the same precision
 * `acquisition_ratio` rounds to on the Python side, so a repeating-decimal
 * division (e.g. 10/3) can't drift between float64 and arbitrary-precision
 * `Decimal` before the two are compared.
 */
export function acquisitionRatio(
  marketValueAtPurchase: string | number | null | undefined,
  costBasis: string | number | null | undefined
): number | null {
  const market = toAmount(marketValueAtPurchase)
  const cost = toAmount(costBasis)
  if (market === null || cost === null || cost === 0) return null

  const raw = (market / cost) * 100
  return Math.round(raw * 100) / 100
}

/**
 * The rounded integer percent for display, e.g. `"313%"`. `null` in, `null`
 * out — the caller renders nothing for a null ratio, never a grey `0%` or a
 * dash mixed into a chip; see `ratioTone`'s docstring for why a `null` chip
 * is not a chip at all.
 */
export function formatRatio(ratio: number | null): string | null {
  if (ratio === null) return null
  return `${Math.round(ratio)}%`
}

export type RatioTone = 'good' | 'neutral' | 'bad'

/**
 * Tone bands, defined once and nowhere else:
 *
 * | Ratio      | Tone                        |
 * |------------|-----------------------------|
 * | >= 200%    | good                        |
 * | 100 - 200% | neutral                     |
 * | < 100%     | bad — we paid over market   |
 * | `null`     | no chip at all, not a grey zero |
 */
export function ratioTone(ratio: number | null): RatioTone | null {
  if (ratio === null) return null
  if (ratio >= 200) return 'good'
  if (ratio >= 100) return 'neutral'
  return 'bad'
}
