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

import ArticlePage, { generateStaticParams } from '@/app/(public)/articles/[slug]/page'
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
