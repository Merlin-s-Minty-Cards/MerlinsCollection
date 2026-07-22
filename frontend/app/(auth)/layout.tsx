import { redirect } from 'next/navigation'
import { auth } from '@/lib/auth'
import Navbar from '@/components/layout/Navbar'
import Footer from '@/components/layout/Footer'

// Server-side gate for the inventory tool: an unauthenticated visitor is sent to
// sign in (with a callback back here) before any page under (auth) renders, so
// the protected UI never loads without a session. The session itself is exposed
// to client components by the SessionProvider in the root layout. The shared
// brand-green chrome (Navbar/Footer) frames the page; the dark "vault" theme
// lives inside it (see the .vault-* styles in globals.css).
export default async function AuthLayout({ children }: { children: React.ReactNode }) {
  const session = await auth()
  // No session, or a session whose Cognito token could no longer be refreshed
  // (`session.error`): either way the visitor is effectively signed out and must
  // not load the protected page.
  if (!session || session.error) {
    redirect('/api/auth/signin?callbackUrl=/inventory')
  }
  return (
    <>
      <Navbar />
      <main>{children}</main>
      <Footer />
    </>
  )
}
