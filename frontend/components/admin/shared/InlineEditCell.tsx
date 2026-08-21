'use client'

import { useRef, useState, KeyboardEvent, ReactNode } from 'react'
import { Pencil, X } from 'lucide-react'
import { MONEY_PARSE_MESSAGE, parseMoney } from '@/lib/money'

export interface InlineEditCellProps {
  /** Current stored value, used to seed the input when editing starts. */
  value: string
  /**
   * What to render while editing.
   *
   * `'money'` is a TEXT input, never `type="number"` — a number input cannot
   * receive a comma, and `1,300` is what the owner actually types for a
   * four-figure card. The typed text is put through `parseMoney` on commit, so
   * `onSave` always receives a clean numeric string (`'1,300'` → `'1300'`) and
   * an unreadable amount never reaches the API at all.
   */
  type: 'number' | 'url' | 'money'
  /** Read-only content shown when not editing (e.g. a formatted price or link). */
  displayValue: ReactNode
  /**
   * Called when the edit is committed (Enter or blur) with a value that
   * actually changed from `value` — unchanged edits are skipped entirely
   * (no call, no save, no round trip). The caller owns parsing/validation
   * (throw/reject to reject the edit — see below) and empty-string handling
   * (e.g. converting '' to null before saving).
   *
   * May return a Promise. While it is pending the input stays open and
   * disabled. If it resolves, the cell exits edit mode. If it rejects, edit
   * mode stays open (so the admin can see/retry the offending value) and the
   * rejection reason is forwarded to `onError`, if provided.
   */
  onSave: (value: string) => void | Promise<void>
  /**
   * Called when `onSave` rejects/throws. Typically used to surface a message
   * (e.g. "Save failed: <detail>") somewhere in the caller's UI. The cell
   * itself renders no error text — it only keeps the editor open.
   */
  onError?: (error: unknown) => void
  /** Optional: disables the input and suppresses further edits (e.g. a sibling bulk action is in flight). */
  saving?: boolean
  /** Optional: overrides the numeric step attribute (defaults to "0.01"). */
  step?: string
  /** Optional: placeholder shown in the input. */
  placeholder?: string
  /** Optional: adornment rendered inside the input's left edge (e.g. "$"). */
  prefix?: ReactNode
  /** Optional: accessible label for the display/edit trigger. */
  'aria-label'?: string
}

/**
 * Click-to-edit table cell: shows `displayValue` until clicked, then swaps in
 * a text input of the given `type`. Enter and blur commit the typed value via
 * `onSave` (skipped entirely if unchanged); Escape cancels and restores the
 * original value without saving, and — critically — the blur that follows an
 * Escape-driven focus loss must NOT also trigger a save (the classic
 * double-fire bug in this pattern).
 *
 * Not coupled to any specific data shape — callers own the field name(s),
 * parsing, and API call in their `onSave` callback. `onSave` may be async: a
 * rejection keeps the editor open instead of silently reverting, so failed
 * saves are visible and retryable rather than swallowed.
 */
export default function InlineEditCell({
  value,
  type,
  displayValue,
  onSave,
  onError,
  saving = false,
  step = '0.01',
  placeholder,
  prefix,
  'aria-label': ariaLabel,
}: InlineEditCellProps) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(value)
  const [submitting, setSubmitting] = useState(false)
  // Guards against the blur handler firing a save after Escape already
  // cancelled the edit. A ref (not state) is required here: Escape calls
  // blur() synchronously within the same handler, so the blur's onBlur
  // fires before any state update from cancel() has been committed —
  // a state flag would still read its stale (false) value at that point.
  const cancelledRef = useRef(false)

  const startEdit = () => {
    if (saving || submitting) return
    setDraft(value)
    cancelledRef.current = false
    setEditing(true)
  }

  const commit = async () => {
    if (cancelledRef.current) {
      cancelledRef.current = false
      return
    }
    // Dirty-check: reading a value and clicking away must not fire a save.
    if (draft === value) {
      setEditing(false)
      return
    }

    // Money is parsed before it can leave: `parseFloat('1,300')` is `1` and
    // never `NaN`, so an unreadable amount would otherwise pass every guard
    // downstream as a plausible wrong number. Blank stays blank — clearing a
    // price is a real edit, and the caller owns turning '' into null.
    let outgoing = draft
    if (type === 'money' && draft.trim() !== '') {
      const parsed = parseMoney(draft)
      if (parsed === null) {
        // Same shape as an onSave rejection: the editor stays open with the
        // offending text intact so the admin fixes it rather than losing it.
        onError?.(new Error(MONEY_PARSE_MESSAGE))
        return
      }
      outgoing = String(parsed)
      // A value that only differs by formatting ('1,300' vs '1300') is not an
      // edit — skip the round trip the dirty-check above would have skipped.
      if (outgoing === value) {
        setEditing(false)
        return
      }
    }

    setSubmitting(true)
    try {
      await onSave(outgoing)
      setEditing(false)
    } catch (err) {
      // Keep the editor open on failure so the admin can see/retry the
      // offending value instead of it silently reverting.
      onError?.(err)
    } finally {
      setSubmitting(false)
    }
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
    const disabled = saving || submitting
    return (
      <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
        <div className="relative flex-1 min-w-0">
          {prefix && (
            <span className="absolute left-1.5 top-1/2 -translate-y-1/2 text-[10px] text-pine-500 pointer-events-none">
              {prefix}
            </span>
          )}
          <input
            type={type === 'money' ? 'text' : type}
            // The mobile numeric keypad is the only thing type="number" was
            // buying that matters on a show floor; inputMode preserves it.
            inputMode={type === 'money' ? 'decimal' : undefined}
            step={type === 'number' ? step : undefined}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={handleKeyDown}
            onBlur={commit}
            placeholder={placeholder}
            className={`vault-field w-full min-w-0 py-0.5 rounded text-xs font-mono ${prefix ? 'pl-4 pr-1.5' : 'px-1.5'}`}
            autoFocus
            disabled={disabled}
          />
        </div>
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
