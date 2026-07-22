import { describe, it, expect, vi, beforeEach } from 'vitest'

// Sanity is a network boundary — stub the client, exercise our own mapping.
// isSanityConfigured is true here: these tests cover the configured path where
// the article layer actually queries Sanity (the unconfigured path is covered in
// sanity-unconfigured.test.ts).
vi.mock('@/lib/sanity', () => ({
  sanityClient: { fetch: vi.fn() },
  isSanityConfigured: true,
}))

import { sanityClient } from '@/lib/sanity'
import { getAllArticles, getArticleBySlug, formatArticleDate } from '@/lib/articles'

const fetchMock = vi.mocked(sanityClient.fetch)

/** A document shaped the way our GROQ projection returns it. */
const sanityDoc = (overrides: Record<string, unknown> = {}) => ({
  slug: 'grading-101',
  title: 'Grading 101',
  excerpt: 'When grading pays off.',
  publishedAt: '2026-11-03T14:30:00Z',
  readingTime: '6 min read',
  category: 'Guides',
  body: [{ _type: 'block', children: [{ _type: 'span', text: 'Hello' }] }],
  ...overrides,
})

beforeEach(() => {
  fetchMock.mockReset()
})

describe('article queries', () => {
  it('resolves inline image assets to a URL and intrinsic size', async () => {
    // An image block holds only an asset *reference*. next/image cannot render
    // that — it needs a URL and dimensions — so the query must dereference it.
    fetchMock.mockResolvedValue(sanityDoc())

    await getArticleBySlug('grading-101')

    const [query] = fetchMock.mock.calls[0]
    expect(query).toContain('asset->url')
    expect(query).toContain('asset->metadata.dimensions')
  })

  it('asks for the SEO and CTA fields the article page renders', async () => {
    fetchMock.mockResolvedValue(sanityDoc())

    await getArticleBySlug('grading-101')

    const [query] = fetchMock.mock.calls[0]
    expect(query).toContain('seoDescription')
    expect(query).toContain('shareImage')
    expect(query).toContain('cta')
  })

  it('does not download article bodies just to list them', async () => {
    // The listing renders titles and excerpts. Pulling every article's full body
    // (and joining every inline image asset) to throw it away is pure waste.
    fetchMock.mockResolvedValue([])

    await getAllArticles()

    const [query] = fetchMock.mock.calls[0]
    expect(query).not.toContain('body')
  })
})

describe('getAllArticles', () => {
  it('returns the articles Sanity publishes', async () => {
    fetchMock.mockResolvedValue([sanityDoc()])

    const [article] = await getAllArticles()

    expect(article.slug).toBe('grading-101')
    expect(article.title).toBe('Grading 101')
    expect(article.excerpt).toBe('When grading pays off.')
    expect(article.readingTime).toBe('6 min read')
    expect(article.category).toBe('Guides')
    expect(article.body).toEqual([
      { _type: 'block', children: [{ _type: 'span', text: 'Hello' }] },
    ])
  })

  it('narrows the publish timestamp to a date-only string', async () => {
    // publishedAt is a datetime, but the page renders a calendar date. Keeping
    // `date` date-only is what lets formatArticleDate stay timezone-safe.
    fetchMock.mockResolvedValue([sanityDoc({ publishedAt: '2026-11-03T14:30:00Z' })])

    const [article] = await getAllArticles()

    expect(article.date).toBe('2026-11-03')
  })

  it('returns an empty list when nothing is published yet', async () => {
    fetchMock.mockResolvedValue([])

    expect(await getAllArticles()).toEqual([])
  })
})

describe('getArticleBySlug', () => {
  it('returns the article matching the slug', async () => {
    fetchMock.mockResolvedValue(sanityDoc({ slug: 'spotting-fakes' }))

    const article = await getArticleBySlug('spotting-fakes')

    expect(article?.slug).toBe('spotting-fakes')
    expect(article?.date).toBe('2026-11-03')
  })

  it('passes the slug to Sanity as a parameter rather than string interpolation', async () => {
    // Interpolating user input into a GROQ query is an injection risk; params
    // keep the query and the value separate.
    fetchMock.mockResolvedValue(sanityDoc())

    await getArticleBySlug('spotting-fakes')

    expect(fetchMock).toHaveBeenCalledWith(expect.any(String), { slug: 'spotting-fakes' })
  })

  it('returns undefined when no article matches the slug', async () => {
    fetchMock.mockResolvedValue(null)

    expect(await getArticleBySlug('does-not-exist')).toBeUndefined()
  })
})

describe('formatArticleDate', () => {
  it('formats a date-only ISO string by its calendar date, independent of timezone', () => {
    // Parsed as UTC midnight; must render the same day everywhere (no off-by-one).
    expect(formatArticleDate('2026-09-20')).toBe('Sep 20, 2026')
  })

  it('supports a long month style for the article page', () => {
    expect(formatArticleDate('2026-09-20', 'long')).toBe('September 20, 2026')
  })

  it('falls back to the original string when the date is unparseable', () => {
    expect(formatArticleDate('not-a-date')).toBe('not-a-date')
  })
})
