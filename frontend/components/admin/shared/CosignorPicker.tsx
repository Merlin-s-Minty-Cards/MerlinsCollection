'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { useCosigners } from '@/lib/use-cosigners'

export interface CosignorPickerProps {
  value: string | null
  onChange: (consignorId: string | null) => void
  label?: string
  allowClear?: boolean
}

/**
 * A small (owner-managed, dozens-at-most) searchable dropdown over
 * useCosigners() — client-side substring filter, no server search, matching
 * useLocations()'s complexity level rather than CardSearchPanel's.
 */
export default function CosignorPicker({
  value,
  onChange,
  label = 'Consignor',
  allowClear = true,
}: CosignorPickerProps) {
  const { options } = useCosigners()
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const blurTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    return () => {
      if (blurTimeoutRef.current !== null) {
        clearTimeout(blurTimeoutRef.current)
      }
    }
  }, [])

  const selected = options.find((o) => o.value === value) ?? null

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return options
    return options.filter((o) => o.label.toLowerCase().includes(q))
  }, [options, query])

  return (
    <div className="relative flex flex-col gap-1">
      <span className="text-[11px] uppercase tracking-wider text-pine-400">{label}</span>
      <div className="flex items-center gap-1.5">
        <input
          role="combobox"
          aria-label={label}
          aria-expanded={open}
          className="vault-field w-full rounded-lg px-3 py-2 text-sm"
          value={open ? query : (selected?.label ?? '')}
          placeholder="Search cosigners…"
          onFocus={() => {
            setOpen(true)
            setQuery('')
          }}
          onChange={(e) => setQuery(e.target.value)}
          onBlur={() => {
            blurTimeoutRef.current = setTimeout(() => setOpen(false), 150)
          }}
        />
        {allowClear && selected && (
          <button
            type="button"
            aria-label="Clear consignor"
            className="text-[11px] text-pine-400 hover:text-pine-100"
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => onChange(null)}
          >
            Clear
          </button>
        )}
      </div>
      {open && (
        <div className="absolute top-full left-0 mt-1 w-full max-h-56 overflow-y-auto vault-panel rounded-lg border border-pine-700/40 shadow-xl z-30">
          {filtered.length === 0 ? (
            <p className="px-3 py-2 text-xs text-pine-500">No cosigners match.</p>
          ) : (
            filtered.map((o) => (
              <button
                key={o.value}
                type="button"
                className="block w-full px-3 py-2 text-left text-xs text-pine-200 hover:bg-mint/10"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => {
                  onChange(o.value)
                  setOpen(false)
                  setQuery('')
                }}
              >
                {o.label}
              </button>
            ))
          )}
        </div>
      )}
    </div>
  )
}
