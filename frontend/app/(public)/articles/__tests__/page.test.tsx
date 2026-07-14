import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@/lib/articles', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/articles')>()),
  getAllArticles: vi.fn(),
}))

import ArticlesPage from '@/app/(public)/articles/page'
import { getAllArticles, type Article } from '@/lib/articles'

const getAllArticlesMock = vi.mocked(getAllArticles)

const article: Article = {
  slug: 'spotting-fakes',
  title: 'How to spot a fake Pokémon card',
  excerpt: 'Quick checks that catch the most common counterfeits.',
  date: '2026-04-02',
  readingTime: '5 min read',
  category: 'Guides',
  body: [],
}

beforeEach(() => {
  getAllArticlesMock.mockReset()
})

describe('Articles page', () => {
  it('renders the page heading', async () => {
    getAllArticlesMock.mockResolvedValue([])

    render(await ArticlesPage())

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(/articles|guides/i)
  })

  it('lists the articles published in Sanity, linking to their pages', async () => {
    getAllArticlesMock.mockResolvedValue([article])

    render(await ArticlesPage())

    const link = screen.getByRole('link', { name: /How to spot a fake/i })
    expect(link).toHaveAttribute('href', '/articles/spotting-fakes')
  })

  it('still renders the heading when nothing is published yet', async () => {
    // A brand-new Sanity dataset is empty; the page must not crash.
    getAllArticlesMock.mockResolvedValue([])

    render(await ArticlesPage())

    expect(screen.getByRole('heading', { level: 1 })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /How to spot a fake/i })).not.toBeInTheDocument()
  })
})
