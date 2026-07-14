'use client'

import { useEffect, useState } from 'react'
import { useSession, signIn } from 'next-auth/react'
import Link from 'next/link'
import Image from 'next/image'
import { Menu } from 'lucide-react'
import Container from '@/components/ui/Container'
import Button from '@/components/ui/Button'

const links = [
  { href: '/shows', label: 'Shows' },
  { href: '/about', label: 'About' },
  { href: '/dictionary', label: 'Dictionary' },
  { href: '/articles', label: 'Articles' },
]

export default function Navbar() {
  const { status } = useSession()
  const [open, setOpen] = useState(false)

  // The inventory tool is gated: show a Sign in CTA until we know the visitor is
  // authenticated (optimistically show Inventory while the session is loading).
  const signedOut = status === 'unauthenticated'
  const startSignIn = () => {
    setOpen(false)
    signIn('cognito', { callbackUrl: '/inventory' })
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  return (
    <header className="sticky top-0 z-40 bg-cream/90 backdrop-blur border-b border-line">
      <Container>
        <nav className="relative flex items-center gap-4 h-[66px]">
          <Link href="/" className="flex items-center gap-2.5 min-w-0">
            <Image
              src="/images/logo/cat-logo.png"
              alt="Merlin's Minty Cards"
              width={32}
              height={32}
              className="rounded-full shrink-0"
            />
            <span className="font-serif font-semibold text-[16px] nav:text-[19px] text-forest-deep whitespace-nowrap truncate">
              Merlin&apos;s Minty Cards
            </span>
          </Link>

          <ul
            id="primary-menu"
            className={`${
              open ? 'flex' : 'hidden'
            } nav:flex flex-col nav:flex-row gap-0 nav:gap-[22px] absolute nav:static top-[66px] left-0 right-0 nav:top-auto bg-cream nav:bg-transparent border-b border-line nav:border-0 py-2 nav:py-0 shadow-lg nav:shadow-none ml-0 nav:ml-2.5 text-[17px] nav:text-[15px] font-medium`}
          >
            {links.map((l) => (
              <li key={l.href}>
                <Link
                  href={l.href}
                  onClick={() => setOpen(false)}
                  className="block px-7 py-3.5 nav:p-0 text-[#4a4339] hover:text-forest"
                >
                  {l.label}
                </Link>
              </li>
            ))}
            <li className="nav:hidden px-7 pt-1 pb-2">
              {signedOut ? (
                <button
                  type="button"
                  onClick={startSignIn}
                  className="block w-full rounded-full bg-forest text-white text-center font-semibold text-[15px] px-5 py-3 shadow-[0_8px_20px_rgba(31,110,50,0.25)] active:translate-y-px"
                >
                  Sign in
                </button>
              ) : (
                <Link
                  href="/inventory"
                  onClick={() => setOpen(false)}
                  className="block rounded-full bg-forest text-white text-center font-semibold text-[15px] px-5 py-3 shadow-[0_8px_20px_rgba(31,110,50,0.25)] active:translate-y-px"
                >
                  Inventory
                </Link>
              )}
            </li>
          </ul>

          <span className="flex-1" />

          {signedOut ? (
            <Button
              onClick={startSignIn}
              className="hidden nav:inline-block px-5 py-2.5 text-sm"
            >
              Sign in
            </Button>
          ) : (
            <Button href="/inventory" className="hidden nav:inline-block px-5 py-2.5 text-sm">
              Inventory
            </Button>
          )}

          <button
            type="button"
            aria-label="Menu"
            aria-expanded={open}
            aria-controls="primary-menu"
            onClick={() => setOpen((o) => !o)}
            className="nav:hidden flex shrink-0 items-center justify-center w-10 h-10 rounded-[10px] border-[1.5px] border-line text-forest-deep"
          >
            <Menu size={20} />
          </button>
        </nav>
      </Container>
    </header>
  )
}
