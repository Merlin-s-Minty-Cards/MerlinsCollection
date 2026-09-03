'use client'

import { useEffect, useState } from 'react'
import { useSession } from 'next-auth/react'
import { getInventorySummary, type InventorySummary } from '@/lib/inventory'

// RFC 0025 T5 — the owner asked for the Est. value tile removed (only the
// middle tile; two counts are not a valuation, which is why the other two
// stay). The grid is `auto-fit` below, so dropping a tile needs no layout
// rework — it just reflows.
const LABELS = ['Cards in vault', 'Sets tracked'] as const

const PLACEHOLDER = '—'

const integer = new Intl.NumberFormat('en-US')

/**
 * Live dashboard stats over the same customer-visible cohort as the search.
 * Fetches /inventory/summary with the user's Cognito token. While loading or on
 * any error it renders "—" placeholders (never the old fake numbers, never a
 * crash) so the authed page always stays intact.
 */
export default function InventoryStats() {
  const { data: session } = useSession()
  const token = session?.accessToken
  const [summary, setSummary] = useState<InventorySummary | null>(null)
  const [errored, setErrored] = useState(false)

  useEffect(() => {
    // Wait for the session token to hydrate before fetching — calling with no
    // token would guarantee a 401 (and a "—" flash) on every dashboard load.
    if (!token) return
    let active = true
    setSummary(null)
    setErrored(false)
    getInventorySummary({ token })
      .then((data) => {
        if (active) setSummary(data)
      })
      .catch(() => {
        if (active) setErrored(true)
      })
    return () => {
      active = false
    }
  }, [token])

  const values =
    summary && !errored
      ? [
          integer.format(summary.cards_in_vault),
          integer.format(summary.sets_tracked),
        ]
      : [PLACEHOLDER, PLACEHOLDER]

  // auto-fit rather than a fixed grid-cols-3: at 390px the three fixed columns
  // were ~105px each while "$10,517.69" at text-lg needs ~110px, so the value
  // overflowed its card and collided with the one beside it (measured in a live
  // browser pass, 2026-08-27). auto-fit reflows instead of overflowing, and
  // needs no breakpoint because it responds to the real container, not the
  // viewport.
  return (
    <dl className="mt-7 grid max-w-md grid-cols-[repeat(auto-fit,minmax(7.5rem,1fr))] gap-4">
      {LABELS.map((label, i) => (
        <div key={label} className="rounded-xl border border-pine-700 bg-pine-950/60 px-3 py-3">
          <dt className="font-mono text-[10px] uppercase tracking-[0.1em] text-pine-300">
            {label}
          </dt>
          <dd className="mt-1 font-mono text-lg font-semibold text-pine-100">{values[i]}</dd>
        </div>
      ))}
    </dl>
  )
}
