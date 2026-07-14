'use client'

import { SessionProvider } from 'next-auth/react'

// Client boundary so `useSession()` in the inventory panels has a context to
// read. NextAuth fetches the session from /api/auth/session on mount.
export default function AuthSessionProvider({ children }: { children: React.ReactNode }) {
  return <SessionProvider>{children}</SessionProvider>
}
