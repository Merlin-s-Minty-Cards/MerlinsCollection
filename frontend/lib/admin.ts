/**
 * Admin identity, derived from Cognito group membership.
 *
 * Admins are members of a Cognito group (default `admins`, see COGNITO_ADMIN_GROUP).
 * Cognito puts that membership in the `cognito:groups` claim of the ID token.
 */

// Cognito group names are case-sensitive, so this must match the console exactly.
// `||` (not `??`) so a blank env var falls back rather than making every admin
// check compare against '' and silently 404 every admin at /studio.
const ADMIN_GROUP = process.env.COGNITO_ADMIN_GROUP || 'admins'

const GROUPS_CLAIM = 'cognito:groups'

type Claims = Record<string, unknown> | null | undefined

/**
 * Read the payload of an ID token WITHOUT verifying its signature.
 *
 * Safe *only* here: this runs inside the NextAuth `jwt` callback on the token
 * Auth.js just received from Cognito and cryptographically verified during the
 * OAuth code exchange. It is deliberately module-private and never exported —
 * pointed at an attacker-supplied token (say, an Authorization header) an
 * unverified decode is a straight privilege escalation.
 */
function claimsFromIdToken(idToken: unknown): Claims {
  if (typeof idToken !== 'string') return null
  try {
    const payload = idToken.split('.')[1]
    if (!payload) return null
    // JWTs use base64url (`-`/`_`, unpadded); atob wants padded base64.
    const base64 = payload.replace(/-/g, '+').replace(/_/g, '/')
    const padded = base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), '=')
    return JSON.parse(atob(padded))
  } catch {
    // A malformed token means "not an admin", never a crash: throwing in the
    // jwt callback fails the entire sign-in and locks the user out.
    return null
  }
}

function groupsFrom(claims: Claims): string[] {
  const groups = claims?.[GROUPS_CLAIM]
  // Cognito omits the claim entirely for users in no groups — the normal state
  // of every customer — so absence and non-arrays must both read as "no groups".
  return Array.isArray(groups) ? groups.filter((g): g is string => typeof g === 'string') : []
}

/**
 * Decide whether a signing-in user is an admin.
 *
 * Prefers the profile claims Auth.js already parsed; falls back to the ID token
 * because Cognito's /userinfo endpoint does not return `cognito:groups`.
 */
export function resolveIsAdmin({
  account,
  profile,
}: {
  account?: { id_token?: unknown } | null
  profile?: Claims
}): boolean {
  const groups = [...groupsFrom(profile), ...groupsFrom(claimsFromIdToken(account?.id_token))]
  return groups.includes(ADMIN_GROUP)
}
