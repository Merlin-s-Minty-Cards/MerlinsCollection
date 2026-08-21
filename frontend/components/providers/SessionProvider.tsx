'use client'

import { SessionProvider } from 'next-auth/react'

// Client boundary so `useSession()` in the inventory panels has a context to
// read. NextAuth fetches the session from /api/auth/session on mount.
//
// `refetchInterval` pings /api/auth/session every 4 minutes while the tab is
// open. This keeps the encrypted JWT cookie fresh — each ping triggers the jwt
// callback, which silently refreshes the Cognito access token before it expires
// (Cognito access tokens last 1 hour by default). Without this, the session
// only refreshes on window focus, and users who stay idle get logged out when
// the stale access token finally fails on the next server-side check.
//
// `refetchOnWindowFocus` is true by default (kept here explicitly for clarity)
// and handles the case where a user tabs away for hours then returns.
export default function AuthSessionProvider({ children }: { children: React.ReactNode }) {
  return (
    <SessionProvider refetchInterval={4 * 60} refetchOnWindowFocus={true}>
      {children}
    </SessionProvider>
  )
}
