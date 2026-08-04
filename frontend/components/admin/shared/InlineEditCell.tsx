'use client'

import { useRef, useState, KeyboardEvent, ReactNode } from 'react'
import { Pencil, X } from 'lucide-react'

export interface InlineEditCellProps {
  /** Current stored value, used to seed the input when editing starts. */
  value: string
  /** HTML input type to render while editing. */
  type: 'number' | 'url'
  /** Read-only content shown when not editing (e.g. a formatted price or link). */
  displayValue: ReactNode
  /**
   * Called when the edit is committed (Enter or blur). Receives the raw
   * string typed into the input — the caller owns parsing/validation and
   * empty-string handling (e.g. converting '' to null before saving).
   */
  onSave: (value: string) => void
  /** Optional: disables the input and suppresses further edits while a save is in flight. */
  saving?: boolean
  /** Optional: overrides the numeric step attribute (defaults to "0.01"). */
  step?: string
  /** Optional: placeholder shown in the input. */
  placeholder?: string
  /** Optional: accessible label for the display/edit trigger. */
  'aria-label'?: string
}

/**
 * Click-to-edit table cell: shows `displayValue` until clicked, then swaps in
 * a text input of the given `type`. Enter and blur commit the typed value via
 * `onSave`; Escape cancels and restores the original value without saving,
 * and — critically — the blur that follows an Escape-driven focus loss must
 * NOT also trigger a save (the classic double-fire bug in this pattern).
 *
 * Not coupled to any specific data shape — callers own the field name(s),
 * parsing, and API call in their `onSave` callback.
 */
export default function InlineEditCell({
  value,
  type,
  displayValue,
  onSave,
  saving = false,
  step = '0.01',
  placeholder,
  'aria-label': ariaLabel,
}: InlineEditCellProps) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(value)
  // Guards against the blur handler firing a save after Escape already
  // cancelled the edit. A ref (not state) is required here: Escape calls
  // blur() synchronously within the same handler, so the blur's onBlur
  // fires before any state update from cancel() has been committed —
  // a state flag would still read its stale (false) value at that point.
  const cancelledRef = useRef(false)

  const startEdit = () => {
    if (saving) return
    setDraft(value)
    cancelledRef.current = false
    setEditing(true)
  }

  const commit = () => {
    if (cancelledRef.current) {
      cancelledRef.current = false
      return
    }
    setEditing(false)
    onSave(draft)
  }

  const cancel = () => {
    cancelledRef.current = true
    setDraft(value)
    setEditing(false)
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.currentTarget.blur()
    } else if (e.key === 'Escape') {
      cancel()
      e.currentTarget.blur()
    }
  }

  if (editing) {
    return (
      <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
        <input
          type={type}
          step={type === 'number' ? step : undefined}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={handleKeyDown}
          onBlur={commit}
          placeholder={placeholder}
          className="vault-field w-full min-w-0 px-1.5 py-0.5 rounded text-xs font-mono"
          autoFocus
          disabled={saving}
        />
        <button
          type="button"
          onClick={cancel}
          className="p-0.5 text-pine-500 hover:text-pine-300"
          aria-label="Cancel"
        >
          <X size={12} />
        </button>
      </div>
    )
  }

  return (
    <div
      className="flex items-center gap-1 group/inline-edit cursor-pointer"
      onClick={(e) => {
        e.stopPropagation()
        startEdit()
      }}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter') startEdit()
      }}
      aria-label={ariaLabel}
    >
      {displayValue}
      <Pencil size={10} className="text-pine-600 opacity-0 group-hover/inline-edit:opacity-100 transition-opacity" />
    </div>
  )
}
