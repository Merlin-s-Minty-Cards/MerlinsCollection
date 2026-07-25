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

  it('drops a link whose href is a javascript: URI', () => {
    // Hrefs are editor-supplied. Rendering this one would be stored XSS.
    const hostile = {
      _type: 'block',
      _key: 'k1',
      style: 'normal',
      markDefs: [{ _type: 'link', _key: 'l1', href: 'javascript:alert(1)' }],
      children: [{ _type: 'span', _key: 's1', text: 'click me', marks: ['l1'] }],
    } as Article['body'][number]

    render(<ArticleBody value={[hostile]} />)

    expect(screen.queryByRole('link')).not.toBeInTheDocument()
    // The text survives; only the dangerous link is stripped.
    expect(screen.getByText('click me')).toBeInTheDocument()
  })
})

describe('ArticleBody inline images', () => {
  const image = (overrides: Record<string, unknown> = {}) =>
    ({
      _type: 'image',
      _key: 'i1',
      url: 'https://cdn.sanity.io/images/aqhayya8/production/abc-1200x800.jpg',
      dimensions: { width: 1200, height: 800 },
      alt: 'A Base Set Charizard in a slab',
      ...overrides,
    }) as Article['body'][number]

  it('renders an image the editor placed in the body', () => {
    render(<ArticleBody value={[image()]} />)

    expect(screen.getByRole('img', { name: 'A Base Set Charizard in a slab' })).toBeInTheDocument()
  })

  it('shows the caption underneath the image', () => {
    render(<ArticleBody value={[image({ caption: 'Graded PSA 9.' })]} />)

    expect(screen.getByText('Graded PSA 9.')).toBeInTheDocument()
  })

  it('renders an image with no caption without an empty caption element', () => {
    const { container } = render(<ArticleBody value={[image()]} />)

    expect(container.querySelector('figcaption')).toBeNull()
  })

  it('treats an image with no alt text as decorative rather than crashing', () => {
    // alt is required in the Studio, but data written before that rule (or via
    // the API) can still lack it. An empty alt is the correct a11y fallback.
    render(<ArticleBody value={[image({ alt: undefined })]} />)

    expect(screen.getByRole('presentation', { hidden: true })).toBeInTheDocument()
  })

  it('skips an image whose asset failed to resolve', () => {
    const { container } = render(
      <ArticleBody value={[image({ url: undefined, dimensions: undefined })]} />,
    )

    expect(container.querySelector('img')).toBeNull()
  })
})
