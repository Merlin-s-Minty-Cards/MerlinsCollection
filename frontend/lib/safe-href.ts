/** Schemes an editor may legitimately link to. Everything else is dropped. */
const ALLOWED_SCHEMES = ['http:', 'https:', 'mailto:', 'tel:']

/** Never resolvable as a real origin, so anything that lands here was relative. */
const RELATIVE_BASE = 'https://relative.invalid'

/**
 * Vet a link URL that came from the CMS before rendering it as an `href`.
 *
 * Article links and CTAs are authored in Sanity, so their hrefs are untrusted
 * input: a compromised editor account or a leaked write token could store a
 * `javascript:` URI (stored XSS) or a `//evil.com` (off-site navigation dressed
 * up as an internal link). Returns `undefined` for anything not on the allowlist
 * so callers can render the text without a link.
 *
 * Resolving against a base is what makes this safe. A leading-slash check is not:
 * `//evil.com` and `/\evil.com` both start with `/` yet browsers resolve them to
 * another origin entirely.
 */
export function safeHref(href: string | undefined | null): string | undefined {
  if (!href) return undefined
  const trimmed = href.trim()
  if (!trimmed) return undefined

  try {
    const url = new URL(trimmed, RELATIVE_BASE)
    const hasScheme = /^[a-z][a-z0-9+.-]*:/i.test(trimmed)

    if (!hasScheme) {
      // Scheme-less, so it should be same-site — but `//evil.com` and `/\evil.com`
      // are authority-relative and resolve to someone else's origin. Anything that
      // escaped our placeholder base is off-site pretending to be a local path.
      return url.origin === RELATIVE_BASE ? trimmed : undefined
    }

    // The URL parser has already normalised the casing and embedded whitespace
    // used to smuggle `javascript:` past a naive string comparison.
    return ALLOWED_SCHEMES.includes(url.protocol) ? trimmed : undefined
  } catch {
    return undefined
  }
}
