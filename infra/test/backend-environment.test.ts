import { describe, expect, it } from 'vitest'
import { buildBackendEnvironment } from '../lib/backend-environment'

const baseProps = {
  dynamoTableName: 'test-cards',
  rateLimitTableName: 'test-rate-limits',
  cognitoUserPoolId: 'us-east-1_TESTPOOL',
  cognitoClientId: 'test-client-id',
  corsOrigins: 'https://example.test,http://localhost:3000',
}

describe('buildBackendEnvironment', () => {
  it('never sets AWS_REGION (Lambda-reserved; CloudFormation rejects it)', () => {
    const env = buildBackendEnvironment(baseProps)
    expect(env.AWS_REGION).toBeUndefined()
  })

  it('sets FORWARDED_ALLOW_IPS to loopback, not the ECS ALB private-range value', () => {
    const env = buildBackendEnvironment(baseProps)
    expect(env.FORWARDED_ALLOW_IPS).toBe('127.0.0.1/32')
  })

  it('sets the LWA port and buffered invoke mode', () => {
    const env = buildBackendEnvironment(baseProps)
    expect(env.AWS_LWA_PORT).toBe('8000')
    expect(env.AWS_LWA_INVOKE_MODE).toBe('BUFFERED')
  })

  it('omits secret keys entirely when not supplied, rather than writing an empty string', () => {
    const env = buildBackendEnvironment(baseProps)
    expect('POKEMONPRICETRACKER_API_KEY' in env).toBe(false)
    expect('ADMIN_API_KEY' in env).toBe(false)
  })

  it('includes secret keys when supplied', () => {
    const env = buildBackendEnvironment({
      ...baseProps,
      pokemonPriceTrackerApiKey: 'fake-ppt-key',
      adminApiKey: 'fake-admin-key',
    })
    expect(env.POKEMONPRICETRACKER_API_KEY).toBe('fake-ppt-key')
    expect(env.ADMIN_API_KEY).toBe('fake-admin-key')
  })

  it('carries the non-secret values through unchanged', () => {
    const env = buildBackendEnvironment(baseProps)
    expect(env.DYNAMODB_TABLE_NAME).toBe('test-cards')
    expect(env.RATE_LIMIT_TABLE_NAME).toBe('test-rate-limits')
    expect(env.COGNITO_USER_POOL_ID).toBe('us-east-1_TESTPOOL')
    expect(env.COGNITO_CLIENT_ID).toBe('test-client-id')
    expect(env.CORS_ORIGINS).toBe('https://example.test,http://localhost:3000')
  })
})
