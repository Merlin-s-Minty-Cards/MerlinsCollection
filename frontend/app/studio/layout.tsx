import type { Metadata, Viewport } from 'next'
import { redirect, notFound } from 'next/navigation'
import { auth } from '@/lib/auth'

export const metadata: Metadata = {
  title: 'Studio',
  // The Studio is staff-only; keep it out of search results.
  robots: { index: false, follow: false },
}

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  viewportFit: 'cover',
}

/**
 * Server-side gate for the Studio. Signed-out visitors are sent to sign in;
 * signed-in non-admins get a 404, since a customer has no business learning the
 * route exists.
 *
 * This is defence in depth, NOT the boundary that protects the content: the
 * Studio talks to Sanity directly from the browser using the visitor's own
 * Sanity session, so what actually guards the CMS is the Sanity project's member
 * list. Someone who is a Sanity member can still edit via sanity.io/manage
 * regardless of this check — which is also the break-glass path if Cognito is
 * ever unavailable.
 */
export default async function StudioLayout({ children }: { children: React.ReactNode }) {
  const session = await auth()
  if (!session) {
    redirect('/api/auth/signin?callbackUrl=/studio')
  }
  if (!session.isAdmin) {
    notFound()
  }
  return children
}
