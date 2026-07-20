import type { NextAuthConfig } from 'next-auth'
import type { JWT } from 'next-auth/jwt'
import Cognito from 'next-auth/providers/cognito'

/** Refresh this long before the access token's hard expiry to absorb clock skew. */
const REFRESH_BUFFER_MS = 60 * 1000

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
      // `account` is present only on the initial sign-in callback: capture the
      // access token, the refresh token, and when the access token expires.
      if (account?.access_token) {
        token.accessToken = account.access_token
        token.refreshToken = account.refresh_token
        token.accessTokenExpires =
          Date.now() + Number(account.expires_in ?? 0) * 1000
        return token
      }

      // Subsequent calls: if the access token is still comfortably valid, use it
      // as-is. Refresh a little before the hard expiry (REFRESH_BUFFER_MS) so a
      // request in flight near the boundary — or a backend clock running ahead —
      // doesn't reach Cognito with an already-expired token.
      const expires = token.accessTokenExpires
      if (typeof expires === 'number' && Date.now() < expires - REFRESH_BUFFER_MS) {
        return token
      }

      // Expired but nothing to refresh with — leave the token untouched.
      if (!token.refreshToken) {
        return token
      }

      // Expired: exchange the refresh token for a fresh access token.
      return refreshAccessToken(token)
    },
    async session({ session, token }) {
      // A refresh failure means the embedded access token is no longer usable;
      // don't expose it, and forward the error so the client can react.
      if (token.error) {
        session.accessToken = undefined
        session.error = token.error
        return session
      }
      session.accessToken = token.accessToken as string | undefined
      return session
    },
  },
}

/**
 * Exchange the stored Cognito refresh token for a new access token. On success
 * returns the token with a fresh `accessToken`/`accessTokenExpires` (and the
 * rotated `refreshToken`, if Cognito issued one). On failure it flags the token
 * with `error = 'RefreshAccessTokenError'` rather than throwing, so the session
 * callback can degrade the session to signed-out instead of crashing.
 */
async function refreshAccessToken(token: JWT): Promise<JWT> {
  try {
    const issuer = process.env.AWS_COGNITO_ISSUER
    const clientId = process.env.AWS_COGNITO_CLIENT_ID ?? ''
    const clientSecret = process.env.AWS_COGNITO_CLIENT_SECRET ?? ''

    const body = new URLSearchParams({
      grant_type: 'refresh_token',
      client_id: clientId,
      refresh_token: token.refreshToken as string,
    })

    const response = await fetch(`${issuer}/oauth2/token`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        Authorization: `Basic ${Buffer.from(
          `${clientId}:${clientSecret}`,
        ).toString('base64')}`,
      },
      body,
    })

    const refreshed = await response.json()
    if (!response.ok) {
      throw new Error('Failed to refresh access token')
    }

    return {
      ...token,
      accessToken: refreshed.access_token,
      accessTokenExpires: Date.now() + Number(refreshed.expires_in ?? 0) * 1000,
      // Cognito may rotate the refresh token; fall back to the existing one.
      refreshToken: refreshed.refresh_token ?? token.refreshToken,
      error: undefined,
    }
  } catch {
    return { ...token, error: 'RefreshAccessTokenError' }
  }
}
