import Image from 'next/image'
import { PortableText, type PortableTextComponents } from '@portabletext/react'
import type { Article, ArticleImageBlock } from '@/lib/articles'
import { safeHref } from '@/lib/safe-href'

/** The article column is ~68ch; 2x that covers retina without fetching originals. */
const ARTICLE_COLUMN_WIDTH = 680
const ARTICLE_IMAGE_WIDTH = ARTICLE_COLUMN_WIDTH * 2

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
    link: ({ children, value }) => {
      // Hrefs are editor-supplied and therefore untrusted: safeHref drops anything
      // that isn't a real link scheme (a `javascript:` URI here would be stored
      // XSS), and we render the text unlinked rather than losing it entirely.
      const href = safeHref(value?.href)
      if (!href) return <>{children}</>
      // Open only off-site links in a new tab; an internal link (/, #, ?) should
      // navigate in place. noopener/noreferrer denies the new page window.opener.
      const external = /^[a-z]+:/i.test(href)
      return (
        <a
          href={href}
          {...(external ? { target: '_blank', rel: 'noopener noreferrer' } : {})}
          className="font-medium text-forest underline underline-offset-2 hover:text-forest-deep"
        >
          {children}
        </a>
      )
    },
  },
  types: {
    image: ({ value }: { value: ArticleImageBlock }) => {
      // An asset that failed to resolve leaves no url/dimensions, and next/image
      // throws without them — so skip the image rather than break the article.
      if (!value.url || !value.dimensions?.width || !value.dimensions?.height) return null
      return (
        <figure className="my-8">
          <Image
            // asset->url is the untouched original — potentially a 6MB phone photo.
            // Sanity's image API caps it at render width before we ever fetch it.
            src={`${value.url}?w=${ARTICLE_IMAGE_WIDTH}&auto=format`}
            width={value.dimensions.width}
            height={value.dimensions.height}
            // Without `sizes`, the browser assumes 100vw and pulls the largest
            // candidate in the srcset for what is really a ~680px column.
            sizes={`(max-width: 768px) 100vw, ${ARTICLE_COLUMN_WIDTH}px`}
            // Empty alt marks an image decorative, the correct fallback when an
            // editor left it blank. Never fall back to the caption or filename.
            alt={value.alt ?? ''}
            className="h-auto w-full rounded-2xl border border-line"
          />
          {value.caption ? (
            <figcaption className="mt-2 text-center text-[14px] text-muted">
              {value.caption}
            </figcaption>
          ) : null}
        </figure>
      )
    },
  },
}

/** Renders an article's Portable Text body in the site's article typography. */
export default function ArticleBody({ value }: { value: Article['body'] }) {
  return <PortableText value={value} components={components} />
}
