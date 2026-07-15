import { describe, it, expect } from 'vitest'
import { authConfig as config } from '@/lib/auth.config'

// The Cognito provider and the two callbacks are what carry the access token
// from sign-in through to the browser session; the components then attach it as
// a bearer token on every backend call.
describe('auth config', () => {
  it('registers a Cognito provider', () => {
    expect(config.providers).toHaveLength(1)
  })

  it('jwt callback captures the access token on first sign-in', async () => {
    const token = await config.callbacks!.jwt!({
      token: {},
      account: { access_token: 'cognito-access-token' },
    } as never)
    expect(token).toMatchObject({ accessToken: 'cognito-access-token' })
  })

  it('jwt callback leaves the token untouched on later calls (no account)', async () => {
    const token = await config.callbacks!.jwt!({
      token: { sub: 'user-1' },
      account: null,
    } as never)
    expect(token).toEqual({ sub: 'user-1' })
  })

  it('session callback exposes the access token to the client', async () => {
    const session = await config.callbacks!.session!({
      session: { user: {}, expires: '2026-01-01' },
      token: { accessToken: 'cognito-access-token' },
    } as never)
    expect(session).toMatchObject({ accessToken: 'cognito-access-token' })
  })
})
