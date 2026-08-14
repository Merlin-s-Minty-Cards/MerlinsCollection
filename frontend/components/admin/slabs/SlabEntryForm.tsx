'use client'

import { useEffect, useRef, useState } from 'react'
import { Plus } from 'lucide-react'
import { useAdminApi } from '@/lib/admin-api'
import { parseMoney } from '@/lib/money'
import { useLocations } from '@/lib/use-locations'
import MoneyInput from '@/components/admin/shared/MoneyInput'
import CardSearchPanel from '@/components/admin/shared/CardSearchPanel'
import type { PickerCard } from '@/components/admin/shared/CardPickerRow'
import CertInput from './CertInput'

export interface StagedSlab {
  key: string
  cert_number: string
  card_id: string | null
  name: string
  company: string
  grade: string
  grade_label: string
  /** PARSED, not the raw text. A staged row is what will be sent. */
  buy_price: number
  location: string
}

interface OwnedCheck {
  owned: boolean
  item_id?: string
  status?: string
  name?: string
}

const COMPANIES = ['PSA', 'BGS', 'CGC', 'SGC']

/**
 * Hand-entry for one graded slab, emitting a single staged row via `onAdd`.
 *
 * Card identity is catalog autocomplete with a free-text fallback: picking a
 * suggestion sets `card_id`, typing a name and picking nothing leaves it null
 * and the item lands in Triage as `no_catalog_link`. That fallback is the whole
 * point -- a Japanese slab with no catalog row must still be enterable.
 *
 * No condition control: conditions are meaningless for an encapsulated card.
 */
export default function SlabEntryForm({
  onAdd,
  focusToken,
}: {
  onAdd: (row: StagedSlab) => void
  /** Bump to pull focus back to the cert field after a commit. */
  focusToken?: number
}) {
  const api = useAdminApi()
  // `options`, not `locations` -- see lib/use-locations.ts:13.
  const { options: locationOptions } = useLocations()

  const [cert, setCert] = useState('')
  const [name, setName] = useState('')
  const [cardId, setCardId] = useState<string | null>(null)
  const [company, setCompany] = useState('PSA')
  const [grade, setGrade] = useState('')
  const [gradeLabel, setGradeLabel] = useState('')
  const [cost, setCost] = useState('')
  const [location, setLocation] = useState('toploader')

  const [owned, setOwned] = useState<OwnedCheck | null>(null)
  const [error, setError] = useState<string | null>(null)
  // Remounts CardSearchPanel after a successful add so its internal name,
  // number and set state clear along with the rest of the form.
  const [panelKey, setPanelKey] = useState(0)

  const nameRef = useRef<HTMLInputElement>(null)
  const certRef = useRef<HTMLInputElement>(null)

  // Focus is driven from the page so "Scan cert" can arm this field even when
  // the form was already open (no remount, so autoFocus would never re-fire).
  useEffect(() => {
    if (focusToken === undefined) return
    certRef.current?.focus()
  }, [focusToken])

  const checkOwned = async () => {
    if (!cert.trim()) return
    try {
      setOwned(await api.get<OwnedCheck>(`/slabs/certs/${encodeURIComponent(cert)}`, { company }))
    } catch {
      // A check that threw is not evidence the cert is unowned. `null` means
      // "unknown", which shows no warning and blocks nothing.
      setOwned(null)
    }
  }

  const submit = () => {
    if (!cert.trim()) {
      setError(
        'Without a cert number this is not a slab, it is just a normal card — add it on the Buy page instead.',
      )
      return
    }
    if (!grade.trim()) {
      setError('Grade and cost are required.')
      return
    }
    // `=== null`, never falsiness: a free card costs 0, and 0 is a real answer.
    const parsedCost = parseMoney(cost)
    if (parsedCost === null) {
      // MoneyInput already explains what a readable amount looks like, right
      // under the field. This says why the ADD was refused, not the same
      // sentence a second time.
      setError(
        cost.trim()
          ? `Cost "${cost.trim()}" is not a readable amount — fix it before adding.`
          : 'Grade and cost are required.',
      )
      return
    }
    setError(null)
    onAdd({
      key: crypto.randomUUID(),
      cert_number: cert.trim(),
      card_id: cardId,
      name: name.trim(),
      company,
      grade: grade.trim(),
      grade_label: gradeLabel.trim(),
      buy_price: parsedCost,
      location,
    })
    setCert('')
    setName('')
    setCardId(null)
    setGrade('')
    setGradeLabel('')
    setCost('')
    setOwned(null)
    setPanelKey((k) => k + 1)
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <CertInput
          value={cert}
          inputRef={certRef}
          onChange={(v) => {
            setCert(v)
            setOwned(null)
          }}
          onEnter={() => nameRef.current?.focus()}
          onBlur={checkOwned}
        />
      </div>

      {owned?.owned && (
        <p
          role="status"
          className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-300"
        >
          Already in inventory ({owned.status}) — {owned.name}. You can still add it.
        </p>
      )}

      <CardSearchPanel
        key={panelKey}
        nameInputRef={nameRef}
        initialName={name}
        onNameChange={(v) => {
          setName(v)
          setCardId(null)
        }}
        onSelect={(picked: PickerCard) => {
          setCardId(picked.card_id)
          setName(picked.name)
        }}
        // A permanent affordance -- the owner's report was that manual entry
        // only appeared after a search returned nothing, unreachable in the
        // more common case: the search succeeds and every result is wrong.
        onManualEntry={() => nameRef.current?.focus()}
      />
      {cardId && (
        <p className="text-[11px] text-spriggatito-400">Linked to catalog ({cardId})</p>
      )}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <label className="flex flex-col gap-1">
          <span className="text-[11px] uppercase tracking-wider text-pine-400">Company</span>
          <select
            aria-label="Company"
            value={company}
            className="vault-field w-full rounded-lg px-3 py-2 text-sm"
            onChange={(e) => setCompany(e.target.value)}
          >
            {COMPANIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-[11px] uppercase tracking-wider text-pine-400">Grade</span>
          <input
            aria-label="Grade"
            inputMode="decimal"
            value={grade}
            className="vault-field w-full rounded-lg px-3 py-2 font-mono text-sm"
            onChange={(e) => setGrade(e.target.value)}
          />
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-[11px] uppercase tracking-wider text-pine-400">Grade label</span>
          <input
            aria-label="Grade label"
            value={gradeLabel}
            className="vault-field w-full rounded-lg px-3 py-2 text-sm"
            onChange={(e) => setGradeLabel(e.target.value)}
          />
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-[11px] uppercase tracking-wider text-pine-400">Cost</span>
          <MoneyInput label="Cost" value={cost} onChange={(raw) => setCost(raw)} />
        </label>
      </div>

      <label className="flex max-w-xs flex-col gap-1">
        <span className="text-[11px] uppercase tracking-wider text-pine-400">Location</span>
        <select
          aria-label="Location"
          value={location}
          className="vault-field w-full rounded-lg px-3 py-2 text-sm"
          onChange={(e) => setLocation(e.target.value)}
        >
          {locationOptions.map((l) => (
            <option key={l.value} value={l.value}>
              {l.label}
            </option>
          ))}
        </select>
      </label>

      {error && (
        <p
          role="alert"
          className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300"
        >
          {error}
        </p>
      )}
      <button
        type="button"
        onClick={submit}
        className="inline-flex items-center gap-1.5 self-start rounded-lg border border-mint/30 bg-mint/15 px-3.5 py-2 text-xs font-medium text-mint transition-colors hover:bg-mint/25"
      >
        <Plus size={14} />
        Add to batch
      </button>
    </div>
  )
}
