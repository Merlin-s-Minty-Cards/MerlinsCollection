/**
 * Pure logic — no DOM.
 *
 * @vitest-environment node
 */
import { describe, it, expect } from 'vitest'

import { normalizeBaseUrl, isUsableBaseUrl } from '@/lib/api-base'

describe('normalizeBaseUrl', () => {
  // The production regression this exists to prevent, 2026-08-26: every
  // frontend call to the backend returned 404 because the deployed
  // NEXT_PUBLIC_API_URL carried a trailing slash and both api.ts and
  // admin-api.ts build request URLs as `${BASE_URL}${path}` where every
  // caller's `path` already starts with `/`. The resulting `//inventory/
  // search` is a genuinely different path to FastAPI's router — measured
  // live against the deployed Lambda Function URL: `/health` -> 200,
  // `//health` -> 404.
  it('strips the trailing slash a Lambda Function URL always carries', () => {
    expect(normalizeBaseUrl('https://abc123.lambda-url.us-east-1.on.aws/')).toBe(
      'https://abc123.lambda-url.us-east-1.on.aws',
    )
  })

  it('strips repeated trailing slashes', () => {
    expect(normalizeBaseUrl('https://api.example.test///')).toBe('https://api.example.test')
  })

  it('leaves an already-clean URL untouched', () => {
    expect(normalizeBaseUrl('https://api.example.test')).toBe('https://api.example.test')
  })

  it('preserves a path prefix while still dropping the trailing slash', () => {
    expect(normalizeBaseUrl('https://api.example.test/v1/')).toBe('https://api.example.test/v1')
  })

  it('falls back to the local dev backend when the variable is unset', () => {
    expect(normalizeBaseUrl(undefined)).toBe('http://localhost:8000')
    expect(normalizeBaseUrl('')).toBe('http://localhost:8000')
  })

  it('never returns a value ending in a slash, for any input', () => {
    for (const raw of ['https://x.test/', 'https://x.test', '/', '//', undefined, '']) {
      expect(normalizeBaseUrl(raw).endsWith('/')).toBe(false)
    }
  })
})

describe('normalizeBaseUrl — build-time placeholders', () => {
  // cdk-nextjs-standalone builds the bundle with NEXT_PUBLIC_* set to
  // `{{ KEY }}` placeholders (NextjsBuild.getBuildEnvVars), substituting the
  // real value into the built files at DEPLOY time. During `next build` the
  // value is therefore literally "{{ NEXT_PUBLIC_API_URL }}" — an unusable
  // base URL that no request can ever succeed against.
  it('reports a build-time placeholder as unusable', () => {
    expect(isUsableBaseUrl('{{ NEXT_PUBLIC_API_URL }}')).toBe(false)
  })

  it('reports real origins as usable', () => {
    expect(isUsableBaseUrl('https://abc.lambda-url.us-east-1.on.aws')).toBe(true)
    expect(isUsableBaseUrl('http://localhost:8000')).toBe(true)
  })

  it('reports anything that is not an absolute http(s) origin as unusable', () => {
    for (const bad of ['', 'not a url', '/relative/path', 'ftp://example.test']) {
      expect(isUsableBaseUrl(bad)).toBe(false)
    }
  })
})
