import Link from 'next/link'
import Badge from '@/components/ui/Badge'
import { formatArticleDate, type ArticleSummary } from '@/lib/articles'

/** Preview card for an article, linking to its full page. */
export default function ArticleCard({ article }: { article: ArticleSummary }) {
  return (
    <Link
      href={`/articles/${article.slug}`}
      className="group flex h-full flex-col rounded-2xl border border-line bg-cream p-6 hover-lift hover:border-mint hover:shadow-card"
    >
      <Badge>{article.category}</Badge>
      <h3 className="mt-3 font-serif text-[21px] font-semibold leading-snug text-forest-deep group-hover:text-forest">
        {article.title}
      </h3>
      <p className="mt-2 flex-1 text-[15px] text-[#4a4339]">{article.excerpt}</p>
      <div className="mt-4 flex items-center gap-2 font-sans text-[13px] text-muted">
        <time dateTime={article.date}>{formatArticleDate(article.date)}</time>
        <span aria-hidden>·</span>
        <span>{article.readingTime}</span>
      </div>
    </Link>
  )
}
