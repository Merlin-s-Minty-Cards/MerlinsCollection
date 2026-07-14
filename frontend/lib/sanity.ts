import { createClient } from '@sanity/client'

export const sanityClient = createClient({
  projectId: process.env.NEXT_PUBLIC_SANITY_PROJECT_ID ?? '',
  dataset: process.env.NEXT_PUBLIC_SANITY_DATASET ?? 'production',
  apiVersion: '2024-01-01',
  // Sanity stores in-progress edits as `drafts.*` documents in the same dataset,
  // and a public dataset hands them to an unauthenticated reader. Without this,
  // /articles would list a draft next to its published twin and an article page
  // could serve half-finished text.
  perspective: 'published',
  // The pages that call this are ISR-cached by Next already, so Sanity's own CDN
  // cache would only add a second layer of staleness on top of the 60s window.
  useCdn: false,
})
