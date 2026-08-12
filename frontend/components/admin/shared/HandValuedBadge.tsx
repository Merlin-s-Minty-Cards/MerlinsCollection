import { Hand } from 'lucide-react'

/**
 * "This number came from a person, and no sync will ever revisit it."
 * docs/plans/rfc-0010/t16-unmatched-card-valuation.md
 *
 * A market figure and a hand-typed one look identical on screen and mean
 * opposite things: one is replaced nightly, the other is replaced never. Without
 * the marker an admin reads a blank Market column as "the price hasn't synced
 * yet" and waits for something that is not coming.
 *
 * Not a status badge — `StatusBadge`'s vocabulary is inventory lifecycle
 * (`available`/`sold`) plus the two entity-lifecycle styles T2 added, and this is
 * neither. Same rule as "an `Archived` badge never reuses inventory-status
 * vocabulary" (CLAUDE.md).
 */
export default function HandValuedBadge({
  explain = false,
  className = '',
}: {
  /** Render the reason beside the chip. On for a detail panel, off in a table row. */
  explain?: boolean
  className?: string
}) {
  return (
    <span className={`inline-flex flex-wrap items-center gap-1.5 ${className}`}>
      <span
        title="Not in the catalog — no sync will ever price this card, so its value is set by hand."
        className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px]
                   bg-sky-400/10 text-sky-300 border border-sky-400/25 whitespace-nowrap"
      >
        <Hand size={9} /> Hand-valued
      </span>
      {explain && (
        <span className="text-[10px] text-pine-400">
          Not in the catalog — no sync will ever price this card.
        </span>
      )}
    </span>
  )
}
