import 'next-auth'
import 'next-auth/jwt'

// The Cognito access token is threaded from sign-in to the browser session so
// components can attach it to backend requests (see lib/auth.config.ts).
declare module 'next-auth' {
  interface Session {
    accessToken?: string
    /** Member of the Cognito admins group; gates the Studio. */
    isAdmin?: boolean
  }
}

declare module 'next-auth/jwt' {
  interface JWT {
    accessToken?: string
    isAdmin?: boolean
  }
}
