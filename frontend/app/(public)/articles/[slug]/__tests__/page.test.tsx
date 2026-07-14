import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@/lib/articles', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/articles')>()),
  getAllArticles: vi.fn(),
  getArticleBySlug: vi.fn(),
}))

vi.mock('next/navigation', () => ({
  notFound: vi.fn(() => {
    throw new Error('NEXT_NOT_FOUND')
  }),
}))

import ArticlePage, { generateStaticParams, generateMetadata } from '@/app/(public)/articles/[slug]/page'
import { getAllArticles, getArticleBySlug, type Article } from '@/lib/articles'

const getArticleBySlugMock = vi.mocked(getArticleBySlug)
const getAllArticlesMock = vi.mocked(getAllArticles)

const article: Article = {
  slug: 'grading-101',
  title: 'Grading 101: is your card worth slabbing?',
  excerpt: 'When professional grading pays off.',
  date: '2026-05-12',
  readingTime: '6 min read',
  category: 'Guides',
  body: [
    {
      _type: 'block',
      _key: 'k1',
      style: 'normal',
      markDefs: [],
      children: [{ _type: 'span', _key: 's1', text: 'Grading can pay for itself.', marks: [] }],
    },
  ] as Article['body'],
}

beforeEach(() => {
  getArticleBySlugMock.mockReset()
  getAllArticlesMock.mockReset()
})

describe('Article page', () => {
  it('renders the article Sanity returns for the slug', async () => {
    getArticleBySlugMock.mockResolvedValue(article)

    render(await ArticlePage({ params: Promise.resolve({ slug: 'grading-101' }) }))

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(/Grading 101/i)
    expect(screen.getByText('Guides')).toBeInTheDocument()
    expect(screen.getByText('6 min read')).toBeInTheDocument()
    expect(screen.getByText('May 12, 2026')).toBeInTheDocument()
  })

  it('renders the Portable Text body', async () => {
    getArticleBySlugMock.mockResolvedValue(article)

    render(await ArticlePage({ params: Promise.resolve({ slug: 'grading-101' }) }))

    expect(screen.getByText('Grading can pay for itself.')).toBeInTheDocument()
  })

  it('404s when Sanity has no article for that slug', async () => {
    getArticleBySlugMock.mockResolvedValue(undefined)

    await expect(
      ArticlePage({ params: Promise.resolve({ slug: 'does-not-exist' }) }),
    ).rejects.toThrow('NEXT_NOT_FOUND')
  })
})

describe('generateStaticParams', () => {
  it('pre-renders a page per published article', async () => {
    getAllArticlesMock.mockResolvedValue([article])

    expect(await generateStaticParams()).toEqual([{ slug: 'grading-101' }])
  })
})

describe('call to action', () => {
  it('renders the CTA the editor configured', async () => {
    getArticleBySlugMock.mockResolvedValue({
      ...article,
      cta: { label: 'Browse our inventory', href: 'https://merlinsmintycards.com/inventory' },
    })

    render(await ArticlePage({ params: Promise.resolve({ slug: 'grading-101' }) }))

    expect(screen.getByRole('link', { name: 'Browse our inventory' })).toHaveAttribute(
      'href',
      'https://merlinsmintycards.com/inventory',
    )
  })

  it('renders no CTA when the editor left it blank', async () => {
    getArticleBySlugMock.mockResolvedValue(article)

    render(await ArticlePage({ params: Promise.resolve({ slug: 'grading-101' }) }))

    expect(screen.queryByRole('link', { name: /browse our inventory/i })).not.toBeInTheDocument()
  })

  it('drops a CTA pointing at a javascript: URI', async () => {
    getArticleBySlugMock.mockResolvedValue({
      ...article,
      cta: { label: 'Click me', href: 'javascript:alert(1)' },
    })

    render(await ArticlePage({ params: Promise.resolve({ slug: 'grading-101' }) }))

    expect(screen.queryByRole('link', { name: 'Click me' })).not.toBeInTheDocument()
  })
})

describe('generateMetadata', () => {
  it('uses the article title', async () => {
    getArticleBySlugMock.mockResolvedValue(article)

    const meta = await generateMetadata({ params: Promise.resolve({ slug: 'grading-101' }) })

    expect(meta.title).toMatch(/Grading 101/)
  })

  it('uses the SEO description for search results and link previews', async () => {
    getArticleBySlugMock.mockResolvedValue({
      ...article,
      seoDescription: 'Whether grading your Pokemon card is worth the money.',
    })

    const meta = await generateMetadata({ params: Promise.resolve({ slug: 'grading-101' }) })

    expect(meta.description).toBe('Whether grading your Pokemon card is worth the money.')
    expect(meta.openGraph?.description).toBe(
      'Whether grading your Pokemon card is worth the money.',
    )
  })

  it('falls back to the excerpt when no SEO description is set', async () => {
    getArticleBySlugMock.mockResolvedValue(article)

    const meta = await generateMetadata({ params: Promise.resolve({ slug: 'grading-101' }) })

    expect(meta.description).toBe(article.excerpt)
  })

  it('advertises the social share image, constrained to the size scrapers expect', async () => {
    getArticleBySlugMock.mockResolvedValue({
      ...article,
      shareImage: { url: 'https://cdn.sanity.io/images/aqhayya8/production/share.jpg' },
    })

    const meta = await generateMetadata({ params: Promise.resolve({ slug: 'grading-101' }) })

    // The raw original can be many MB; scrapers reject that and want ~1200x630.
    expect(meta.openGraph?.images).toContainEqual(
      expect.objectContaining({
        url: expect.stringContaining('w=1200&h=630'),
        width: 1200,
        height: 630,
      }),
    )
  })

  it('omits the share image when the editor did not set one', async () => {
    getArticleBySlugMock.mockResolvedValue(article)

    const meta = await generateMetadata({ params: Promise.resolve({ slug: 'grading-101' }) })

    expect(meta.openGraph?.images).toBeUndefined()
  })
})
