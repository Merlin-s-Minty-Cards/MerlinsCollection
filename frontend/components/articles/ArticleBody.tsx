import { PortableText, type PortableTextComponents } from '@portabletext/react'
import type { Article } from '@/lib/articles'

// Maps the block styles and marks an editor can pick in the Studio onto the
// site's typography. Anything not listed here falls back to Portable Text's
// defaults, so adding a style in Sanity degrades gracefully rather than crashing.
const components: PortableTextComponents = {
  block: {
    normal: ({ children }) => <p>{children}</p>,
    h2: ({ children }) => (
      <h2 className="mt-10 font-serif text-[26px] font-semibold leading-snug text-forest-deep">
        {children}
      </h2>
    ),
    h3: ({ children }) => (
      <h3 className="mt-8 font-serif text-[21px] font-semibold leading-snug text-forest-deep">
        {children}
      </h3>
    ),
    blockquote: ({ children }) => (
      <blockquote className="border-l-2 border-mint pl-4 italic text-[#4a4339]">
        {children}
      </blockquote>
    ),
  },
  list: {
    bullet: ({ children }) => <ul className="list-disc space-y-2 pl-5">{children}</ul>,
    number: ({ children }) => <ol className="list-decimal space-y-2 pl-5">{children}</ol>,
  },
  marks: {
    strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
    em: ({ children }) => <em>{children}</em>,
    link: ({ children, value }) => (
      // noopener/noreferrer: these hrefs are editor-supplied, so treat them as
      // untrusted and deny the target page access to window.opener.
      <a
        href={value?.href}
        target="_blank"
        rel="noopener noreferrer"
        className="font-medium text-forest underline underline-offset-2 hover:text-forest-deep"
      >
        {children}
      </a>
    ),
  },
}

/** Renders an article's Portable Text body in the site's article typography. */
export default function ArticleBody({ value }: { value: Article['body'] }) {
  return <PortableText value={value} components={components} />
}
