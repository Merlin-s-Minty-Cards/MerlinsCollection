/**
 * Client-side sort helper for admin tables whose list endpoint returns its
 * FULL result set with no `limit`/pagination — `/vault`, `/show-prep/mispriced`
 * and `/watchlist` are the three today. On a page like Inventory or Prep Queue
 * a `limit` truncates the response BEFORE any sort could see the rest of the
 * rows, which is why those pages must sort on the server. None of these three
 * truncate at all, so sorting the already-complete response client-side
 * produces an IDENTICAL result to sorting it server-side, for zero round trip.
 *
 * Mirrors the shape of the backend's `services/table_sort.py::SortRegistry` —
 * same **missing sorts LAST in both directions** invariant (a partition, not a
 * sentinel: `reverse` would flip a sentinel too, which is what used to bunch
 * blanks at whichever end nobody was looking at), and the same "an unknown key
 * is a no-op, not a crash" behavior, so a page's `handleSort` never needs a
 * try/catch just because a column's key does not have an extractor yet.
 *
 * Field-specific ranking (e.g. Vault's condition-tier order) stays in that
 * page's own extractor map rather than living here — this module only owns
 * the missing-last / present/missing partition, not any table's domain rules.
 */

export type FieldExtractor<T> = (row: T) => number | string | null

export function sortRows<T>(
  rows: T[],
  fields: Record<string, FieldExtractor<T>>,
  key: string | null,
  dir: 'asc' | 'desc',
): T[] {
  if (!key) return rows
  const extract = fields[key]
  // An unknown key is a no-op here — same "does not crash" contract as the
  // backend registry's `resolve_sort_field` returning `None`. The column
  // picker is what keeps `key` in sync with `fields`; this is belt-and-braces.
  if (!extract) return rows

  const sign = dir === 'asc' ? 1 : -1
  const present = rows.filter((r) => extract(r) !== null)
  const missing = rows.filter((r) => extract(r) === null)

  present.sort((a, b) => {
    const av = extract(a)
    const bv = extract(b)
    if (typeof av === 'number' && typeof bv === 'number') {
      return sign * (av - bv)
    }
    return sign * String(av ?? '').localeCompare(String(bv ?? ''))
  })

  return [...present, ...missing]
}
