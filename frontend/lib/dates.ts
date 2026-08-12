/**
 * Dates that say what the operator's calendar says.
 * docs/plans/rfc-0010/t8-local-date-formatting.md
 *
 * Two live bugs, one root cause — a date pushed through a UTC boundary:
 *
 * 1. **Display was a day early.** `new Date("2026-08-10")` is required by
 *    ECMA-262 to parse as UTC midnight, and `toLocaleDateString` then renders it
 *    in the browser's zone. At any negative offset — every US timezone — that is
 *    the evening of Aug 9. The owner reported it on Show Analytics, and noted
 *    the date picker beside it was right: the picker binds the ISO string and
 *    never builds a `Date`.
 * 2. **"Today" was tomorrow after 5pm Pacific.** `new Date().toISOString()
 *    .split('T')[0]` is the UTC date. Measured: 6:30pm Pacific on Aug 10 yields
 *    `2026-08-11`, so a buy typed at an evening card show landed in the wrong
 *    day's analytics and potentially against the wrong show.
 *
 * **Local zone first, Pacific only as a fallback** (owner: *"use the local time
 * if possible, but otherwise default to PST time as that is where we are all
 * located"*). And the two halves barely interact: a DATE-ONLY value carries no
 * timezone at all, so once it stops going through `new Date()` it reads as the
 * same day everywhere on earth. The fallback matters only for real instants and
 * for "what is today".
 */

/**
 * The zone this business operates in. Used ONLY when the runtime has none
 * (SSR, an old engine, a test with no ICU data).
 *
 * IANA, never a fixed offset: Pacific is PDT (−7) in August and PST (−8) in
 * January, so a hardcoded −08:00 is wrong from March to November — about eight
 * months a year, every summer show included.
 */
export const BUSINESS_TIME_ZONE = 'America/Los_Angeles'

/** `YYYY-MM-DD` and nothing else. A timestamp is a different kind of value. */
const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/

const DEFAULT_DATE_OPTIONS: Intl.DateTimeFormatOptions = {
  month: 'short',
  day: 'numeric',
  year: 'numeric',
}

const DEFAULT_TIMESTAMP_OPTIONS: Intl.DateTimeFormatOptions = {
  month: 'short',
  day: 'numeric',
  year: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
}

/**
 * The zone the runtime knows it is in, or `undefined` when it does not know.
 *
 * `undefined` is the signal to fall back to {@link BUSINESS_TIME_ZONE}; passing
 * `timeZone: undefined` to `Intl` means "use local", which is the behaviour the
 * owner asked for first. Never force Pacific on a browser that knows its own
 * zone.
 */
function runtimeTimeZone(): string | undefined {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || undefined
  } catch {
    return undefined
  }
}

/** The zone to format an instant in: local when known, Pacific when not. */
function displayTimeZone(): string | undefined {
  return runtimeTimeZone() ?? BUSINESS_TIME_ZONE
}

/**
 * Local-midnight `Date` for a date-only string, or `null` if it is not one.
 *
 * Built from the parts (`new Date(y, m - 1, d)`) rather than parsed, which is
 * the entire fix: parsing gives UTC midnight, constructing gives local midnight.
 * A value that rolls over (`2026-02-31`) is rejected rather than silently
 * becoming March.
 */
export function parseISODateLocal(iso: string): Date | null {
  if (typeof iso !== 'string') return null
  const match = DATE_ONLY.exec(iso)
  if (!match) return null
  const year = Number(match[1])
  const month = Number(match[2])
  const day = Number(match[3])
  const date = new Date(year, month - 1, day)
  if (
    date.getFullYear() !== year ||
    date.getMonth() !== month - 1 ||
    date.getDate() !== day
  ) {
    return null
  }
  return date
}

/**
 * Format a value the API sent as a calendar date.
 *
 * Three documented cases, because these functions receive whatever the backend
 * put on the wire and rendering `Invalid Date` at a buy table is worse than
 * rendering the raw string:
 *
 * - **date-only** (`"2026-08-10"`, what `date.isoformat()` sends, and what
 *   `Transaction.date` / `Show.date` / `acquired_at` all are) — split into parts
 *   and formatted at local midnight. No zone is involved. **NEVER pass a
 *   date-only string to `new Date()`.**
 * - **a full timestamp** (`"2026-08-10T22:00:00Z"`) — a real instant, so it is
 *   delegated to normal `Date` parsing and rendered as the calendar date it
 *   falls on in the viewer's zone. That is the honest reading: 22:00Z is still
 *   Aug 10 in Pacific, and 02:00Z would genuinely be the previous day.
 * - **anything else** (junk, empty) — returned unchanged.
 */
export function formatISODate(
  iso: string | null | undefined,
  opts: Intl.DateTimeFormatOptions = DEFAULT_DATE_OPTIONS,
): string {
  if (typeof iso !== 'string' || iso === '') return ''
  const dateOnly = parseISODateLocal(iso)
  if (dateOnly) return dateOnly.toLocaleDateString('en-US', opts)

  const instant = new Date(iso)
  if (Number.isNaN(instant.getTime())) return iso
  return instant.toLocaleDateString('en-US', { ...opts, timeZone: displayTimeZone() })
}

/**
 * A `Date` as `YYYY-MM-DD` in a given zone, assembled from parts.
 *
 * `formatToParts` rather than `en-CA`, so the output does not depend on which
 * locale patterns the runtime's ICU build shipped with. No offset arithmetic —
 * that is what a DST-aware zone database is for.
 */
function isoDateInZone(date: Date, timeZone: string | undefined): string {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(date)
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((p) => p.type === type)?.value ?? ''
  return `${part('year')}-${part('month')}-${part('day')}`
}

/** A `Date` as `YYYY-MM-DD` in the viewer's zone (Pacific if it has none). */
export function toLocalISODate(date: Date): string {
  return isoDateInZone(date, displayTimeZone())
}

/**
 * Today's date as `YYYY-MM-DD` in the USER's zone, falling back to Pacific.
 *
 * **NOT `new Date().toISOString().split('T')[0]`**, which is the UTC date:
 * measured, 6:30pm Pacific on Aug 10 yields `"2026-08-11"`, so every
 * transaction entered after 5pm Pacific defaulted to tomorrow. For a business
 * that sells at evening card shows that is most of them.
 */
export function todayLocal(): string {
  return toLocalISODate(new Date())
}

/**
 * Format a real instant (`voided_at`, a slab's `updated_at`) in the viewer's
 * zone, falling back to Pacific when the runtime has none.
 *
 * Unlike a date-only value this genuinely does render differently per zone, and
 * that is correct — it names a moment, not a square on a calendar. Junk is
 * returned unchanged rather than rendered as `Invalid Date`.
 */
export function formatTimestamp(
  iso: string | null | undefined,
  opts: Intl.DateTimeFormatOptions = DEFAULT_TIMESTAMP_OPTIONS,
): string {
  if (typeof iso !== 'string' || iso === '') return ''
  const instant = new Date(iso)
  if (Number.isNaN(instant.getTime())) return iso
  return instant.toLocaleString('en-US', { ...opts, timeZone: displayTimeZone() })
}
