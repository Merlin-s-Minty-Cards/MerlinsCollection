import ArticleCard from './ArticleCard'
import Reveal from '@/components/ui/Reveal'
import type { ArticleSummary } from '@/lib/articles'

/** Grid of article preview cards. */
export default function ArticleList({ articles }: { articles: ArticleSummary[] }) {
  return (
    <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
      {articles.map((article, i) => (
        <Reveal key={article.slug} delay={i * 80}>
          <ArticleCard article={article} />
        </Reveal>
      ))}
    </div>
  )
}
