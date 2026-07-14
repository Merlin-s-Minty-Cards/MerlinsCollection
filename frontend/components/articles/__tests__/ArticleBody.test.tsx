import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import ArticleBody from '@/components/articles/ArticleBody'
import type { Article } from '@/lib/articles'

/** Build a Portable Text block the way Sanity emits one. */
const block = (
  text: string,
  { style = 'normal', marks = [] as string[] } = {},
): Article['body'][number] =>
  ({
    _type: 'block',
    _key: `k-${text.slice(0, 6)}`,
    style,
    markDefs: [],
    children: [{ _type: 'span', _key: `s-${text.slice(0, 6)}`, text, marks }],
  }) as Article['body'][number]

describe('ArticleBody', () => {
  it('renders normal blocks as paragraphs', () => {
    render(<ArticleBody value={[block('Grading can turn a good card into a great one.')]} />)

    expect(
      screen.getByText('Grading can turn a good card into a great one.'),
    ).toBeInTheDocument()
  })

  it('renders headings as real heading elements, not styled paragraphs', () => {
    // Editors reach for headings to structure a guide; they must come out
    // semantic so screen readers and search engines can follow the outline.
    render(<ArticleBody value={[block('When grading pays off', { style: 'h2' })]} />)

    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('When grading pays off')
  })

  it('renders emphasis marks the editor applied', () => {
    render(<ArticleBody value={[block('Never', { marks: ['strong'] })]} />)

    expect(screen.getByText('Never').tagName).toBe('STRONG')
  })

  it('renders an external link with safe rel attributes', () => {
    // Portable Text link marks carry the href in markDefs, keyed by the mark.
    const linked = {
      _type: 'block',
      _key: 'k1',
      style: 'normal',
      markDefs: [{ _type: 'link', _key: 'l1', href: 'https://pokemontcg.io' }],
      children: [{ _type: 'span', _key: 's1', text: 'the card API', marks: ['l1'] }],
    } as Article['body'][number]

    render(<ArticleBody value={[linked]} />)

    const link = screen.getByRole('link', { name: 'the card API' })
    expect(link).toHaveAttribute('href', 'https://pokemontcg.io')
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'))
  })

  it('renders nothing when the article has no body yet', () => {
    const { container } = render(<ArticleBody value={[]} />)

    expect(container).toBeEmptyDOMElement()
  })
})
