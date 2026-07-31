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

  const num = typeof value === 'string' ? parseFloat(value) : value
  if (isNaN(num)) {
    return <span className={`text-pine-500 ${className}`}>—</span>
  }

  const formatted = compact
    ? num >= 1000
      ? `$${(num / 1000).toFixed(1)}k`
      : `$${num.toFixed(0)}`
    : `$${num.toFixed(2)}`

  return <span className={`font-mono ${className}`}>{formatted}</span>
}
