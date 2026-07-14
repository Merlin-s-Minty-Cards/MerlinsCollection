import { describe, it, expect } from 'vitest'
import article from '@/sanity/schemas/article'

type Field = { name: string; type: string; of?: { type: string }[] }

const fieldNamed = (name: string): Field | undefined =>
  (article.fields as Field[]).find((f) => f.name === name)

describe('article schema', () => {
  it('is a document type named "article"', () => {
    expect(article.name).toBe('article')
    expect(article.type).toBe('document')
  })

  it('defines every field the article pages render', () => {
    // The site renders each of these; a missing field means editors cannot
    // supply content the page expects.
    expect(fieldNamed('title')?.type).toBe('string')
    expect(fieldNamed('slug')?.type).toBe('slug')
    expect(fieldNamed('excerpt')?.type).toBe('text')
    expect(fieldNamed('publishedAt')?.type).toBe('datetime')
    expect(fieldNamed('readingTime')?.type).toBe('string')
    expect(fieldNamed('category')?.type).toBe('string')
  })

  it('stores the body as Portable Text so editors get real formatting', () => {
    const body = fieldNamed('body')
    expect(body?.type).toBe('array')
    expect(body?.of).toContainEqual({ type: 'block' })
  })
})
