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
import { sanityClient } from '@/lib/sanity'

describe('sanity client', () => {
  it('only ever reads published documents', () => {
    // Sanity keeps in-progress edits as `drafts.*` documents in the SAME dataset,
    // and a public dataset serves them to an unauthenticated client. Without this,
    // /articles shows a draft alongside its published twin, and an article page
    // can serve half-written text. This is the switch that prevents it.
    expect(sanityClient.config().perspective).toBe('published')
  })
})
