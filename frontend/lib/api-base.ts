/**
 * The one place the backend's base URL is resolved and normalized.
 *
 * Both `api.ts` (customer) and `admin-api.ts` (admin) build request URLs as
 * `${BASE_URL}${path}`, and every caller's `path` starts with its own leading
 * slash. So a base URL that ENDS in a slash produces `//inventory/search`,
 * which is a genuinely different route to FastAPI's router, not a cosmetic
 * difference — it 404s before authentication is even reached.
 *
 * This is not hypothetical. It took the entire production site down on
 * 2026-08-26 (customer inventory search, chat, and every admin tab at once),
 * because `NEXT_PUBLIC_API_URL` is a Lambda Function URL and AWS always
 * renders those with a trailing slash. Measured live against the deployed
 * backend:
 *
 *     /health   -> 200 {"status":"ok"}      //health   -> 404 {"detail":"Not Found"}
 *
 * `infra/bin/infra.ts` also strips the slash on the way in, but that is a
 * second layer rather than the primary defense: an infra-side fix only holds
 * for values this repo's own CDK supplies, while this one holds for anything
 * that ever sets the variable — a `.env.local`, `docker-compose.yml`, a
 * hand-run `next build`, or a future deploy path nobody has written yet.
 */

/** The local backend used when `NEXT_PUBLIC_API_URL` is unset (dev, tests). */
export const DEFAULT_BASE_URL = 'http://localhost:8000'

/**
 * Resolve a backend base URL that is always safe to concatenate a
 * slash-prefixed path onto. Never returns a value ending in a slash.
 */
export function normalizeBaseUrl(raw: string | undefined): string {
  const candidate = (raw ?? '').trim()
  // Strip EVERY trailing slash, not just one: `.replace(/\/$/, '')` leaves
  // `https://host//` as `https://host/`, which reintroduces the exact bug
  // this function exists to remove.
  const trimmed = candidate.replace(/\/+$/, '')
  return trimmed === '' ? DEFAULT_BASE_URL : trimmed
}

/**
 * Is this base URL something a request could actually succeed against?
 *
 * The case that matters is a **build-time placeholder**. cdk-nextjs-standalone
 * compiles the bundle with every `NEXT_PUBLIC_*` token replaced by a literal
 * `{{ KEY }}` marker (`NextjsBuild.getBuildEnvVars`), then substitutes the real
 * value into the built files at DEPLOY time. So during `next build`,
 * `NEXT_PUBLIC_API_URL` is the string `"{{ NEXT_PUBLIC_API_URL }}"`.
 *
 * Handing that to Next's fetch is what caused this project's long-standing
 * "known, unresolved" build flakiness. Raw `fetch` rejects such a URL in ~23ms,
 * but `lib/public.ts` fetches with `next: { revalidate: 300 }`, and inside
 * Next's ISR fetch wrapper that rejection becomes a HANG — static generation
 * then burns the whole `staticPageGenerationTimeout` three times and fails the
 * build on whichever public page reached it first. (Measured 2026-08-26: `/`
 * on one run, `/shows` on the next — the "different page each time" signature
 * `infra/lib/frontend-stack.ts` records as a suspected Windows proxy/DNS/socket
 * problem. It is not that; it reproduces on Linux, on a DIRECT build, and it
 * disappears the moment the variable holds a real origin.)
 *
 * The page-level `try/catch` fallbacks never rescued it because **a hang is not
 * an error**. Rejecting before a request exists is what lets them work.
 */
export function isUsableBaseUrl(raw: string | undefined): boolean {
  if (!raw) return false
  let parsed: URL
  try {
    parsed = new URL(raw)
  } catch {
    return false
  }
  return parsed.protocol === 'http:' || parsed.protocol === 'https:'
}

/** The resolved backend origin, read once at module load. */
export const API_BASE_URL = normalizeBaseUrl(process.env.NEXT_PUBLIC_API_URL)

/**
 * True when `API_BASE_URL` is a real origin. False during `next build`, where
 * every request must fail fast into its caller's fallback instead of hanging.
 */
export const API_BASE_URL_IS_USABLE = isUsableBaseUrl(API_BASE_URL)
