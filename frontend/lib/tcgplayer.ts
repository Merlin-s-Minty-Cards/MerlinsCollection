import { safeHref } from './safe-href'

/**
 * The ONE place a TCGplayer URL is built (RFC 0023 §3).
 *
 * TCGplayer has exactly TWO Pokémon categories, verified 2026-09-02 against
 * TCGplayer's own category registry (`tcgcsv.com/tcgplayer/categories`):
 * `pokemon` (id 3, English) and `pokemon-japan` (id 85). There is no Korean,
 * Chinese, French, German, Spanish, Italian or Portuguese Pokémon category —
 * TCGplayer launched Japanese Pokémon as a dedicated category in Oct 2024 and
 * has added no others since.
 *
 * Returns `null` for every other language, including `OTHER`. A `null` is
 * NOT a bug and must never be papered over with the English link: an
 * English-category search for a Korean card returns the wrong card or
 * nothing, and both are worse than no link at all. Callers must show
 * `TCGPLAYER_UNSUPPORTED_LANGUAGE_MESSAGE` instead of silently omitting the
 * control — see CLAUDE.md's "an escape hatch/disabled control states why"
 * rule.
 *
 * Stored language codes are always upper-case (`Language` is a Python
 * `StrEnum` with values like `"EN"`/`"JP"`/`"KO"`), so the comparison below
 * is a plain, case-sensitive string match — not a normalization.
 *
 * Takes `language: string | null | undefined` rather than a `Language` type:
 * this repo has no frontend `Language` type yet (RFC 0023 T3 is what adds
 * `LANGUAGE_OPTIONS` to `lib/constants.ts`), and every current caller's item
 * type already carries `language` as a plain optional string.
 */
export function tcgplayerSearchUrl(
  language: string | null | undefined,
  query: string
): string | null {
  const q = encodeURIComponent(query)
  if (language === 'EN') {
    return `https://www.tcgplayer.com/search/pokemon/product?q=${q}&view=grid`
  }
  if (language === 'JP') {
    return `https://www.tcgplayer.com/search/pokemon-japan/product?productLineName=pokemon-japan&q=${q}&view=grid`
  }
  return null
}

/**
 * The one-line reason to show beside a still-editable manual `tcg_url`
 * field when `tcgplayerSearchUrl` returns `null`. Deliberately generic
 * (does not name the specific language) rather than duplicating a partial
 * copy of `LANGUAGE_LABELS` here — that mirror belongs to RFC 0023 T3.
 */
export const TCGPLAYER_UNSUPPORTED_LANGUAGE_MESSAGE =
  'TCGplayer only has English and Japanese Pokémon categories — paste a link if you have one.'

/**
 * The safe form of a stored `tcg_url` to use as an `<a href>`, or `null` if
 * it isn't one.
 *
 * `tcg_url` is admin-typed free text, not a value this codebase generates —
 * `admin-inventory-columns.tsx`'s own comment on this same field already
 * documents it as a stored-XSS sink: a `javascript:` value in an href fires
 * on one click. Delegates to {@link safeHref} — the same URL-vetting
 * discipline already used for Sanity-authored article links, which parses
 * with the real `URL` constructor rather than a regex and so also catches
 * whitespace/case tricks a naive `^https?:\/\//` check would miss — instead
 * of a second, narrower reimplementation of "is this href safe". Narrowed
 * further to http(s) only: `safeHref` also allows `mailto:`/`tel:`, neither
 * of which is a TCGplayer link.
 */
export function safeTcgHref(url: unknown): string | null {
  if (typeof url !== 'string') return null
  const vetted = safeHref(url)
  return vetted && /^https?:/i.test(vetted) ? vetted : null
}
