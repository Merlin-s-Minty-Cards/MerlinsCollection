'use client'

import { useEffect, useRef, useState } from 'react'
import { Search, X } from 'lucide-react'

interface SearchInputProps {
  value: string
  onChange: (value: string) => void
  placeholder?: string
  debounceMs?: number
  className?: string
  /**
   * Accessible name for the input. Without one the field's only name is its
   * placeholder, which disappears the moment anything is typed.
   */
  ariaLabel?: string
}

/**
 * Debounced search input with clear button. Styled for the vault theme.
 */
export default function SearchInput({
  value,
  onChange,
  placeholder = 'Search…',
  debounceMs = 300,
  className = '',
  ariaLabel,
}: SearchInputProps) {
  const [local, setLocal] = useState(value)
  const timerRef = useRef<ReturnType<typeof setTimeout>>()

  useEffect(() => {
    setLocal(value)
  }, [value])

  const handleChange = (newValue: string) => {
    setLocal(newValue)
    clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => onChange(newValue), debounceMs)
  }

  const clear = () => {
    setLocal('')
    onChange('')
  }

  return (
    <div className={`relative ${className}`}>
      <Search
        size={16}
        className="absolute left-3 top-1/2 -translate-y-1/2 text-pine-400 pointer-events-none"
      />
      <input
        type="text"
        aria-label={ariaLabel}
        value={local}
        onChange={(e) => handleChange(e.target.value)}
        placeholder={placeholder}
        className="vault-field w-full pl-9 pr-8 py-2 rounded-lg text-sm"
      />
      {local && (
        <button
          type="button"
          onClick={clear}
          className="absolute right-2.5 top-1/2 -translate-y-1/2 text-pine-400 hover:text-pine-200 transition-colors"
          aria-label="Clear search"
        >
          <X size={14} />
        </button>
      )}
    </div>
  )
}
