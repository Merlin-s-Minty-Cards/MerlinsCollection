'use client'

import { useEffect, useState } from 'react'
import { useAdminApi } from '@/lib/admin-api'
import { useLocations } from '@/lib/use-locations'
import { parseMoney } from '@/lib/money'
import { CONDITION_OPTIONS } from '@/lib/constants'
import { buildIncomingLeg, type IncomingLeg } from '@/lib/trade-incoming-form'
import MoneyInput from '@/components/admin/shared/MoneyInput'
import CosignorPicker from '@/components/admin/shared/CosignorPicker'
import type { PickerCard } from '@/components/admin/shared/CardPickerRow'
import DealCardRow from './DealCardRow'

/**
 * Add one card to a deal: catalog pick FIRST, then kind (RFC 0011 T14, §K).
 *
 * RFC 0012 reverses Decision 14: a graded leg no longer requires a catalog
 * pick. Manual entry (no catalog match) can now be graded, matching how
 * `/admin/slabs` intake has always worked — an unmatched graded item lands
 * unpriced and self-routes to Triage (services/triage.py's
 * is_missing_card_id), the same state a JP slab is already in.
 *
 * Decision 15 is STRUCTURAL, not cosmetic: condition and grade are never both
 * rendered. They are alternatives — a graded card's condition IS its grade.
 * Showing both invites filling both, and T13 422s a raw leg carrying graded
 * fields, so a form offering both would generate a rejection the operator
 * cannot explain.
 */

/** Mirrors `/admin/slabs`' list. Do not invent a second one. */
const COMPANIES = ['PSA', 'BGS', 'CGC', 'SGC']

const FINISHES = ['normal', 'holofoil', 'reverseHolofoil', 'firstEditionHolofoil']

/** `Language` on `InventoryItem` is a case-sensitive StrEnum: `EN`/`JP` only. */
const LANGUAGES = [
  { value: 'EN', label: 'EN' },
  { value: 'JP', label: 'JP' },
]

const CERT_DEBOUNCE_MS = 300

interface OwnedCheck {
  owned: boolean
  item_id?: string
  status?: string
  name?: string
}

export interface IncomingCardFormProps {
  /** `null` == manual entry (no catalog match). */
  card: PickerCard | null
  onAdd: (leg: IncomingLeg) => void
  onCancel: () => void
  /**
   * Presentational gate only — which controls the form shows. Defaults to
   * `true`. RFC 0012 removed the Buy-mode-specific block this used to carry
   * (the cert-ownership warning it was "pending" already existed and is
   * gated on `kind === 'graded'` alone, at lines ~101-123 below — it just
   * wasn't reachable while this defaulted to `false` for Buy). Kept as a
   * prop, not deleted, in case a future caller needs to withhold graded for
   * a reason unrelated to this one.
   */
  gradedAllowed?: boolean
}

