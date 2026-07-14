// Article content layer — backed by the Sanity CMS. The business authors
// articles at /studio; these functions read what they publish.

import type { PortableTextBlock } from '@portabletext/types'
import { sanityClient } from '@/lib/sanity'

/** An image resolved to something `next/image` can actually render. */
export interface ArticleImage {
  url?: string
  dimensions?: { width: number; height: number }
  alt?: string
  caption?: string
}

/** An inline image an editor placed in the body. */
export type ArticleImageBlock = ArticleImage & { _type: 'image'; _key: string }

export type ArticleBodyBlock = PortableTextBlock | ArticleImageBlock

export interface ArticleCta {
  label?: string
  href?: string
}

/** What a listing card shows. The listing never fetches the body (see LIST_FIELDS). */
export interface ArticleSummary {
  slug: string
  title: string
  excerpt: string
  /** Date-only (`YYYY-MM-DD`), narrowed from Sanity's `publishedAt` datetime. */
  date: string
  readingTime: string
  category: string
}

export interface Article extends ArticleSummary {
  body: ArticleBodyBlock[]
  // Nothing below is required in the Studio, so it is all genuinely optional here.
  seoDescription?: string
  shareImage?: ArticleImage
  cta?: ArticleCta
}

/** A document as the GROQ projections below return it, before `date` is narrowed. */
type SanityDoc<T extends ArticleSummary> = Omit<T, 'date'> & { publishedAt: string }

/** Narrow Sanity's `publishedAt` datetime to the date-only string the pages render. */
function narrowDate<T extends ArticleSummary>(doc: SanityDoc<T>): T {
  const { publishedAt, ...rest } = doc
  return { ...rest, date: (publishedAt ?? '').slice(0, 10) } as unknown as T
}

// next/image refuses to render a remote image without intrinsic dimensions, and
// an image block only holds an asset *reference* — so resolve each one to its URL
// and size here rather than shipping a reference the renderer can't use.
const IMAGE_PROJECTION = `"url": asset->url, "dimensions": asset->metadata.dimensions`

/** What the listing cards render — deliberately no body, so no image joins. */
const LIST_FIELDS = `
  "slug": slug.current,
  title,
  excerpt,
  publishedAt,
  readingTime,
  category
`

/** Everything the article page needs, including the body and its images. */
const DETAIL_FIELDS = `
  ${LIST_FIELDS},
  seoDescription,
  shareImage{ ${IMAGE_PROJECTION} },
  cta{ label, href },
  body[]{
    ...,
    _type == "image" => { ${IMAGE_PROJECTION} }
  }
`

// Only articles with a slug are reachable. Drafts are excluded by the client's
// `published` perspective (see lib/sanity.ts). Newest first, matching the listing.
const ALL_ARTICLES_QUERY = `*[_type == "article" && defined(slug.current)]
  | order(publishedAt desc) { ${LIST_FIELDS} }`

// $slug is a query *parameter*, not string interpolation — the slug comes from
// the URL, and interpolating it straight into GROQ would be an injection hole.
const ARTICLE_BY_SLUG_QUERY = `*[_type == "article" && slug.current == $slug][0] { ${DETAIL_FIELDS} }`

/**
 * Sanity stores `publishedAt` as a full datetime, but the pages only ever show a
 * calendar date. Truncating to `YYYY-MM-DD` here is what keeps `formatArticleDate`
 * timezone-safe downstream (see its comment).
 */
export async function getAllArticles(): Promise<ArticleSummary[]> {
  const results = await sanityClient.fetch<SanityDoc<ArticleSummary>[]>(ALL_ARTICLES_QUERY)
  return (results ?? []).map(narrowDate)
}

export async function getArticleBySlug(slug: string): Promise<Article | undefined> {
  const result = await sanityClient.fetch<SanityDoc<Article> | null>(ARTICLE_BY_SLUG_QUERY, { slug })
  return result ? narrowDate(result) : undefined
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
