import Link from 'next/link'
import type { ReactNode } from 'react'

type Variant = 'primary' | 'ghost'

const base =
  'inline-block rounded-full text-center font-semibold text-[15px] px-6 py-3 transition-transform active:translate-y-px'

const variantClasses: Record<Variant, string> = {
  primary: 'bg-forest text-white shadow-[0_8px_20px_rgba(31,110,50,0.25)]',
  ghost: 'border-[1.5px] border-forest text-forest',
}

export default function Button({
  href,
  variant = 'primary',
  className = '',
  children,
}: {
  href?: string
  variant?: Variant
  className?: string
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
    <button type="button" data-variant={variant} className={classes}>
      {children}
    </button>
  )
}
