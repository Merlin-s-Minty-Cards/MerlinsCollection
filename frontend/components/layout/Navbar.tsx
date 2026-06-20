'use client'

import { useEffect, useState } from 'react'
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
  const [open, setOpen] = useState(false)

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
          <Link href="/" className="flex items-center gap-2.5 shrink-0">
            <Image
              src="/images/logo/cat-logo.png"
              alt="Merlin's Minty Cards"
              width={32}
              height={32}
              className="rounded-full shrink-0"
            />
            <span className="font-serif font-semibold text-[16px] nav:text-[19px] text-forest-deep whitespace-nowrap">
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
          </ul>

          <span className="flex-1" />

          <Button href="/inventory" className="px-4 nav:px-5 py-2.5 text-[13px] nav:text-sm">
            Inventory
          </Button>

          <button
            type="button"
            aria-label="Menu"
            aria-expanded={open}
            aria-controls="primary-menu"
            onClick={() => setOpen((o) => !o)}
            className="nav:hidden flex items-center justify-center w-10 h-10 rounded-[10px] border-[1.5px] border-line text-forest-deep"
          >
            <Menu size={18} />
          </button>
        </nav>
      </Container>
    </header>
  )
}
