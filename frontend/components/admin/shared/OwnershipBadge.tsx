interface OwnershipBadgeProps {
  consigned: boolean
}

/**
 * Small pill indicating whether an inventory item is consigned or owned.
 */
export default function OwnershipBadge({ consigned }: OwnershipBadgeProps) {
  const classes = consigned
    ? 'bg-amber-500/15 text-amber-300 border border-amber-500/30'
    : 'bg-mint/10 text-mint border border-mint/30'

  return (
    <span className={`text-xs px-2 py-0.5 rounded-full ${classes}`}>
      {consigned ? 'Cosigned' : 'Owned'}
    </span>
  )
}
