import { parseMoney } from '@/lib/money'

interface PriceDisplayProps {
  value: string | number | null | undefined
  className?: string
  compact?: boolean
}

/**
 * Formatted currency display. Shows "—" for null/undefined values.
 */
export default function PriceDisplay({ value, className = '', compact }: PriceDisplayProps) {
  if (value === null || value === undefined || value === '') {
    return <span className={`text-pine-500 ${className}`}>—</span>
  }

  // `parseFloat` reads "1,300.00" as `1` and is not `NaN` — a comma-grouped
  // server string would render as "$1.00" instead of "—" or a crash, which
  // CLAUDE.md's money rule treats as strictly worse than either. Nothing
  // currently sends this component a grouped string, but `CardPickerRow`
  // feeds it a server-formatted price and there is no contract against one
  // arriving later, so this stays on `parseMoney` even while dormant.
  const num = typeof value === 'string' ? parseMoney(value) : value
  if (num === null || isNaN(num)) {
    return <span className={`text-pine-500 ${className}`}>—</span>
  }

  const formatted = compact
    ? num >= 1000
      ? `$${(num / 1000).toFixed(1)}k`
      : `$${num.toFixed(0)}`
    : `$${num.toFixed(2)}`

  return <span className={`font-mono ${className}`}>{formatted}</span>
}
