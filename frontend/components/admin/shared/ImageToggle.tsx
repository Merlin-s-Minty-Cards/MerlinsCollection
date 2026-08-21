'use client'

import { Eye, EyeOff } from 'lucide-react'

interface ImageToggleProps {
  /** Whether images are currently visible */
  showImages: boolean
  /** Toggle callback */
  onToggle: () => void
  /** Label text (optional) */
  label?: string
  /** Size variant */
  size?: 'sm' | 'md'
}

/**
 * A toggle button for showing/hiding card images.
 * Use as a global page-level toggle or per-card toggle.
 */
export default function ImageToggle({
  showImages,
  onToggle,
  label,
  size = 'md',
}: ImageToggleProps) {
  const iconSize = size === 'sm' ? 12 : 14
  const padding = size === 'sm' ? 'px-1.5 py-1' : 'px-2.5 py-1.5'

  return (
    <button
      type="button"
      onClick={onToggle}
      className={`inline-flex items-center gap-1.5 ${padding} rounded-md text-[11px] font-medium border transition-colors ${
        showImages
          ? 'border-mint/40 text-mint bg-mint/10 hover:bg-mint/15'
          : 'border-pine-700/40 text-pine-400 hover:text-pine-200 hover:border-pine-600'
      }`}
      title={showImages ? 'Hide images' : 'Show images'}
      aria-pressed={showImages}
      aria-label={label ?? (showImages ? 'Hide card images' : 'Show card images')}
    >
      {/* eslint-disable-next-line jsx-a11y/alt-text */}
      {showImages ? <Eye size={iconSize} /> : <EyeOff size={iconSize} />}
      {label && <span>{label}</span>}
    </button>
  )
}
