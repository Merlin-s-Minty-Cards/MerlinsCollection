'use client'

import type { ReactNode } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'

// Markdown headings (#, ##, ###...) all render as one small, consistent
// heading size — a full-size <h1> would blow out a compact chat bubble.
const heading = ({ children }: { children?: ReactNode }) => (
  <h4 className="mb-1 mt-2 text-sm font-semibold text-pine-100 first:mt-0">{children}</h4>
)

const components: Components = {
  p: ({ children }) => <p className="leading-relaxed">{children}</p>,
  strong: ({ children }) => <strong className="font-semibold text-pine-100">{children}</strong>,
  em: ({ children }) => <em className="italic">{children}</em>,
  h1: heading,
  h2: heading,
  h3: heading,
  h4: heading,
  h5: heading,
  h6: heading,
  ul: ({ children }) => <ul className="ml-4 list-disc space-y-0.5">{children}</ul>,
  ol: ({ children }) => <ol className="ml-4 list-decimal space-y-0.5">{children}</ol>,
  li: ({ children }) => <li>{children}</li>,
  a: ({ href, children }) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-mint underline underline-offset-2 hover:text-mint-soft"
    >
      {children}
    </a>
  ),
  code: ({ children }) => (
    <code className="rounded bg-pine-800 px-1 py-0.5 font-mono text-xs text-mint">{children}</code>
  ),
  pre: ({ children }) => (
    <pre className="overflow-x-auto rounded bg-pine-800 p-2 font-mono text-xs">{children}</pre>
  ),
  table: ({ children }) => <table className="my-1 border-collapse text-xs">{children}</table>,
  th: ({ children }) => <th className="border border-pine-700 px-2 py-1 text-left">{children}</th>,
  td: ({ children }) => <td className="border border-pine-700 px-2 py-1">{children}</td>,
}

export default function MarkdownMessage({ content }: { content: string }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
      {content}
    </ReactMarkdown>
  )
}