export default function IncomingCardForm({ card, onAdd, onCancel, gradedAllowed = true }: IncomingCardFormProps) {
  const api = useAdminApi()
  // `options`, not `locations` — see lib/use-locations.ts:13.
  const { options: locationOptions } = useLocations()

  const manual = card === null

  const [kind, setKind] = useState<'raw' | 'graded'>('raw')
  const [name, setName] = useState(card?.name ?? '')
  const [setName_, setSetName] = useState(card?.set_name ?? '')
  const [number, setNumber] = useState(card?.number ?? '')
  const [condition, setCondition] = useState<string>(CONDITION_OPTIONS[0])
  const [finish, setFinish] = useState(FINISHES[0])
  const [company, setCompany] = useState(COMPANIES[0])
  const [grade, setGrade] = useState('')
  const [gradeLabel, setGradeLabel] = useState('')
  const [cert, setCert] = useState('')
  const [language, setLanguage] = useState('EN')
  const [location, setLocation] = useState('')
  const [value, setValue] = useState('')
  const [owned, setOwned] = useState<OwnedCheck | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [consignorPanel, setConsignorPanel] = useState(false)
  const [consignorId, setConsignorId] = useState<string | null>(null)

  // The location list is admin-managed and arrives async, so the default is
  // picked once it does rather than hardcoded here.
  useEffect(() => {
    if (!location && locationOptions.length > 0) setLocation(locationOptions[0].value)
  }, [location, locationOptions])

  /**
   * A cert already in inventory is a WARNING WITH OVERRIDE, never a gate: a
   * slab sold and bought back is legitimate re-entry (RFC 0009). Add stays
   * enabled, always.
   */
  useEffect(() => {
    if (kind !== 'graded' || !cert.trim()) {
      setOwned(null)
      return
    }
    let cancelled = false
    const t = setTimeout(async () => {
      try {
        const res = await api.get<OwnedCheck>(`/slabs/certs/${encodeURIComponent(cert.trim())}`, {
          company,
        })
        if (!cancelled) setOwned(res)
      } catch {
        // A check that threw is not evidence the cert is unowned. `null` means
        // "unknown", which shows no warning and blocks nothing.
        if (!cancelled) setOwned(null)
      }
    }, CERT_DEBOUNCE_MS)
    return () => {
      cancelled = true
      clearTimeout(t)
    }
  }, [cert, company, kind, api])

  // RFC 0012: manual entry (no catalog match) can be graded — Slabs intake
  // never gated this, and the Trade-specific backend rule that used to
  // require a card_id for a graded leg (Decision 14) is gone (see
  // routers/admin/trades.py). gradedAllowed itself now only reflects
  // whatever a specific caller still wants to withhold, if anything.
  const gradedSelectable = gradedAllowed

  const submit = () => {
    if (!name.trim()) {
      setError('A name is required — it is what the row will say on the deal.')
      return
    }
    // `=== null`, never falsiness: a throw-in is free, and 0 is a real answer
    // at a buy table.
    const parsed = parseMoney(value)
    if (parsed === null) {
      setError(
        value.trim()
          ? `Value "${value.trim()}" is not a readable amount — fix it before adding.`
          : 'A value is required. A free card is 0.',
      )
      return
    }
    setError(null)
    onAdd({
      ...buildIncomingLeg({
        card_id: card?.card_id ?? null,
        name,
        agreed_value: parsed,
        // Belt and braces on the one rule T13 enforces with a 422.
        kind: gradedSelectable ? kind : 'raw',
        set_name: setName_,
        card_number: number,
        condition,
        finish,
        company,
        grade,
        cert_number: cert,
        grade_label: gradeLabel,
        language,
        location,
        // Absent for a manual entry (no catalog card) or an unpriced catalog
        // card — never coerced to 0, per CLAUDE.md's "an absent price is
        // never $0.00, never blank, and never a guess."
        market_value: card ? parseMoney(String(card.display_price ?? '')) : null,
        image_url: card?.images?.small ?? null,
      }),
      // Client-side only — see IncomingLeg.consignor_id. Omitted entirely
      // (never `null`) when no consignor was staged.
      ...(consignorId ? { consignor_id: consignorId } : {}),
    })
  }

  return (
    <div className="vault-panel flex flex-col gap-3 rounded-lg p-3">
      {/* Identity stays on screen for the whole fill-in, never behind a hover. */}
      {manual ? (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-[2fr_2fr_1fr]">
          <label className="flex flex-col gap-1">
            <span className="text-[11px] uppercase tracking-wider text-pine-400">Card name</span>
            <input
              aria-label="Card name"
              value={name}
              className="vault-field w-full rounded-lg px-3 py-2 text-sm"
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[11px] uppercase tracking-wider text-pine-400">Set</span>
            <input
              aria-label="Set"
              value={setName_}
              className="vault-field w-full rounded-lg px-3 py-2 text-sm"
              onChange={(e) => setSetName(e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[11px] uppercase tracking-wider text-pine-400">Number</span>
            <input
              aria-label="Card number"
              value={number}
              className="vault-field w-full rounded-lg px-3 py-2 text-sm"
              onChange={(e) => setNumber(e.target.value)}
            />
          </label>
        </div>
      ) : (
        <DealCardRow
          card={{
            card_id: card.card_id,
            name: card.name,
            meta: [card.set_name || card.set_id, card.number && `#${card.number}`, card.rarity]
              .filter(Boolean)
              .join(' · '),
            imageUrl: card.images?.small,
            // A catalog figure is a NEAR MINT market price and is not
            // condition-adjusted. Labelled, never presented as a sale price.
            price: card.display_price,
            priceLabel: 'market',
          }}
        />
      )}

      <div role="radiogroup" aria-label="Card kind" className="flex items-center gap-4">
        {(['raw', 'graded'] as const).map((k) => (
          <label key={k} className="flex items-center gap-1.5 text-xs text-pine-200">
            <input
              type="radio"
              name="incoming-kind"
              value={k}
              checked={kind === k}
              // T13 422s a raw leg carrying graded fields, but a graded leg no
              // longer needs a card_id (RFC 0012) — `gradedSelectable` now
              // just mirrors `gradedAllowed`, which defaults to true and is
              // only false if a future caller explicitly withholds graded.
              disabled={k === 'graded' && !gradedSelectable}
              onChange={() => setKind(k)}
              className="accent-mint"
            />
            {k === 'raw' ? 'Raw' : 'Graded'}
          </label>
        ))}
      </div>

      {kind === 'raw' || !gradedSelectable ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <label className="flex flex-col gap-1">
            <span className="text-[11px] uppercase tracking-wider text-pine-400">Condition</span>
            <select
              aria-label="Condition"
              value={condition}
              className="vault-field w-full rounded-lg px-3 py-2 text-sm"
              onChange={(e) => setCondition(e.target.value)}
            >
              {CONDITION_OPTIONS.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[11px] uppercase tracking-wider text-pine-400">Finish</span>
            <select
              aria-label="Finish"
              value={finish}
              className="vault-field w-full rounded-lg px-3 py-2 text-sm"
              onChange={(e) => setFinish(e.target.value)}
            >
              {FINISHES.map((f) => (
                <option key={f} value={f}>
                  {f}
                </option>
              ))}
            </select>
          </label>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
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
              <span className="text-[11px] uppercase tracking-wider text-pine-400">Cert number</span>
              <input
                aria-label="Cert number"
                value={cert}
                className="vault-field w-full rounded-lg px-3 py-2 font-mono text-sm"
                onChange={(e) => setCert(e.target.value)}
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
          </div>

          {owned?.owned && (
            <p
              role="status"
              className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-300"
            >
              You already own cert {cert.trim()} ({owned.status}) — {owned.name}. You can still add
              it.
            </p>
          )}
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <label className="flex flex-col gap-1">
          <span className="text-[11px] uppercase tracking-wider text-pine-400">Language</span>
          <select
            aria-label="Language"
            value={language}
            className="vault-field w-full rounded-lg px-3 py-2 text-sm"
            onChange={(e) => setLanguage(e.target.value)}
          >
            {LANGUAGES.map((l) => (
              <option key={l.value} value={l.value}>
                {l.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
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
        <label className="flex flex-col gap-1">
          <span className="text-[11px] uppercase tracking-wider text-pine-400">Value</span>
          <MoneyInput label="Value" value={value} onChange={(raw) => setValue(raw)} />
        </label>
      </div>

      <div className="flex flex-col gap-2">
        {consignorPanel ? (
          <CosignorPicker value={consignorId} onChange={setConsignorId} />
        ) : (
          <button
            type="button"
            onClick={() => setConsignorPanel(true)}
            className="self-start text-[11px] text-mint hover:text-mint/80"
          >
            + Consignor
          </button>
        )}
      </div>

      {error && (
        // `status`, not `alert`: MoneyInput already owns the alert that says
        // what a readable amount looks like, and two live regions saying
        // almost the same thing is how an operator learns to ignore both.
        <p
          role="status"
          className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300"
        >
          {error}
        </p>
      )}

      <div className="flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="rounded-lg border border-pine-700/40 px-3 py-1.5 text-xs text-pine-300 transition-colors hover:text-pine-100"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={submit}
          className="rounded-lg border border-mint/30 bg-mint/15 px-3.5 py-1.5 text-xs font-medium text-mint transition-colors hover:bg-mint/25"
        >
          Add
        </button>
      </div>
    </div>
  )
}
