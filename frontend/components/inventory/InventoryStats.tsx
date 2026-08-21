'use client'

import { useEffect, useState } from 'react'
import { useSession } from 'next-auth/react'
import { getInventorySummary, formatPrice, type InventorySummary } from '@/lib/inventory'

// The three dashboard-header stats, in order. Labels are unchanged from the
// placeholder version; only the values are now real.
const LABELS = ['Cards in vault', 'Est. value', 'Sets tracked'] as const

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
          formatPrice(summary.est_value),
          integer.format(summary.sets_tracked),
        ]
      : [PLACEHOLDER, PLACEHOLDER, PLACEHOLDER]

  return (
    <dl className="mt-7 grid max-w-md grid-cols-3 gap-4">
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
