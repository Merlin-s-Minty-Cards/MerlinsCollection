import { createClient } from '@sanity/client'

const projectId = process.env.NEXT_PUBLIC_SANITY_PROJECT_ID ?? ''

// The public site is built in CI and Docker without CMS credentials, so
// projectId is empty there. `@sanity/client` throws on an empty projectId, which
// would crash `next build` when it evaluates this module while collecting page
// data. The article layer checks this flag and skips fetches during such a build;
// the pages are ISR (revalidate = 60) and hydrate once real env is present.
export const isSanityConfigured = projectId.length > 0

export const sanityClient = createClient({
  // `placeholder` is a valid id that keeps createClient from throwing during a
  // credential-less build; it is never actually queried (see isSanityConfigured).
  projectId: projectId || 'placeholder',
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
