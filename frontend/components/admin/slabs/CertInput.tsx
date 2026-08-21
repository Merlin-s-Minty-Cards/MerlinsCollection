'use client'

import type { Ref } from 'react'

interface CertInputProps {
  value: string
  onChange: (value: string) => void
  /** Fired on Enter with a non-blank value. Advances focus; does NOT submit. */
  onEnter?: () => void
  /** Fired when the field loses focus. Task 4 hangs the duplicate check here. */
  onBlur?: () => void
  disabled?: boolean
  /**
   * Lets the page drive focus — a committed batch returns to this field.
   * `autoFocus` alone only fires on mount, which is why refocus-after-commit
   * sat unfixed as a T4 follow-up.
   */
  inputRef?: Ref<HTMLInputElement>
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
 *
 * **RFC 0010 T12 removed the "Scan cert" button and the armed affordance, and
 * deliberately kept everything below.** The owner's reasoning is that a wedge
 * scanner just types the number, so the ordinary field is the scanner target.
 * That is only true while `onEnter` advances and the `
` strip stays: delete
 * either and wedge scanning breaks while hand-typing keeps working, which is an
 * invisible failure nobody finds until they are at a table with a scanner.
 */
export default function CertInput({
  value,
  onChange,
  onEnter,
  onBlur,
  disabled,
  inputRef,
}: CertInputProps) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[11px] uppercase tracking-wider text-pine-400">Cert number</span>
      <input
        ref={inputRef}
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
        className="vault-field w-full rounded-lg px-3 py-2 font-mono text-sm"
      />
    </label>
  )
}
