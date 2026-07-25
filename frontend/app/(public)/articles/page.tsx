import type { Metadata } from 'next'
import Container from '@/components/ui/Container'
import Eyebrow from '@/components/ui/Eyebrow'
import Reveal from '@/components/ui/Reveal'
import ArticleList from '@/components/articles/ArticleList'
import StudioLink from '@/components/articles/StudioLink'
import { getAllArticles } from '@/lib/articles'

export const metadata: Metadata = { title: 'Articles' }

// Re-fetch from Sanity at most once a minute, so newly published articles appear
// without a rebuild while the page stays cached and cheap for everyone else.
export const revalidate = 60

export default async function ArticlesPage() {
  const articles = await getAllArticles()

  return (
    <section className="py-[clamp(48px,8vw,84px)]">
      <Container>
        <Reveal>
          <Eyebrow>Learn the hobby</Eyebrow>
          <h1 className="mt-3 max-w-[20ch] font-serif text-[clamp(34px,6.4vw,52px)] font-semibold leading-[1.05] tracking-[-0.01em] text-forest-deep">
            Articles &amp; guides
          </h1>
          <div className="mt-4 flex flex-wrap items-start justify-between gap-4">
            <p className="max-w-[54ch] text-[clamp(16px,2.4vw,19px)] text-[#4a4339]">
              Everything we wish someone had told us when we started — written for new collectors
              and the parents helping their kids get into it.
            </p>
            <StudioLink />
          </div>
        </Reveal>

        <div className="mt-10">
          <ArticleList articles={articles} />
        </div>
      </Container>
    </section>
  )
}
