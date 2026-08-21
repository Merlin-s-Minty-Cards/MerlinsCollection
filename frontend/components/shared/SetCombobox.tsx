'use client'

import { useEffect, useMemo, useRef, useState } from 'react'

/**
 * Type-to-narrow set picker, shared by the public inventory filter panel and the
 * admin inventory page (RFC 0008 T8).
 *
 * It was private to `components/inventory/FilterPanel.tsx` and moved here
 * verbatim in behaviour — the public panel's tests are the regression guard on
 * that, and they are the reason nothing here was "improved" on the way out.
 *
 * The two call sites hand it differently-shaped data: the public panel passes
 * `facets.sets` (`{id, name}`, scoped to customer-visible stock), the admin page
 * passes catalog-set registry rows carrying an owned count and a language. The
 * prop contract is deliberately the INTERSECTION — `{id, name}` plus an optional
 * `annotation` — rather than a union of both shapes, so there is one component
 * to fix rather than two that drift.
 */

export interface ComboboxSet {
  id: string
  name: string
  /**
   * Secondary text shown beside the name (the admin page puts "EN · 3 owned"
   * here). Deliberately NOT part of the search text: typing "EN" would
   * otherwise match every English set at once and narrowing would stop meaning
   * anything.
   */
  annotation?: string
}

export default function SetCombobox({
  sets,
  value,
  onChange,
  inputId = 'set-combobox',
  ariaLabel,
  placeholder = 'Any set',
  emptyLabel = 'Any set',
  className = 'vault-field w-full rounded-lg px-3 py-2.5 text-sm',
}: {
  sets: ComboboxSet[]
  value: string
  onChange: (id: string) => void
  inputId?: string
  ariaLabel?: string
  placeholder?: string
  emptyLabel?: string
  className?: string
}) {
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  // Index into `options` below (the empty row is index 0). -1 = nothing
  // highlighted yet, so a bare Enter does not silently pick the first set.
  const [active, setActive] = useState(-1)
  const wrapperRef = useRef<HTMLDivElement>(null)

  // Resolve the current value to a display name.
  const selected = sets.find((s) => s.id === value)

  const filtered = query
    ? sets.filter((s) => s.name.toLowerCase().includes(query.toLowerCase()))
    : sets

  // Two identically-named sets exist across languages ("Base Set" is both
  // `en:base1` and `ja:base1`), so the id is the key — the name is not unique.
  const listboxId = `${inputId}-listbox`

  // The empty ("Any set") row plus the filtered sets, in render order — one list
  // so keyboard and mouse select exactly the same things. `null` is the empty row.
  const options = useMemo<(ComboboxSet | null)[]>(() => [null, ...filtered], [filtered])
  const optionId = (i: number) => `${listboxId}-opt-${i}`

  const commit = (option: ComboboxSet | null) => {
    onChange(option ? option.id : '')
    setOpen(false)
    setActive(-1)
  }

  // Close on outside click.
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  return (
    <div ref={wrapperRef} className="relative">
      <input
        id={inputId}
        type="text"
        role="combobox"
        aria-label={ariaLabel}
        aria-expanded={open}
        aria-autocomplete="list"
        aria-controls={listboxId}
        value={open ? query : selected?.name ?? ''}
        placeholder={placeholder}
        className={className}
        aria-activedescendant={open && active >= 0 ? optionId(active) : undefined}
        onFocus={() => {
          setOpen(true)
          setQuery('')
          setActive(-1)
        }}
        onChange={(e) => {
          setQuery(e.target.value)
          setOpen(true)
          // Narrowing invalidates the old index — it could point past the end,
          // or at a different set than the one under the cursor a moment ago.
          setActive(-1)
          if (e.target.value === '') {
            onChange('')
          }
        }}
        onKeyDown={(e) => {
          // Without this the list could be narrowed by typing but never chosen
          // from: options were mouse-only, so a keyboard-only admin was stuck
          // (RFC 0008 follow-up, T8 row 1).
          if (e.key === 'Escape') {
            setOpen(false)
            setActive(-1)
            return
          }
          if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            e.preventDefault()
            if (!open) {
              setOpen(true)
              return
            }
            if (options.length === 0) return
            const step = e.key === 'ArrowDown' ? 1 : -1
            // Wraps, and treats the -1 "nothing highlighted" state as before the
            // first row so ArrowDown lands on index 0 and ArrowUp on the last.
            setActive((prev) => {
              const next = prev + step
              if (next < 0) return options.length - 1
              if (next >= options.length) return 0
              return next
            })
            return
          }
          if (e.key === 'Enter' && open && active >= 0) {
            e.preventDefault()
            commit(options[active] ?? null)
            return
          }
          if (e.key === 'Tab' && open) {
            setOpen(false)
            setActive(-1)
          }
        }}
      />
      {open && filtered.length > 0 && (
        <ul
          id={listboxId}
          role="listbox"
          className="absolute z-50 mt-1 max-h-60 w-full overflow-auto rounded-lg vault-panel border border-pine-700 py-1"
        >
          <li
            id={optionId(0)}
            role="option"
            aria-selected={value === ''}
            className={`cursor-pointer px-3 py-2 text-sm hover:bg-pine-700/40 ${
              active === 0 ? 'bg-pine-700/40' : ''
            }`}
            onMouseDown={(e) => {
              // `onMouseDown` with preventDefault, not `onClick`: the input's
              // blur would close the list before a click ever landed.
              e.preventDefault()
              commit(null)
            }}
          >
            {emptyLabel}
          </li>
          {filtered.map((s, i) => (
            <li
              key={s.id}
              id={optionId(i + 1)}
              role="option"
              aria-selected={value === s.id}
              className={`flex cursor-pointer items-baseline justify-between gap-2 px-3 py-2 text-sm hover:bg-pine-700/40 ${
                active === i + 1 ? 'bg-pine-700/40' : ''
              }`}
              onMouseDown={(e) => {
                e.preventDefault()
                commit(s)
              }}
            >
              <span>{s.name}</span>
              {s.annotation && (
                <span className="shrink-0 font-mono text-[11px] text-pine-400">
                  {s.annotation}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
