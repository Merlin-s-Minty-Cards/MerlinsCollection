import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import ArticleCard from '@/components/articles/ArticleCard'
import type { Article } from '@/lib/articles'

const article: Article = {
  slug: 'grading-101',
  title: 'Grading 101: is your card worth slabbing?',
  excerpt: 'When professional grading pays off — and when it just costs you.',
  date: '2026-05-12',
  readingTime: '6 min read',
  category: 'Guides',
  body: [
    {
      _type: 'block',
      _key: 'a1',
      children: [{ _type: 'span', _key: 's1', text: 'First paragraph.' }],
    },
  ],
}

describe('ArticleCard', () => {
  it('links to the article and shows its title and excerpt', () => {
    render(<ArticleCard article={article} />)
    const link = screen.getByRole('link', { name: /Grading 101/i })
    expect(link).toHaveAttribute('href', '/articles/grading-101')
    expect(screen.getByText(article.excerpt)).toBeInTheDocument()
    expect(screen.getByText('6 min read')).toBeInTheDocument()
  })
})
