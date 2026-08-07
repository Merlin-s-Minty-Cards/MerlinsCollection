/**
 * Pure logic — no DOM. Runs in `node` rather than the default jsdom:
 * constructing a jsdom per file was the single largest cost in this
 * suite (215s cumulative `environment` time against 55s of actual tests).
 * If this file ever renders a component or touches window/document,
 * delete this docblock rather than stubbing the DOM by hand.
 *
 * @vitest-environment node
 */
import { describe, it, expect } from 'vitest'
import { resolveIsAdmin } from '@/lib/admin'

/** Build an unsigned JWT whose payload carries the given claims. */
function idTokenWith(claims: Record<string, unknown>): string {
  const b64url = (o: unknown) =>
    Buffer.from(JSON.stringify(o))
      .toString('base64')
      .replace(/\+/g, '-')
      .replace(/\//g, '_')
      .replace(/=+$/, '')
  return `${b64url({ alg: 'RS256' })}.${b64url(claims)}.sig`
}

describe('resolveIsAdmin', () => {
  it('is true when the ID token profile lists the admin group', () => {
    const profile = { 'cognito:groups': ['admins'] }

    expect(resolveIsAdmin({ profile })).toBe(true)
  })

  it('is false for a signed-in customer with no groups claim at all', () => {
    // This is the default state of every ordinary customer. Reading `.includes`
    // off an absent claim would throw inside the jwt callback and break sign-in
    // for everyone, so absence must be handled, not assumed away.
    expect(resolveIsAdmin({ profile: { email: 'collector@example.com' } })).toBe(false)
  })

  it('is false when the user belongs to groups, but not the admin one', () => {
    expect(resolveIsAdmin({ profile: { 'cognito:groups': ['customers'] } })).toBe(false)
  })

  it('is false when the groups claim is an empty list', () => {
    expect(resolveIsAdmin({ profile: { 'cognito:groups': [] } })).toBe(false)
  })

  it('matches the group name exactly, since Cognito group names are case-sensitive', () => {
    expect(resolveIsAdmin({ profile: { 'cognito:groups': ['Admins'] } })).toBe(false)
  })

  it('falls back to the ID token when the profile carries no groups', () => {
    // Cognito's /userinfo endpoint does not return cognito:groups, so depending
    // on how the claims are sourced they may only exist on the ID token.
    const account = { id_token: idTokenWith({ 'cognito:groups': ['admins'] }) }

    expect(resolveIsAdmin({ account, profile: { email: 'owner@example.com' } })).toBe(true)
  })

  it('is false, and does not throw, when the ID token is malformed', () => {
    // A throw here would fail the whole sign-in, locking the user out.
    expect(() => resolveIsAdmin({ account: { id_token: 'not-a-jwt' } })).not.toThrow()
    expect(resolveIsAdmin({ account: { id_token: 'not-a-jwt' } })).toBe(false)
  })

  it('is false when there is no account and no profile', () => {
    expect(resolveIsAdmin({})).toBe(false)
  })

  it('is false when the groups claim is not a list', () => {
    expect(resolveIsAdmin({ profile: { 'cognito:groups': 'admins' } })).toBe(false)
  })
})
