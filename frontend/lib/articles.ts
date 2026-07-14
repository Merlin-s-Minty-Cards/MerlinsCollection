// Article content layer — backed by the Sanity CMS. The business authors
// articles at /studio; these functions read what they publish.

import type { PortableTextBlock } from '@portabletext/types'
import { sanityClient } from '@/lib/sanity'

export interface Article {
  slug: string
  title: string
  excerpt: string
  /** Date-only (`YYYY-MM-DD`), narrowed from Sanity's `publishedAt` datetime. */
  date: string
  readingTime: string
  category: string
  body: PortableTextBlock[]
}

/** An article as the GROQ projection below returns it. */
type SanityArticle = Omit<Article, 'date'> & { publishedAt: string }

// Only articles with a slug are reachable, so unslugged drafts are skipped.
// Newest first, matching how the listing page reads.
const ARTICLE_FIELDS = `
  "slug": slug.current,
  title,
  excerpt,
  publishedAt,
  readingTime,
  category,
  body
`

const ALL_ARTICLES_QUERY = `*[_type == "article" && defined(slug.current)]
  | order(publishedAt desc) { ${ARTICLE_FIELDS} }`

// $slug is a query *parameter*, not string interpolation — the slug comes from
// the URL, and interpolating it straight into GROQ would be an injection hole.
const ARTICLE_BY_SLUG_QUERY = `*[_type == "article" && slug.current == $slug][0] { ${ARTICLE_FIELDS} }`

/**
 * Sanity stores `publishedAt` as a full datetime, but the pages only ever show a
 * calendar date. Truncating to `YYYY-MM-DD` here is what keeps `formatArticleDate`
 * timezone-safe downstream (see its comment).
 */
function toArticle({ publishedAt, ...rest }: SanityArticle): Article {
  return { ...rest, date: (publishedAt ?? '').slice(0, 10) }
}

export async function getAllArticles(): Promise<Article[]> {
  const results = await sanityClient.fetch<SanityArticle[]>(ALL_ARTICLES_QUERY)
  return (results ?? []).map(toArticle)
}

export async function getArticleBySlug(slug: string): Promise<Article | undefined> {
  const result = await sanityClient.fetch<SanityArticle | null>(ARTICLE_BY_SLUG_QUERY, { slug })
  return result ? toArticle(result) : undefined
}

// One formatter per month style. timeZone: 'UTC' is essential: article dates are
// date-only strings (parsed as UTC midnight), so formatting in UTC keeps the
// displayed calendar date identical for every viewer. Without it, negative-offset
// timezones (e.g. US Pacific, where the business is based) render the prior day.
const dateFormatters: Record<'short' | 'long', Intl.DateTimeFormat> = {
  short: new Intl.DateTimeFormat('en-US', { year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC' }),
  long: new Intl.DateTimeFormat('en-US', { year: 'numeric', month: 'long', day: 'numeric', timeZone: 'UTC' }),
}

/**
 * Format an article's date-only ISO string (e.g. `"2026-05-12"`) for display.
 * Returns the original string unchanged when it can't be parsed.
 *
 * @param iso   A date-only ISO string.
 * @param style `'short'` → `"May 12, 2026"` (default); `'long'` → `"May 12, 2026"`
 *              with the full month name (e.g. `"September 20, 2026"`).
 */
export function formatArticleDate(iso: string, style: 'short' | 'long' = 'short'): string {
  const parsed = new Date(iso)
  return Number.isNaN(parsed.getTime()) ? iso : dateFormatters[style].format(parsed)
}
