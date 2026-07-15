import NextAuth from 'next-auth'
import { authConfig } from './auth.config'

// Config lives in ./auth.config (edge-safe, unit-testable); this module makes
// the runtime handlers. Next.js 15 note: cookies(), headers(), params, and
// searchParams are async — await them where needed in server code.
export const { handlers, auth, signIn, signOut } = NextAuth(authConfig)
