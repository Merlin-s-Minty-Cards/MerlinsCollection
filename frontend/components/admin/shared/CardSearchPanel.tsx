'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { useAdminApi } from '@/lib/admin-api'
import { useCatalogSets, toComboboxSets } from '@/lib/use-catalog-sets'
import SetCombobox from '@/components/shared/SetCombobox'
import CardPickerRow, { type PickerCard } from './CardPickerRow'

/**
 * One shared card search -- name, number and set -- backing every catalog
 * picker in admin (RFC 0011 T11). Three of five pickers had already lost
 * their card images and their number/set fields by drifting apart from the
 * Buy page's reference row; this is the one definition all of them share.
 *
 * `onManualEntry`, when provided, renders a PERMANENT control -- present
 * before any search runs, while results are showing, and when there are
 * none. The owner's report was that manual entry only appeared after a
 * search returned nothing, which is unreachable in the more common and more
 * expensive failure: the search succeeds and every result is the wrong
 * printing. See CLAUDE.md, "AN ESCAPE HATCH IS NEVER GATED ON THE FAILURE OF
 * THE PATH IT ESCAPES".
 */

const DEBOUNCE_MS = 300

export interface CardSearchPanelProps {
  onSelect: (card: PickerCard) => void
  /** Rendered as a permanent control. Omit on surfaces where manual entry is meaningless. */
  onManualEntry?: () => void
  /** Seeds the name box -- used by the Unmatched queue's "Search catalog" action (T8). */
  initialName?: string
  initialNumber?: string
  autoFocus?: boolean
  /** Fires on every keystroke in the name box -- Slabs tracks this for its free-text fallback. */
  onNameChange?: (name: string) => void
  /** Lets a caller move focus into the name box programmatically (Slabs' cert-Enter handoff). */
  nameInputRef?: React.RefObject<HTMLInputElement>
}

export default function CardSearchPanel({
  onSelect,
  onManualEntry,
  initialName = '',
  initialNumber = '',
  autoFocus,
  onNameChange,
  nameInputRef,
}: CardSearchPanelProps) {
  const api = useAdminApi()
  const { sets } = useCatalogSets()

  const [name, setName] = useState(initialName)
  const [number, setNumber] = useState(initialNumber)
  const [setId, setSetId] = useState('')
  const [results, setResults] = useState<PickerCard[]>([])

  // Requests do not resolve in send order -- without this guard, a slow
  // response for an earlier keystroke can overwrite a faster one for a later
  // one. Same guard the Slabs and Buy searches already use.
  const seqRef = useRef(0)
  const nameRef = useRef<HTMLInputElement>(null)

  const search = useCallback(async (n: string, num: string, set: string) => {
    if (!n.trim() && !num.trim() && !set.trim()) {
      setResults([])
      return
    }
    const seq = ++seqRef.current
    const params: Record<string, string> = {}
    if (n.trim()) params.name = n.trim()
    if (num.trim()) params.number = num.trim()
    if (set.trim()) params.set_id = set.trim()
    try {
      const res = await api.get<{ items: PickerCard[]; total: number }>('/market/search', params)
      if (seq !== seqRef.current) return
      setResults(res.items)
    } catch {
      // A failed request is not evidence the catalog lacks the card.
      if (seq === seqRef.current) setResults([])
    }
  }, [api])

  useEffect(() => {
    const t = setTimeout(() => search(name, number, setId), DEBOUNCE_MS)
    return () => clearTimeout(t)
  }, [name, number, setId, search])

  return (
    <div className="flex flex-col gap-2.5">
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-[2fr_1fr_2fr]">
        <input
          ref={nameInputRef ?? nameRef}
          aria-label="Card name"
          value={name}
          autoFocus={autoFocus}
          placeholder="Search catalog or type a name…"
          className="vault-field w-full rounded-lg px-2.5 py-1.5 text-xs"
          onChange={(e) => {
            setName(e.target.value)
            onNameChange?.(e.target.value)
          }}
        />
        <input
          aria-label="Card number"
          value={number}
          placeholder="Card #"
          className="vault-field w-full rounded-lg px-2.5 py-1.5 text-xs"
          onChange={(e) => setNumber(e.target.value)}
        />
        <SetCombobox
          sets={toComboboxSets(sets)}
          value={setId}
          onChange={setSetId}
          inputId="card-search-set"
          ariaLabel="Set"
          placeholder="All sets"
          emptyLabel="All sets"
          className="vault-field w-full rounded-lg px-2.5 py-1.5 text-xs"
        />
      </div>

      {onManualEntry && (
        <button
          type="button"
          onClick={onManualEntry}
          className="self-start text-[11px] text-pine-400 underline underline-offset-2 hover:text-mint"
        >
          Enter manually instead
        </button>
      )}

      {results.length > 0 && (
        <ul className="vault-panel max-h-[28rem] divide-y divide-pine-700/25 overflow-y-auto vault-scroll rounded-lg">
          {results.map((c) => (
            <li key={c.card_id}>
              <CardPickerRow card={c} onSelect={(picked) => { setResults([]); onSelect(picked) }} />
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
