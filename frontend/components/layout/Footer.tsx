'use client'

import { useSession, signOut } from 'next-auth/react'
import Link from 'next/link'
import Image from 'next/image'
import Container from '@/components/ui/Container'

type Item = { label: string; href: string }
const columns: { heading: string; items: Item[] }[] = [
  {
    heading: 'Explore',
    items: [
      { label: 'Shows', href: '/shows' },
      { label: 'About', href: '/about' },
      { label: 'Articles', href: '/articles' },
      { label: 'Dictionary', href: '/dictionary' },
    ],
  },
  {
    heading: 'Collect',
    items: [
      { label: 'Inventory', href: '/inventory' },
      { label: 'Sell to us', href: '/about' },
    ],
  },
  {
    heading: 'Follow',
    items: [
      { label: 'Instagram', href: 'https://instagram.com/merlinsmintycards' },
      { label: 'Contact', href: '/about#contact' },
    ],
  },
]

const footerLinkClassName = 'block text-[14px] text-[#bcd6c4] py-1 hover:text-mint'

function FooterLink({ item }: { item: Item }) {
  if (/^https?:/.test(item.href)) {
    return (
      <a href={item.href} target="_blank" rel="noopener noreferrer" className={footerLinkClassName}>
        {item.label}
      </a>
    )
  }
  return (
    <Link href={item.href} className={footerLinkClassName}>
      {item.label}
    </Link>
  )
}

/**
 * The one session-dependent entry in the footer — which is why Footer has to
 * be a Client Component even though everything else here is static links.
 * Signed out: a plain "Sign in" link to /inventory, same as before (the
 * Navbar owns the actual sign-in CTA; this just gets a visitor there).
 * Signed in: "Sign out", styled identically to every other footer link
 * rather than as a Button — deliberately low-visibility, per the request,
 * not a second CTA competing with the Navbar's.
 */
function FooterAuthLink() {
  const { data: session, status } = useSession()
  const signedOut = status === 'unauthenticated' || Boolean(session?.error)

  if (signedOut) {
    return (
      <Link href="/inventory" className={footerLinkClassName}>
        Sign in
      </Link>
    )
  }

  return (
    <button
      type="button"
      onClick={() => signOut({ callbackUrl: '/' })}
      className={`${footerLinkClassName} w-full text-left`}
    >
      Sign out
    </button>
  )
}

export default function Footer() {
  return (
    <footer className="bg-forest-deep text-[#bcd6c4] pt-[54px] pb-[30px]">
      <Container>
        <div className="grid grid-cols-1 sm:grid-cols-2 nav:grid-cols-[2fr_1fr_1fr_1fr] gap-[30px]">
          <div>
            <div className="flex items-center gap-2.5 mb-3 text-white">
              <Image
                src="/images/logo/cat-logo.png"
                alt="Merlin's Minty Cards"
                width={32}
                height={32}
                className="rounded-full shrink-0"
              />
              <span className="font-serif font-semibold text-[19px]">Merlin&apos;s Minty Cards</span>
            </div>
            <p className="text-[14px] text-[#9fbfa8] max-w-[34ch]">
              Buy. Sell. Trade. Meow.
            </p>
          </div>
          {columns.map((col) => (
            <div key={col.heading}>
              <h5 className="font-sans text-[14px] uppercase tracking-[0.06em] text-white mb-3.5">
                {col.heading}
              </h5>
              {col.items.map((item) => (
                <FooterLink key={item.label + item.href} item={item} />
              ))}
              {col.heading === 'Collect' && <FooterAuthLink />}
            </div>
          ))}
        </div>
        <div className="flex flex-wrap gap-3.5 justify-between border-t border-white/10 mt-[34px] pt-[18px] text-[13px] text-[#8fae98]">
          <span>© {new Date().getFullYear()} Merlin&apos;s Minty Cards LLC</span>
          <span>Privacy · Terms</span>
        </div>
      </Container>
    </footer>
  )
}
