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
import { describeApiError } from '../admin-error'
import { AdminApiError } from '../admin-api'

// The bug this exists for: the catalog-search banner hard-coded "a connection
// problem, not an empty catalog" for EVERY failure. The live site was actually
// returning HTTP 500 (the ECS task role was missing dynamodb:Scan), so the one
// message on screen asserted the one cause that had been ruled out, and sent
// the investigation at the network instead of at the server.
describe('describeApiError', () => {
  it('calls a genuine network failure a connection problem', () => {
    // A rejected fetch is a TypeError, not an AdminApiError — no status exists.
    const d = describeApiError(new TypeError('Failed to fetch'))
    expect(d.kind).toBe('unreachable')
    expect(d.message).toMatch(/could not be reached/i)
  })

  it('reports a 500 as a server error and does NOT blame the connection', () => {
    const d = describeApiError(new AdminApiError(500, 'Internal Server Error'))
    expect(d.kind).toBe('server')
    expect(d.message).toMatch(/server error/i)
    expect(d.message).not.toMatch(/connection/i)
  })

  it('surfaces the status code so a report names the real failure', () => {
    expect(describeApiError(new AdminApiError(503)).message).toContain('503')
  })

  it('treats an expired session as auth, not as an outage', () => {
    for (const status of [401, 403]) {
      const d = describeApiError(new AdminApiError(status))
      expect(d.kind).toBe('auth')
      expect(d.message).toMatch(/sign|session|permission/i)
    }
  })

  it('reports a rate limit distinctly so retrying looks pointless, not broken', () => {
    const d = describeApiError(new AdminApiError(429))
    expect(d.kind).toBe('rate-limit')
    expect(d.message).toMatch(/too many|slow down|rate/i)
  })

  it('passes a 4xx detail through — the backend said something specific', () => {
    const d = describeApiError(new AdminApiError(422, 'name must be 3+ characters'))
    expect(d.kind).toBe('request')
    expect(d.message).toContain('name must be 3+ characters')
  })

  it('never claims a cause it cannot know for an unrecognised throw', () => {
    const d = describeApiError('something odd')
    expect(d.kind).toBe('unknown')
    expect(d.message).not.toMatch(/connection|server error/i)
  })

  it('marks which failures are worth a retry button', () => {
    // Retrying a 422 just repeats the same rejection; retrying a 500 or a
    // dropped connection is the reasonable next move.
    expect(describeApiError(new TypeError('Failed to fetch')).retryable).toBe(true)
    expect(describeApiError(new AdminApiError(500)).retryable).toBe(true)
    expect(describeApiError(new AdminApiError(503)).retryable).toBe(true)
    expect(describeApiError(new AdminApiError(422, 'bad')).retryable).toBe(false)
    expect(describeApiError(new AdminApiError(401)).retryable).toBe(false)
  })
})
