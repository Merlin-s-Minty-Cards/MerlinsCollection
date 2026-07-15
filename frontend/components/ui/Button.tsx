import Link from 'next/link'
import type { ReactNode } from 'react'

type Variant = 'primary' | 'ghost'

const base =
  'inline-block rounded-full text-center font-semibold text-[15px] px-6 py-3 transition-all duration-200 active:translate-y-px'

const variantClasses: Record<Variant, string> = {
  primary:
    'bg-forest text-white shadow-[0_8px_20px_rgba(31,110,50,0.25)] hover:-translate-y-0.5 hover:shadow-[0_14px_30px_rgba(31,110,50,0.35)]',
  ghost: 'border-[1.5px] border-forest text-forest hover:bg-forest/[0.06]',
}

/**
 * Brand call-to-action. Renders a Next.js `<Link>` when `href` is provided,
 * otherwise a plain `<button>` (pass `onClick` for that case). `variant`
 * selects the look — solid forest (`primary`) or outlined (`ghost`) — and is
 * mirrored to a `data-variant` attribute so tests and styles can target it.
 */
export default function Button({
  href,
  variant = 'primary',
  className = '',
  onClick,
  children,
}: {
  href?: string
  variant?: Variant
  className?: string
  onClick?: () => void
  children: ReactNode
}) {
  const classes = `${base} ${variantClasses[variant]} ${className}`
  if (href) {
    return (
      <Link href={href} data-variant={variant} className={classes}>
        {children}
      </Link>
    )
  }
  return (
    <button type="button" data-variant={variant} className={classes} onClick={onClick}>
      {children}
    </button>
  )
}
