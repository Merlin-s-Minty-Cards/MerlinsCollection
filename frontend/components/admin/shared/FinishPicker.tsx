'use client'

import { useState } from 'react'
import { PRICED_FINISHES, FINISH_ATTRIBUTE_SUGGESTIONS } from '@/lib/constants'

/**
 * Suggested chips plus any already-selected tag they don't cover, so a
 * custom-typed tag stays visible — and removable — as its own chip instead
 * of vanishing into the array with no control to click it off.
 *
 * Exported (not a private helper) because `CardDetailModal`'s
 * `finish_attributes` row needs the identical computation but cannot use
 * `FinishPicker` itself — it has its own `attributesDraft` state, not this
 * component's `attributes`/`onAttributesChange` prop pair, since it is
 * embedded inside that modal's generic per-field edit switch rather than
 * standing alone the way `IncomingCardForm` uses it.
 */
export function finishAttributeChipVocabulary(selected: string[]): string[] {
  return [
    ...FINISH_ATTRIBUTE_SUGGESTIONS,
    ...selected.filter((a) => !(FINISH_ATTRIBUTE_SUGGESTIONS as readonly string[]).includes(a)),
  ]
}

export interface FinishPickerProps {
  /** The priced finish — the join key into `card.prices`. */
  finish: string
  onFinishChange: (value: string) => void
  /** Everything about a printing that is genuinely NOT mutually exclusive
   *  with `finish` above (1st Edition, Shadowless, ...). */
  attributes: string[]
  onAttributesChange: (value: string[]) => void
}

/**
 * One priced finish plus a chip multi-select for its descriptive attributes
 * (RFC 0023 §2). `finish` and `finish_attributes` are two different backend
 * fields, but a card's printing identity is one thing an operator is looking
 * at, standing at a table with the physical card in hand — this component is
 * the ONE place both are edited together.
 *
 * `PRICED_FINISHES` is MEASURED from the live catalog (see its own docstring
 * in `lib/constants.ts`), not typed — the concrete bug this fixes is
 * `IncomingCardForm.tsx`'s old `FINISHES` array offering `firstEditionHolofoil`,
 * a spelling `_MARKET_FINISH_FALLBACK` has never heard of, so an item staged
 * with it silently fell through the pricing fallback.
 *
 * The chip vocabulary (`FINISH_ATTRIBUTE_SUGGESTIONS`) is SUGGESTED, not
 * enforced — free text via the "add custom" input is always accepted
 * alongside it. A closed vocabulary is the exact failure this component
 * exists to fix: the operator is standing at a table with a card in hand,
 * and Pokémon prints new attribute combinations faster than any dropdown
 * can be updated.
 *
 * Attributes carry NO price multiplier — that is a model-level decision
 * (`models/inventory.py`'s `finish_attributes` docstring), not something
 * this component enforces, but it is why there is no "value" shown here:
 * a 1st Edition Shadowless card is hand-priced, not computed.
 */
export default function FinishPicker({
  finish,
  onFinishChange,
  attributes,
  onAttributesChange,
}: FinishPickerProps) {
  const [customTag, setCustomTag] = useState('')

  const toggle = (tag: string) => {
    if (attributes.includes(tag)) {
      onAttributesChange(attributes.filter((a) => a !== tag))
    } else {
      onAttributesChange([...attributes, tag])
    }
  }

  const addCustom = () => {
    const trimmed = customTag.trim()
    if (!trimmed || attributes.includes(trimmed)) return
    onAttributesChange([...attributes, trimmed])
    setCustomTag('')
  }

  const chipVocabulary = finishAttributeChipVocabulary(attributes)

  return (
    <div className="flex flex-col gap-2">
      <label className="flex flex-col gap-1">
        <span className="text-[11px] uppercase tracking-wider text-pine-400">Finish</span>
        <select
          aria-label="Finish"
          value={finish}
          className="vault-field w-full rounded-lg px-3 py-2 text-sm"
          onChange={(e) => onFinishChange(e.target.value)}
        >
          {PRICED_FINISHES.map((f) => (
            <option key={f} value={f}>{f}</option>
          ))}
        </select>
      </label>

      <div className="flex flex-col gap-1">
        <span className="text-[11px] uppercase tracking-wider text-pine-400">
          Finish Attributes (optional)
        </span>
        <div className="flex flex-wrap gap-1.5">
          {chipVocabulary.map((tag) => {
            const selected = attributes.includes(tag)
            return (
              <button
                key={tag}
                type="button"
                onClick={() => toggle(tag)}
                aria-pressed={selected}
                className={`rounded-full px-2.5 py-1 text-[11px] border transition-colors ${
                  selected
                    ? 'bg-mint/20 border-mint/40 text-mint'
                    : 'bg-pine-800/40 border-pine-700/40 text-pine-400 hover:border-pine-600'
                }`}
              >
                {tag}
              </button>
            )
          })}
        </div>
        <div className="flex gap-1.5 mt-1">
          <input
            type="text"
            aria-label="Add custom finish attribute"
            placeholder="Add custom…"
            value={customTag}
            onChange={(e) => setCustomTag(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') { e.preventDefault(); addCustom() }
            }}
            className="vault-field flex-1 min-w-0 rounded-lg px-2.5 py-1.5 text-xs"
          />
          <button
            type="button"
            onClick={addCustom}
            aria-label="Add finish attribute"
            className="vault-field rounded-lg px-3 py-1.5 text-xs text-mint hover:bg-mint/10"
          >
            Add
          </button>
        </div>
      </div>
    </div>
  )
}
