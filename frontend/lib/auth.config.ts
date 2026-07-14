import type { NextAuthConfig } from 'next-auth'
import Cognito from 'next-auth/providers/cognito'

/**
 * NextAuth config, kept separate from the `NextAuth()` call in `auth.ts` so it
 * can be imported without pulling in Node-only server internals (the standard
 * v5 split — also what keeps it unit-testable).
 *
 * The two callbacks are the whole point: Cognito's access token arrives once on
 * the `account` at sign-in, so `jwt` stashes it on the encrypted session token,
 * and `session` re-exposes it to the browser. Components read
 * `session.accessToken` and send it to the FastAPI backend as a bearer token,
 * which verifies it against the same Cognito user pool.
 */
export const authConfig: NextAuthConfig = {
  providers: [
    Cognito({
      clientId: process.env.AWS_COGNITO_CLIENT_ID,
      clientSecret: process.env.AWS_COGNITO_CLIENT_SECRET,
      issuer: process.env.AWS_COGNITO_ISSUER,
    }),
  ],
  callbacks: {
    async jwt({ token, account }) {
      // `account` is present only on the initial sign-in callback.
      if (account?.access_token) {
        token.accessToken = account.access_token
      }
      return token
    },
    async session({ session, token }) {
      session.accessToken = token.accessToken as string | undefined
      return session
    },
  },
}
