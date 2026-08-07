/**
 * Pure logic — no DOM. Runs in `node` rather than the default jsdom:
 * constructing a jsdom per file was the single largest cost in this
 * suite (215s cumulative `environment` time against 55s of actual tests).
 * If this file ever renders a component or touches window/document,
 * delete this docblock rather than stubbing the DOM by hand.
 *
 * @vitest-environment node
 */
import { describe, it, expect } from 'vitest'
import article from '@/sanity/schemas/article'

type Field = {
  name: string
  type: string
  of?: { type: string }[]
  fields?: Field[]
  validation?: unknown
}

const fieldNamed = (name: string, fields: Field[] = article.fields as Field[]): Field | undefined =>
  fields.find((f) => f.name === name)

describe('article schema', () => {
  it('is a document type named "article"', () => {
    expect(article.name).toBe('article')
    expect(article.type).toBe('document')
  })

  it('defines every field the article pages render', () => {
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

  describe('inline images', () => {
    const imageBlock = () =>
      (fieldNamed('body')?.of as { type: string; fields?: Field[] }[] | undefined)?.find(
        (t) => t.type === 'image',
      )

    it('lets an editor place an image inside the body', () => {
      expect(imageBlock()).toBeDefined()
    })

    it('carries alt text and a caption alongside the image', () => {
      const fields = imageBlock()?.fields as Field[]
      expect(fieldNamed('alt', fields)?.type).toBe('string')
      expect(fieldNamed('caption', fields)?.type).toBe('string')
    })

    it('requires alt text, so a published image can never be unreadable', () => {
      // Without a validation rule editors skip alt, which both breaks screen
      // readers and trips the jsx-a11y lint rule at build time.
      const fields = imageBlock()?.fields as Field[]
      expect(fieldNamed('alt', fields)?.validation).toBeTypeOf('function')
    })
  })

  describe('SEO and social sharing', () => {
    it('has a description used for search results and link previews', () => {
      expect(fieldNamed('seoDescription')?.type).toBe('text')
    })

    it('has a dedicated social share image', () => {
      expect(fieldNamed('shareImage')?.type).toBe('image')
    })
  })

  describe('call to action', () => {
    it('has a CTA with a label and a link', () => {
      const cta = fieldNamed('cta')
      expect(cta?.type).toBe('object')
      const fields = cta?.fields as Field[]
      expect(fieldNamed('label', fields)?.type).toBe('string')
      expect(fieldNamed('href', fields)?.type).toBe('url')
    })
  })
})
