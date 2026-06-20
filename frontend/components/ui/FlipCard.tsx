'use client'

import { useEffect, useRef, useState } from 'react'
import type { KeyboardEvent, ReactNode } from 'react'

export default function FlipCard({
  front,
  back,
  label = 'Flip card',
  className = '',
}: {
  front: ReactNode
  back: ReactNode
  label?: string
  className?: string
}) {
  const [flipped, setFlipped] = useState(false)
  const stageRef = useRef<HTMLDivElement>(null)

  // One-time "peek" when the card first enters view, unless reduced motion.
  useEffect(() => {
    const el = stageRef.current
    if (!el) return
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    if (reduce || typeof IntersectionObserver === 'undefined') return

    let done = false
    let inner: ReturnType<typeof setTimeout> | undefined
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting && !done) {
            done = true
            inner = setTimeout(() => {
              setFlipped(true)
              inner = setTimeout(() => setFlipped(false), 1000)
            }, 600)
          }
        })
      },
      { threshold: 0.6 },
    )
    io.observe(el)
    return () => {
      io.disconnect()
      if (inner) clearTimeout(inner)
    }
  }, [])

  const toggle = () => setFlipped((f) => !f)
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      toggle()
    }
  }

  return (
    <div
      ref={stageRef}
      className={`flip-stage ${className}`}
      role="button"
      tabIndex={0}
      aria-label={label}
      aria-pressed={flipped}
      data-flipped={flipped}
      onClick={toggle}
      onKeyDown={onKeyDown}
    >
      <div className={`flip-inner ${flipped ? 'is-flipped' : ''}`}>
        <div className="flip-face flip-front">{front}</div>
        <div className="flip-face flip-back">{back}</div>
      </div>
    </div>
  )
}
