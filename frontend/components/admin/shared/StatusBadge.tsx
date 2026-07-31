const statusStyles: Record<string, string> = {
  available: 'bg-mint/15 text-mint border-mint/30',
  sold: 'bg-pine-400/15 text-pine-300 border-pine-400/30',
  lost: 'bg-red-500/15 text-red-400 border-red-500/30',
  on_hold: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
  consigned: 'bg-blue-400/15 text-blue-300 border-blue-400/30',
  draft: 'bg-pine-400/15 text-pine-300 border-pine-400/30',
  confirmed: 'bg-mint/15 text-mint border-mint/30',
  cancelled: 'bg-red-500/15 text-red-400 border-red-500/30',
}

interface StatusBadgeProps {
  status: string
  className?: string
}

export default function StatusBadge({ status, className = '' }: StatusBadgeProps) {
  const style = statusStyles[status] ?? 'bg-pine-700/40 text-pine-300 border-pine-600/30'

  return (
    <span
      className={`
        inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-medium
        uppercase tracking-wider border ${style} ${className}
      `}
    >
      {status.replace(/_/g, ' ')}
    </span>
  )
}
