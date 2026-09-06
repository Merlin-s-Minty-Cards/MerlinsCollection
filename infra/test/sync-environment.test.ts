import { describe, expect, it } from 'vitest'
import { buildSyncEnvironment } from '../lib/sync-environment'

const baseProps = { dynamoTableName: 'test-cards', awsRegion: 'us-east-1' }

describe('buildSyncEnvironment', () => {
  it('sets AWS_REGION explicitly -- this is ECS, not Lambda, so nothing reserves it', () => {
    const env = buildSyncEnvironment(baseProps)
    expect(env.AWS_REGION).toBe('us-east-1')
  })

  it('carries the table name through unchanged', () => {
    const env = buildSyncEnvironment(baseProps)
    expect(env.DYNAMODB_TABLE_NAME).toBe('test-cards')
  })

  it('omits the pricing key and quota entirely when not supplied, rather than an empty string', () => {
    const env = buildSyncEnvironment(baseProps)
    expect('POKEMONPRICETRACKER_API_KEY' in env).toBe(false)
    expect('PRICING_DAILY_QUOTA' in env).toBe(false)
  })

  it('includes the pricing key and quota when supplied', () => {
    const env = buildSyncEnvironment({
      ...baseProps,
      pokemonPriceTrackerApiKey: 'fake-ppt-key',
      pricingDailyQuota: '100',
    })
    expect(env.POKEMONPRICETRACKER_API_KEY).toBe('fake-ppt-key')
    expect(env.PRICING_DAILY_QUOTA).toBe('100')
  })
})
