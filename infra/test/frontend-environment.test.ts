import { describe, expect, it } from 'vitest'
import { buildFrontendEnvironment } from '../lib/frontend-environment'

const baseProps = {
  backendApiUrl: 'https://backend.example.test',
  cognitoClientId: 'test-client-id',
  cognitoIssuer: 'https://cognito-idp.us-east-1.amazonaws.com/us-east-1_TESTPOOL',
  cognitoDomain: 'https://test-pool.auth.us-east-1.amazoncognito.com',
}

describe('buildFrontendEnvironment', () => {
  it('never sets AUTH_URL — auth.config.ts trusts the request Host instead', () => {
    const env = buildFrontendEnvironment(baseProps)
    expect(env.AUTH_URL).toBeUndefined()
  })

  it('omits secret keys entirely when not supplied, rather than writing an empty string', () => {
    const env = buildFrontendEnvironment(baseProps)
    expect('AUTH_SECRET' in env).toBe(false)
    expect('AWS_COGNITO_CLIENT_SECRET' in env).toBe(false)
  })

  it('includes secret keys when supplied', () => {
    const env = buildFrontendEnvironment({
      ...baseProps,
      authSecret: 'fake-auth-secret',
      cognitoClientSecret: 'fake-cognito-secret',
    })
    expect(env.AUTH_SECRET).toBe('fake-auth-secret')
    expect(env.AWS_COGNITO_CLIENT_SECRET).toBe('fake-cognito-secret')
  })

  it('carries the non-secret values through unchanged', () => {
    const env = buildFrontendEnvironment(baseProps)
    expect(env.NEXT_PUBLIC_API_URL).toBe('https://backend.example.test')
    expect(env.AWS_COGNITO_CLIENT_ID).toBe('test-client-id')
    expect(env.AWS_COGNITO_ISSUER).toBe(
      'https://cognito-idp.us-east-1.amazonaws.com/us-east-1_TESTPOOL',
    )
    expect(env.AWS_COGNITO_DOMAIN).toBe('https://test-pool.auth.us-east-1.amazoncognito.com')
  })

  it('sets the admin group to "admin", matching the real Cognito group name and the ECS task def', () => {
    const env = buildFrontendEnvironment(baseProps)
    expect(env.COGNITO_ADMIN_GROUP).toBe('admin')
  })
})
