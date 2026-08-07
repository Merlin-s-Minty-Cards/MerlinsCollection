/**
 * Turns an unknown thrown value into something honest to show an admin.
 *
 * The bug this exists for: every catalog-search surface hard-coded the banner
 * "Catalog search failed — a connection problem, not an empty catalog." for
 * ANY rejection. On the live site the request was arriving fine and coming
 * back HTTP 500 (the ECS task role had no `dynamodb:Scan`), so the only
 * message on screen asserted the one cause that had already been ruled out.
 * A message that names a cause it cannot know is worse than a vague one — it
 * aims the next hour of debugging at the wrong layer.
 *
 * So: report only what the failure actually tells us. `fetch` rejects with a
 * TypeError when the server is unreachable and there is no status; anything
 * with a numeric `status` got a real HTTP response and is not a connection
 * problem. Never inline this reasoning in a component — call the helper.
 */

/** What kind of failure this was — for choosing an icon/severity, not copy. */
export type ApiErrorKind =
  | 'unreachable'
  | 'auth'
  | 'rate-limit'
  | 'request'
  | 'server'
  | 'unknown'

export interface ApiErrorDescription {
  kind: ApiErrorKind
  /** One sentence, safe to render directly. */
  message: string
  /** Whether repeating the same request could plausibly succeed. */
  retryable: boolean
}

/**
 * Duck-typed on `status` rather than `instanceof AdminApiError`: the check has
 * to survive an error crossing a bundle/realm boundary, where `instanceof`
 * quietly returns false and would misreport a 500 as a network outage.
 */
function statusOf(err: unknown): number | undefined {
  if (typeof err !== 'object' || err === null) return undefined
  const status = (err as { status?: unknown }).status
  return typeof status === 'number' ? status : undefined
}

function detailOf(err: unknown): string | undefined {
  if (typeof err !== 'object' || err === null) return undefined
  const detail = (err as { detail?: unknown }).detail
  return typeof detail === 'string' && detail.trim() ? detail.trim() : undefined
}

export function describeApiError(err: unknown): ApiErrorDescription {
  const status = statusOf(err)

  // No status: the request never completed. This is the ONLY case that is
  // genuinely a connection problem.
  if (status === undefined) {
    if (err instanceof TypeError) {
      return {
        kind: 'unreachable',
        message: 'The server could not be reached. Check your connection and try again.',
        retryable: true,
      }
    }
    return {
      kind: 'unknown',
      message: 'That request failed for an unknown reason.',
      retryable: true,
    }
  }

  if (status === 401 || status === 403) {
    return {
      kind: 'auth',
      message:
        status === 401
          ? 'Your session has expired — sign in again.'
          : 'Your account does not have permission to do that.',
      retryable: false,
    }
  }

  if (status === 429) {
    return {
      kind: 'rate-limit',
      message: 'Too many requests — wait a moment before trying again.',
      retryable: false,
    }
  }

  if (status >= 500) {
    const detail = detailOf(err)
    return {
      kind: 'server',
      // The status code is in the copy on purpose: it is the single most
      // useful thing to quote when reporting the fault, and its presence is
      // itself the proof the request arrived — so the copy does not need to
      // (and must not) speculate about the network.
      message: `The server hit an error (${status})${detail ? `: ${detail}` : ''}. Retrying may work; if it keeps failing the backend needs a look.`,
      retryable: true,
    }
  }

  // 4xx — the backend rejected the request specifically, so say what it said.
  return {
    kind: 'request',
    message: detailOf(err) ?? `That request was rejected (${status}).`,
    retryable: false,
  }
}
