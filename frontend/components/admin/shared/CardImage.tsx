'use client'

import { useState } from 'react'

interface CardImageProps {
  imageUrl?: string | null
  alt: string
  size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl'
  className?: string
  loading?: 'lazy' | 'eager'
  /**
   * `data-testid` for the PLACEHOLDER branch only. Optional, and unset
   * everywhere it was not asked for, so no existing caller changes shape. It
   * exists because "did this row collapse, or did it render a placeholder at
   * the same height?" is the assertion the deal rows have to make, and an
   * `aria-label` query cannot distinguish a placeholder from a missing node.
   */
  placeholderTestId?: string
}

const SIZE_CLASSES = {
  // 56x78 — a real card's 63x88mm proportions. This is the row thumbnail: big
  // enough to recognise the art, small enough that the image is not what sets
  // the row height.
  xs: 'w-14 h-[4.875rem]',
  sm: 'w-24 h-[8.5rem]',
  md: 'w-40 h-56',
  lg: 'w-56 h-80',
  xl: 'w-72 h-[25.75rem]',
}

/**
 * The size every admin LIST/TABLE row uses for its card thumbnail, and the
 * width of the column holding it.
 *
 * These are exported constants rather than a per-page choice because the
 * per-page choice is exactly what went wrong: Inventory, Vault and Show Prep
 * each hard-coded `md` while Prep Queue hard-coded `lg`, and their columns
 * disagreed too (`w-16` vs `w-24`), so a 160-224px image sat in a 64-96px
 * cell on every one of those pages. Import these; do not re-pick a size.
 */
export const TABLE_THUMB_SIZE = 'xs' as const
export const TABLE_THUMB_COLUMN = 'w-16'

/**
 * Lazy-loaded card image with fallback placeholder.
 * Renders a Pokemon card thumbnail from TCGdex image URL.
 */
export default function CardImage({ imageUrl, alt, size = 'sm', className = '', loading = 'lazy', placeholderTestId }: CardImageProps) {
  const [error, setError] = useState(false)
  const sizeClass = SIZE_CLASSES[size]

  if (!imageUrl || error) {
    return (
      <div
        data-testid={placeholderTestId}
        className={`${sizeClass} rounded bg-pine-800/60 border border-pine-700/40 flex items-center justify-center flex-shrink-0 ${className}`}
        aria-label={`No image for ${alt}`}
      >
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          className="text-pine-600"
        >
          <rect x="3" y="3" width="18" height="18" rx="2" />
          <circle cx="8.5" cy="8.5" r="1.5" />
          <path d="M21 15l-5-5L5 21" />
        </svg>
      </div>
    )
  }

  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={imageUrl}
      alt={alt}
      loading={loading}
      onError={() => setError(true)}
      className={`${sizeClass} rounded object-cover border border-pine-700/40 flex-shrink-0 ${className}`}
    />
  )
}
