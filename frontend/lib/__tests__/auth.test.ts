import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { authConfig as config } from '@/lib/auth.config'

// The Cognito provider and the two callbacks are what carry the access token
// from sign-in through to the browser session; the components then attach it as
// a bearer token on every backend call.
describe('auth config', () => {
  it('registers a Cognito provider', () => {
    expect(config.providers).toHaveLength(1)
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

// --- Token refresh lifecycle -------------------------------------------------
//
// The Cognito access token expires (~60 min) long before NextAuth's own session
// cookie (30 days). Without refresh, a stale access token is silently treated as
// a valid session. These tests pin down the refresh behaviour of the `jwt` and
// `session` callbacks.
describe('auth config — access token refresh', () => {
  const ISSUER = 'https://cognito.example.com/pool'

  beforeEach(() => {
    process.env.AWS_COGNITO_ISSUER = ISSUER
    process.env.AWS_COGNITO_CLIENT_ID = 'client-123'
    process.env.AWS_COGNITO_CLIENT_SECRET = 'secret-abc'
    vi.restoreAllMocks()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('stores accessToken, refreshToken and accessTokenExpires on first sign-in', async () => {
    const before = Date.now()
    const token = await config.callbacks!.jwt!({
      token: {},
      account: {
        access_token: 'cognito-access-token',
        refresh_token: 'cognito-refresh-token',
        expires_in: 3600,
      },
    } as never)

    expect(token).toMatchObject({
      accessToken: 'cognito-access-token',
      refreshToken: 'cognito-refresh-token',
    })
    // accessTokenExpires is ~now + expires_in seconds, in ms.
    const expires = (token as { accessTokenExpires: number }).accessTokenExpires
    expect(typeof expires).toBe('number')
    expect(expires).toBeGreaterThanOrEqual(before + 3600 * 1000)
    expect(expires).toBeLessThanOrEqual(Date.now() + 3600 * 1000 + 1000)
  })

  it('returns the token unchanged (no refresh) while the access token is still valid', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch')
    const validToken = {
      accessToken: 'still-good',
      refreshToken: 'refresh-token',
      accessTokenExpires: Date.now() + 30 * 60 * 1000, // 30 min ahead
    }

    const token = await config.callbacks!.jwt!({
      token: { ...validToken },
      account: null,
    } as never)

    expect(fetchSpy).not.toHaveBeenCalled()
    expect(token).toEqual(validToken)
  })

  it('refreshes proactively when the token is within the clock-skew buffer of expiry', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ access_token: 'fresh-access-token', expires_in: 3600 }),
    } as Response)

    await config.callbacks!.jwt!({
      token: {
        accessToken: 'about-to-expire',
        refreshToken: 'refresh-token',
        accessTokenExpires: Date.now() + 15 * 1000, // 15s ahead — inside the buffer
      },
      account: null,
    } as never)

    expect(fetchSpy).toHaveBeenCalledTimes(1)
  })

  it('refreshes the access token via the Cognito token endpoint once expired', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({
        access_token: 'fresh-access-token',
        expires_in: 3600,
        refresh_token: 'rotated-refresh-token',
      }),
    } as Response)

    const before = Date.now()
    const token = await config.callbacks!.jwt!({
      token: {
        accessToken: 'stale-access-token',
        refreshToken: 'old-refresh-token',
        accessTokenExpires: Date.now() - 1000, // already expired
      },
      account: null,
    } as never)

    expect(fetchSpy).toHaveBeenCalledTimes(1)
    const [url, init] = fetchSpy.mock.calls[0]
    expect(url).toBe(`${ISSUER}/oauth2/token`)
    const body = String((init as RequestInit).body)
    expect(body).toContain('grant_type=refresh_token')
    expect(body).toContain('old-refresh-token')

    expect(token).toMatchObject({
      accessToken: 'fresh-access-token',
      refreshToken: 'rotated-refresh-token',
    })
    const expires = (token as { accessTokenExpires: number }).accessTokenExpires
    expect(expires).toBeGreaterThanOrEqual(before + 3600 * 1000)
    expect((token as { error?: string }).error).toBeUndefined()
  })

  it('sets token.error = RefreshAccessTokenError when the refresh request fails (does not throw)', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: false,
      status: 400,
      json: async () => ({ error: 'invalid_grant' }),
    } as Response)

    const token = await config.callbacks!.jwt!({
      token: {
        accessToken: 'stale-access-token',
        refreshToken: 'revoked-refresh-token',
        accessTokenExpires: Date.now() - 1000,
      },
      account: null,
    } as never)

    expect((token as { error?: string }).error).toBe('RefreshAccessTokenError')
  })

  it('session callback hides a stale access token and forwards the error', async () => {
    const session = await config.callbacks!.session!({
      session: { user: {}, expires: '2026-01-01' },
      token: {
        accessToken: 'stale-access-token',
        error: 'RefreshAccessTokenError',
      },
    } as never)

    expect((session as { accessToken?: string }).accessToken).toBeUndefined()
    expect((session as { error?: string }).error).toBe('RefreshAccessTokenError')
  })
})
