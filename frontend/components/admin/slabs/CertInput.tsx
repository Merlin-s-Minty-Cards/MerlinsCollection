'use client'

interface CertInputProps {
  value: string
  onChange: (value: string) => void
  /** Fired on Enter with a non-blank value. Advances focus; does NOT submit. */
  onEnter?: () => void
  /** Fired when the field loses focus. Task 4 hangs the duplicate check here. */
  onBlur?: () => void
  disabled?: boolean
}

/**
 * The cert field, serving a keyboard-wedge scanner and a human typing equally.
 *
 * A wedge scanner is just a keyboard that types fast and ends with Enter, so
 * there is no scanner-detection here and deliberately no timing logic:
 * submission is NEVER gated on typing speed. A cert typed slowly over ten
 * seconds is exactly as valid as one scanned in 40ms, and for a slab whose
 * barcode will not read, hand entry is the only way in.
 *
 * Enter ADVANCES rather than submits -- the scanner's trailing Enter arrives
 * long before card, grade and cost are filled.
 */
export default function CertInput({ value, onChange, onEnter, onBlur, disabled }: CertInputProps) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-sm font-medium">Cert number</span>
      <input
        type="text"
        inputMode="numeric"
        autoFocus
        disabled={disabled}
        value={value}
        aria-label="Cert number"
        // Some scanners append \r, \n or both. Strip on the way in so the
        // value never carries invisible characters into a URL path.
        onChange={(e) => onChange(e.target.value.replace(/[\r\n]/g, '').trim())}
        onBlur={() => onBlur?.()}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault()
            if (value.trim()) onEnter?.()
          }
        }}
        className="rounded border px-3 py-2"
      />
    </label>
  )
}
