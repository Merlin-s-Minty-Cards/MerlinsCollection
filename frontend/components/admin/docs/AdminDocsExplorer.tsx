'use client'

import { useEffect, useMemo, useState } from 'react'
import { Search } from 'lucide-react'
import { useAdminDocs } from '@/lib/use-admin-docs'
import MarkdownMessage from '@/components/inventory/MarkdownMessage'

/**
 * The admin operations knowledge base browser (RFC 0026) — categories not
 * a single continuous page, plus in-page search. Extends the public
 * Collectors Dictionary's proven shape (`DictionaryExplorer.tsx`: a plain,
 * case-insensitive substring filter, no fuzzy-search dependency) rather than
 * reinventing search for a knowledge base of a few dozen short articles.
 *
 * The category list comes from the fetched `categories` (from
 * `GET /admin/docs`), never a second hardcoded list here — the exact
 * "two sources of truth for the same taxonomy" drift this codebase has
 * already paid for once (the Consignor filter / Card Number column).
 *
 * A non-empty search query OVERRIDES the category filter and searches every
 * article, showing each hit's category as a badge — a real question
 * ("what does Sync Prices cost") is answered faster by search than by first
 * guessing which section it lives in.
 */
export default function AdminDocsExplorer() {
  const { categories, articles, loading, error } = useAdminDocs()
  const [query, setQuery] = useState('')
  const [activeCategory, setActiveCategory] = useState<string | null>(null)
  const [expandedId, setExpandedId] = useState<string | null>(null)

  // Default to the first category once it's known, rather than dumping
  // every article on one page — "not one continuous page" is the point.
  useEffect(() => {
    if (!activeCategory && categories.length > 0) {
      setActiveCategory(categories[0].id)
    }
  }, [categories, activeCategory])

  const trimmedQuery = query.trim()
  const searching = trimmedQuery.length > 0

  const visible = useMemo(() => {
    if (searching) {
      const needle = trimmedQuery.toLowerCase()
      return articles.filter((a) =>
        [a.title, a.summary, a.body, ...a.keywords].join(' ').toLowerCase().includes(needle),
      )
    }
    return articles.filter((a) => a.category === activeCategory)
  }, [articles, trimmedQuery, searching, activeCategory])

  const categoryLabel = (id: string) => categories.find((c) => c.id === id)?.label ?? id

  if (loading) {
    return <p className="text-sm text-pine-300">Loading documentation…</p>
  }

  if (error) {
    return (
      <p className="text-sm text-red-300">
        Couldn&rsquo;t load documentation. Try refreshing the page.
      </p>
    )
  }

  return (
    <div className="flex flex-col gap-6 md:flex-row">
      <div className="md:w-56 md:flex-shrink-0">
        <div className="relative mb-4">
          <Search
            size={16}
            aria-hidden
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-pine-400"
          />
          <input
            type="text"
            aria-label="Search docs"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search…"
            className="vault-field w-full rounded-lg py-2 pl-9 pr-3 text-sm"
          />
        </div>
        {!searching && (
          <nav className="flex flex-row flex-wrap gap-1 md:flex-col" aria-label="Doc categories">
            {categories.map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => setActiveCategory(c.id)}
                className={`rounded-md px-3 py-2 text-left text-sm transition-colors ${
                  activeCategory === c.id
                    ? 'bg-mint/15 text-mint'
                    : 'text-pine-300 hover:bg-pine-800 hover:text-mint'
                }`}
              >
                {c.label}
              </button>
            ))}
          </nav>
        )}
      </div>

      <div className="min-w-0 flex-1 space-y-3">
        {visible.length === 0 && (
          <p className="text-sm text-pine-300">No articles match your search.</p>
        )}
        {visible.map((a) => {
          const expanded = expandedId === a.id
          return (
            <div key={a.id} className="vault-panel rounded-xl p-4">
              <button
                type="button"
                onClick={() => setExpandedId(expanded ? null : a.id)}
                className="w-full text-left"
              >
                <div className="flex items-center justify-between gap-2">
                  <h3 className="font-serif text-base text-pine-100">{a.title}</h3>
                  {searching && (
                    <span className="shrink-0 rounded-full bg-mint/15 px-2 py-0.5 text-xs text-mint">
                      {categoryLabel(a.category)}
                    </span>
                  )}
                </div>
                <p className="mt-1 text-sm text-pine-300">{a.summary}</p>
              </button>
              {expanded && (
                <div
                  data-testid="admin-docs-article-body"
                  className="mt-3 border-t border-pine-700 pt-3 text-sm text-pine-200"
                >
                  <MarkdownMessage content={a.body} />
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
