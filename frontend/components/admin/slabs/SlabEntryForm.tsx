'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { useAdminApi } from '@/lib/admin-api'
import { useLocations } from '@/lib/use-locations'
import CertInput from './CertInput'

export interface StagedSlab {
  key: string
  cert_number: string
  card_id: string | null
  name: string
  company: string
  grade: string
  grade_label: string
  buy_price: string
  location: string
}

interface CatalogCard {
  card_id: string
  name: string
  set_name?: string
  number?: string
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
export default function SlabEntryForm({ onAdd }: { onAdd: (row: StagedSlab) => void }) {
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

  const [results, setResults] = useState<CatalogCard[]>([])
  const [owned, setOwned] = useState<OwnedCheck | null>(null)
  const [error, setError] = useState<string | null>(null)

  // A catalog search can take seconds and several are in flight while the
  // operator types; they do NOT come back in send order. Without this guard the
  // response for "Gen" lands last and replaces the results for "Gengar". Same
  // guard the Buy page uses (app/(admin)/admin/buy/page.tsx:64).
  const seqRef = useRef(0)
  const nameRef = useRef<HTMLInputElement>(null)

  const searchCatalog = useCallback(async (q: string) => {
    if (!q.trim() || cardId) {
      setResults([])
      return
    }
    const seq = ++seqRef.current
    try {
      const res = await api.get<{ items: CatalogCard[]; total: number }>('/market/search', { name: q })
      if (seq !== seqRef.current) return
      setResults(res.items.slice(0, 8))
    } catch {
      // A request that threw is not evidence the catalog lacks the card, so
      // this clears the list and says nothing about it.
      if (seq === seqRef.current) setResults([])
    }
  }, [api, cardId])

  useEffect(() => {
    const t = setTimeout(() => searchCatalog(name), 300)
    return () => clearTimeout(t)
  }, [name, searchCatalog])

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
    if (!grade.trim() || !cost.trim()) {
      setError('Grade and cost are required.')
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
      buy_price: cost.trim(),
      location,
    })
    setCert('')
    setName('')
    setCardId(null)
    setGrade('')
    setGradeLabel('')
    setCost('')
    setResults([])
    setOwned(null)
  }

  return (
    <div className="flex flex-col gap-3">
      <CertInput
        value={cert}
        onChange={(v) => {
          setCert(v)
          setOwned(null)
        }}
        onEnter={() => nameRef.current?.focus()}
        onBlur={checkOwned}
      />
      {owned?.owned && (
        <p role="status" className="text-amber-700">
          Already in inventory ({owned.status}) — {owned.name}. You can still add it.
        </p>
      )}

      <label className="flex flex-col gap-1">
        <span className="text-sm font-medium">Card name</span>
        <input
          ref={nameRef}
          aria-label="Card name"
          value={name}
          className="rounded border px-3 py-2"
          onChange={(e) => {
            setName(e.target.value)
            setCardId(null)
          }}
        />
      </label>
      {results.length > 0 && !cardId && (
        <ul>
          {results.map((c) => (
            <li key={c.card_id}>
              <button
                type="button"
                onClick={() => {
                  setCardId(c.card_id)
                  setName(c.name)
                  setResults([])
                }}
              >
                {c.name} — {c.set_name} #{c.number}
              </button>
            </li>
          ))}
        </ul>
      )}
      {cardId && <p className="text-sm text-green-700">Linked to catalog ({cardId})</p>}

      <label className="flex flex-col gap-1">
        <span className="text-sm font-medium">Company</span>
        <select
          aria-label="Company"
          value={company}
          className="rounded border px-3 py-2"
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
        <span className="text-sm font-medium">Grade</span>
        <input
          aria-label="Grade"
          inputMode="decimal"
          value={grade}
          className="rounded border px-3 py-2"
          onChange={(e) => setGrade(e.target.value)}
        />
      </label>

      <label className="flex flex-col gap-1">
        <span className="text-sm font-medium">Grade label</span>
        <input
          aria-label="Grade label"
          value={gradeLabel}
          className="rounded border px-3 py-2"
          onChange={(e) => setGradeLabel(e.target.value)}
        />
      </label>

      <label className="flex flex-col gap-1">
        <span className="text-sm font-medium">Cost</span>
        <input
          aria-label="Cost"
          inputMode="decimal"
          value={cost}
          className="rounded border px-3 py-2"
          onChange={(e) => setCost(e.target.value)}
        />
      </label>

      <label className="flex flex-col gap-1">
        <span className="text-sm font-medium">Location</span>
        <select
          aria-label="Location"
          value={location}
          className="rounded border px-3 py-2"
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
        <p role="alert" className="text-red-700">
          {error}
        </p>
      )}
      <button type="button" onClick={submit} className="rounded bg-green-700 px-4 py-2 text-white">
        Add to batch
      </button>
    </div>
  )
}
