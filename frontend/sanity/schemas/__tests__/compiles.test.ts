import { describe, it, expect } from 'vitest'
import { createSchema } from 'sanity'
import article from '@/sanity/schemas/article'

// The schema is the riskiest file here: a bad field type or a typo'd validation
// rule (`rule.reqired()`) only surfaces when the Studio boots. Compiling it the
// way Sanity does turns that into a test failure instead of a broken CMS.
describe('sanity schema', () => {
  const schema = createSchema({ name: 'test', types: [article] })

  it('compiles the article type', () => {
    expect(schema.getTypeNames()).toContain('article')
  })

  it('has no schema validation errors', () => {
    const problems = schema
      ._validation!.flatMap((group) => group.problems ?? [])
      .filter((p) => p.severity === 'error')

    expect(problems).toEqual([])
  })
})
