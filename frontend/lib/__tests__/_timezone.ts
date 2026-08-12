/**
 * Test-only timezone pin. NOT a test file (no `.test.` in the name, so vitest's
 * `include` glob skips it) and NOT typechecked by `next build` (tsconfig
 * excludes `**\/__tests__/**`).
 *
 * WHY THIS EXISTS — read before deleting it. Every date bug RFC 0010 T8 fixes is
 * invisible at UTC: `new Date("2026-08-10")` is UTC midnight, which renders as
 * Aug 10 in UTC and Aug 9 only at a NEGATIVE offset. A CI box running at UTC
 * goes green while the bug is live in Portland. **A date test that does not pin
 * a negative-offset zone is theatre.**
 *
 * Node re-reads `process.env.TZ` on assignment (verified on this machine:
 * setting it flips `getTimezoneOffset()` and
 * `Intl.DateTimeFormat().resolvedOptions().timeZone` immediately), so this works
 * at runtime rather than needing a per-file env config vitest does not have.
 *
 * Always call the returned restore function in an `afterAll`/`afterEach` —
 * vitest reuses a worker across files and a leaked TZ would silently retune
 * somebody else's clock.
 */

/** The negative-offset zone the business actually operates in. */
export const PACIFIC = 'America/Los_Angeles'

/** Pin `process.env.TZ`; returns the restore function. */
export function pinTimeZone(tz: string): () => void {
  const previous = process.env.TZ
  process.env.TZ = tz
  return () => {
    if (previous === undefined) delete process.env.TZ
    else process.env.TZ = previous
  }
}
