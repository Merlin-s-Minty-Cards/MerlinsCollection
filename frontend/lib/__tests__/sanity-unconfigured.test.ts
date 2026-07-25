import { describe, it, expect, afterEach, vi } from 'vitest'

// The public site is built in CI and Docker WITHOUT CMS credentials
// (NEXT_PUBLIC_SANITY_PROJECT_ID is empty). `@sanity/client` throws
// "Configuration must contain `projectId`" on an empty id, which crashed
// `next build` while collecting page data for /articles/[slug]. The article
// pages are ISR (revalidate = 60), so a credential-less build must succeed and
// render on demand once real env is present at runtime.

afterEach(() => {
  vi.unstubAllEnvs()
  vi.resetModules()
})

describe('Sanity, when the build has no CMS credentials', () => {
  it('imports the client module without throwing', async () => {
    vi.stubEnv('NEXT_PUBLIC_SANITY_PROJECT_ID', '')
    vi.resetModules()

    const mod = await import('@/lib/sanity')

    expect(mod.isSanityConfigured).toBe(false)
  })

  it('reports Sanity as configured when a project id is present', async () => {
    vi.stubEnv('NEXT_PUBLIC_SANITY_PROJECT_ID', 'aqhayya8')
    vi.resetModules()

    const mod = await import('@/lib/sanity')

    expect(mod.isSanityConfigured).toBe(true)
  })

  it('lists no articles without hitting the network', async () => {
    vi.stubEnv('NEXT_PUBLIC_SANITY_PROJECT_ID', '')
    vi.resetModules()

    const { sanityClient } = await import('@/lib/sanity')
    const fetchSpy = vi.spyOn(sanityClient, 'fetch')
    const { getAllArticles } = await import('@/lib/articles')

    expect(await getAllArticles()).toEqual([])
    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it('resolves an article slug to undefined without hitting the network', async () => {
    vi.stubEnv('NEXT_PUBLIC_SANITY_PROJECT_ID', '')
    vi.resetModules()

    const { sanityClient } = await import('@/lib/sanity')
    const fetchSpy = vi.spyOn(sanityClient, 'fetch')
    const { getArticleBySlug } = await import('@/lib/articles')

    expect(await getArticleBySlug('anything')).toBeUndefined()
    expect(fetchSpy).not.toHaveBeenCalled()
  })
})
