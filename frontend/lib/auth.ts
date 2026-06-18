import NextAuth from 'next-auth'
import type { NextAuthConfig } from 'next-auth'

// Next.js 15 note: cookies(), headers(), params, searchParams are now async.
// When adding Cognito providers, await these where needed.
export const config: NextAuthConfig = {
  providers: [],
  callbacks: {},
}

export const { handlers, auth, signIn, signOut } = NextAuth(config)
