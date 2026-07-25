import type { Metadata } from 'next'
import Link from 'next/link'
import { notFound } from 'next/navigation'
import Container from '@/components/ui/Container'
import Badge from '@/components/ui/Badge'
import Button from '@/components/ui/Button'
import ArticleBody from '@/components/articles/ArticleBody'
import { getAllArticles, getArticleBySlug, formatArticleDate } from '@/lib/articles'
import { safeHref } from '@/lib/safe-href'

type Props = { params: Promise<{ slug: string }> }

// Articles published after the last build render on demand and are then cached,
// so new writing goes live without a rebuild.
export const revalidate = 60

export async function generateStaticParams() {
  const articles = await getAllArticles()
  return articles.map((a) => ({ slug: a.slug }))
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params
  const article = await getArticleBySlug(slug)
  if (!article) return { title: 'Article not found' }

  // The excerpt already summarises the article, so it is the natural fallback
  // when an editor hasn't written a dedicated SEO description.
  const description = article.seoDescription || article.excerpt
  // Social scrapers cap image size and expect ~1200x630; the raw Sanity original
  // can be many MB, which they reject. Constrain it to the standard OG dimensions.
  const shareImage = article.shareImage?.url
    ? `${article.shareImage.url}?w=1200&h=630&fit=crop&auto=format`
    : undefined

  return {
    title: article.title,
    description,
    openGraph: {
      title: article.title,
      description,
      type: 'article',
      publishedTime: article.date,
      images: shareImage ? [{ url: shareImage, width: 1200, height: 630 }] : undefined,
    },
  }
}

export default async function ArticlePage({ params }: Props) {
  const { slug } = await params
  const article = await getArticleBySlug(slug)
  if (!article) notFound()

  const date = formatArticleDate(article.date, 'long')
  // Editor-supplied link: vet the scheme before rendering it (see lib/safe-href).
  const ctaHref = safeHref(article.cta?.href)
  const ctaLabel = article.cta?.label

  return (
    <Container className="py-[clamp(40px,7vw,76px)]">
      <article className="mx-auto max-w-[68ch]">
        <Link
          href="/articles"
          className="font-sans text-[14px] font-semibold text-forest hover:text-forest-deep"
        >
          ← All articles
        </Link>

        <div className="mt-6">
          <Badge>{article.category}</Badge>
        </div>
        <h1 className="mt-3 font-serif text-[clamp(30px,5.4vw,46px)] font-semibold leading-[1.08] tracking-[-0.01em] text-forest-deep">
          {article.title}
        </h1>
        <div className="mt-3 flex items-center gap-2 font-sans text-[14px] text-muted">
          <time dateTime={article.date}>{date}</time>
          <span aria-hidden>·</span>
          <span>{article.readingTime}</span>
        </div>

        <div className="mt-8 space-y-5 text-[17px] leading-[1.7] text-[#3f3a33]">
          <ArticleBody value={article.body} />
        </div>

        {ctaHref && ctaLabel ? (
          <div className="mt-12 rounded-2xl border border-line bg-mint/10 p-6 text-center">
            <Button href={ctaHref} className="px-6 py-3">
              {ctaLabel}
            </Button>
          </div>
        ) : null}
      </article>
    </Container>
  )
}
