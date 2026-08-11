'use client'

import { formatMoneyInput, parseMoney } from '@/lib/money'

export interface MoneyInputProps {
  /** Becomes the input's `aria-label`, so `getByLabelText('Cost')` resolves. */
  label: string
  /** The raw string the operator has typed. The parent owns it. */
  value: string
  /** Raw text plus `parseMoney`'s verdict, so the parent can gate on `null`. */
  onChange: (raw: string, parsed: number | null) => void
  className?: string
}

/**
 * A money field that accepts what a human types.
 *
 * It is a TEXT input, never `type="number"` — a number input cannot receive a
 * comma, and `1,300` is what the owner actually types for a four-figure slab.
 *
 * On blur it rewrites the field to the canonical form (`1,300` → `1300.00`), so
 * the operator sees the number that will be sent while they can still change
 * it. The slab staging table used to render the raw string, which meant a
 * mistyped `1,300` displayed as a perfectly correct-looking `$1,300` right up
 * until it reached the server as `null`.
 */
export default function MoneyInput({ label, value, onChange, className }: MoneyInputProps) {
  const parsed = parseMoney(value)
  // Blank is not an error — it is a field nobody has filled in yet.
  const invalid = value.trim() !== '' && parsed === null

  return (
    <>
      <input
        type="text"
        aria-label={label}
        inputMode="decimal"
        value={value}
        aria-invalid={invalid || undefined}
        className={className ?? 'vault-field w-full rounded-lg px-3 py-2 font-mono text-sm'}
        onChange={(e) => onChange(e.target.value, parseMoney(e.target.value))}
        onBlur={() => {
          // Only normalise what we understood. Rewriting an unreadable value
          // would destroy what the operator typed while they are fixing it.
          if (parsed !== null) onChange(formatMoneyInput(parsed), parsed)
        }}
      />
      {invalid && (
        <span role="alert" className="text-[11px] text-red-300">
          That isn&apos;t an amount I can read — try 1300 or 1,300
        </span>
      )}
    </>
  )
}
