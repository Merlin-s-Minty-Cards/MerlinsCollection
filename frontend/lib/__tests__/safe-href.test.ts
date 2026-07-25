import { describe, it, expect } from 'vitest'
import { safeHref } from '@/lib/safe-href'

describe('safeHref', () => {
  it('allows the link schemes an editor legitimately needs', () => {
    expect(safeHref('https://pokemontcg.io')).toBe('https://pokemontcg.io')
    expect(safeHref('http://example.com')).toBe('http://example.com')
    expect(safeHref('mailto:merlinsmintycardsllc@gmail.com')).toBe(
      'mailto:merlinsmintycardsllc@gmail.com',
    )
    expect(safeHref('tel:+15551234567')).toBe('tel:+15551234567')
  })

  it('allows same-site relative links', () => {
    expect(safeHref('/shows')).toBe('/shows')
  })

  it('allows in-page anchors and query strings', () => {
    // A table-of-contents link is the most common thing an article author writes.
    expect(safeHref('#the-grading-scale')).toBe('#the-grading-scale')
    expect(safeHref('?tab=psa')).toBe('?tab=psa')
  })

  it('rejects protocol-relative URLs that only look like same-site paths', () => {
    // `//evil.com` starts with "/" but is authority-relative: a browser resolves
    // it to https://evil.com. Treating it as a same-site path is how allowlists
    // like this one get bypassed.
    expect(safeHref('//evil.com')).toBeUndefined()
    expect(safeHref('///evil.com')).toBeUndefined()
    expect(safeHref('/\\evil.com')).toBeUndefined()
  })

  it('rejects javascript: URIs', () => {
    // Hrefs come from the CMS. React does not reliably strip these, so a
    // compromised editor account or leaked write token becomes stored XSS.
    expect(safeHref('javascript:alert(1)')).toBeUndefined()
  })

  it('rejects javascript: URIs disguised with casing and whitespace', () => {
    expect(safeHref('  JaVaScRiPt:alert(1)')).toBeUndefined()
    expect(safeHref('java\tscript:alert(1)')).toBeUndefined()
  })

  it('rejects data: URIs', () => {
    expect(safeHref('data:text/html,<script>alert(1)</script>')).toBeUndefined()
  })

  it('returns undefined for a missing or empty href', () => {
    expect(safeHref(undefined)).toBeUndefined()
    expect(safeHref('')).toBeUndefined()
  })
})
