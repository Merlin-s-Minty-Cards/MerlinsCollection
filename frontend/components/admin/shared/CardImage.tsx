'use client'

import { useState } from 'react'

interface CardImageProps {
  imageUrl?: string | null
  alt: string
  size?: 'sm' | 'md' | 'lg'
  className?: string
}

const SIZE_CLASSES = {
  sm: 'w-10 h-14',
  md: 'w-16 h-22',
  lg: 'w-24 h-34',
}

/**
 * Lazy-loaded card image with fallback placeholder.
 * Renders a Pokemon card thumbnail from TCGdex image URL.
 */
export default function CardImage({ imageUrl, alt, size = 'sm', className = '' }: CardImageProps) {
  const [error, setError] = useState(false)
  const sizeClass = SIZE_CLASSES[size]

  if (!imageUrl || error) {
    return (
      <div
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
      loading="lazy"
      onError={() => setError(true)}
      className={`${sizeClass} rounded object-cover border border-pine-700/40 flex-shrink-0 ${className}`}
    />
  )
}
