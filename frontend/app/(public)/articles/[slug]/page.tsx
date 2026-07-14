import type { Metadata } from 'next'
import Link from 'next/link'
import { notFound } from 'next/navigation'
import Container from '@/components/ui/Container'
import Badge from '@/components/ui/Badge'
import ArticleBody from '@/components/articles/ArticleBody'
import { getAllArticles, getArticleBySlug, formatArticleDate } from '@/lib/articles'

type Props = { params: Promise<{ slug: string }> }

export async function generateStaticParams() {
  const articles = await getAllArticles()
  return articles.map((a) => ({ slug: a.slug }))
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params
  const article = await getArticleBySlug(slug)
  return { title: article ? article.title : 'Article not found' }
}

export default async function ArticlePage({ params }: Props) {
  const { slug } = await params
  const article = await getArticleBySlug(slug)
  if (!article) notFound()

  const date = formatArticleDate(article.date, 'long')

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
      </article>
    </Container>
  )
}
