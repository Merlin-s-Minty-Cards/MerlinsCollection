import type { NextAuthConfig } from 'next-auth'
import type { JWT } from 'next-auth/jwt'
import Cognito from 'next-auth/providers/cognito'
import { resolveIsAdmin } from './admin'

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
  // Phase 17: explicit session configuration so the session lifetime is visible
  // and not reliant on undocumented NextAuth defaults.
  session: {
    strategy: 'jwt',
    // How long the encrypted session cookie lives. Set to 30 days (Cognito
    // refresh token default). The access token inside refreshes silently via
    // the jwt callback; this outer lifetime is when the user must fully
    // re-authenticate regardless.
    maxAge: 30 * 24 * 60 * 60, // 30 days in seconds
  },
  callbacks: {
    async jwt({ token, account, profile }) {
      // `account` is present only on the initial sign-in callback: capture the
      // access token, the refresh token, when the access token expires, and the
      // admin group membership.
      if (account?.access_token) {
        token.accessToken = account.access_token
        token.refreshToken = account.refresh_token
        token.accessTokenExpires =
          Date.now() + Number(account.expires_in ?? 0) * 1000
        // Group membership is only visible at sign-in, so it is resolved once and
        // carried on the session token. NOTE: that means removing someone from the
        // admins group does not take effect until their session expires. Refresh-
        // token rotation would re-derive this hourly; see the follow-up.
        token.isAdmin = resolveIsAdmin({ account, profile })
        return token
      }

      // Subsequent calls: if the access token is still comfortably valid, use it
      // as-is. Refresh a little before the hard expiry (REFRESH_BUFFER_MS) so a
      // request in flight near the boundary — or a backend clock running ahead —
      // doesn't reach Cognito with an already-expired token.
      const expires = token.accessTokenExpires
      if (typeof expires === 'number' && expires > 0 && Date.now() < expires - REFRESH_BUFFER_MS) {
        return token
      }

      // If accessTokenExpires was never set (legacy token from before refresh
      // logic existed), leave the token alone — we can't know if it's expired.
      if (typeof expires !== 'number' || expires === 0) {
        return token
      }

      // Token is expired. If we have no refresh token, flag the error so the
      // session degrades cleanly rather than letting stale access tokens silently
      // fail on every backend call (Phase 17 fix).
      if (!token.refreshToken) {
        return { ...token, error: 'RefreshAccessTokenError' }
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
      session.isAdmin = token.isAdmin === true
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
