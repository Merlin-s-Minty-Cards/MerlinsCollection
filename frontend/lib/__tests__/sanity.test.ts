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

  it('bypasses the Sanity CDN, since ISR already caches the result', () => {
    // Stacking Sanity's CDN cache on top of the 60s ISR window would compound
    // staleness and buy nothing — the render is already cached by Next.
    expect(sanityClient.config().useCdn).toBe(false)
  })
})
