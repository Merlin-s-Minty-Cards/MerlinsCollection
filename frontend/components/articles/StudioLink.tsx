'use client'

import { useSession } from 'next-auth/react'
import Button from '@/components/ui/Button'

/**
 * Shortcut into the CMS, shown only to admins.
 *
 * Client-side on purpose. /articles is ISR-cached and that HTML is shared by
 * every visitor, so the page itself must not call `auth()` — reading cookies
 * would force the route dynamic and defeat the cache. Resolving the session in
 * the browser instead keeps the cached HTML identical for everyone.
 *
 * For the same reason this must render *nothing* for non-admins rather than
 * hiding a rendered link with CSS: hidden markup would still be baked into the
 * shared HTML. This is a navigation affordance, not a security control — the
 * real gate is the server check in app/studio/layout.tsx.
 */
export default function StudioLink() {
  const { data: session } = useSession()

  if (!session?.isAdmin) return null

  return (
    <Button href="/studio" className="px-5 py-2.5 text-sm">
      Open Studio
    </Button>
  )
}
