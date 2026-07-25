// Sanity article schema — the shape of the editing form in the Studio.
// Each field here becomes an input the business can fill in at /studio.

type Rule = { required: () => unknown; uri: (opts: { scheme: string[] }) => unknown }

/** An image an editor drops into the body, with the metadata that makes it usable. */
const inlineImage = {
  type: 'image',
  fields: [
    {
      name: 'alt',
      title: 'Alt text',
      type: 'string',
      description: 'Describe the image for screen readers and when it fails to load.',
      // Required: skipped alt text is both an accessibility failure and a lint
      // error at build time.
      validation: (rule: Rule) => rule.required(),
    },
    {
      name: 'caption',
      title: 'Caption',
      type: 'string',
      description: 'Optional. Shown underneath the image.',
    },
  ],
}

const article = {
  name: 'article',
  title: 'Article',
  type: 'document' as const,
  fields: [
    { name: 'title', title: 'Title', type: 'string' },
    { name: 'slug', title: 'Slug', type: 'slug', options: { source: 'title' } },
    { name: 'excerpt', title: 'Excerpt', type: 'text', rows: 3 },
    { name: 'publishedAt', title: 'Published At', type: 'datetime' },
    { name: 'readingTime', title: 'Reading Time', type: 'string' },
    { name: 'category', title: 'Category', type: 'string' },
    { name: 'body', title: 'Body', type: 'array', of: [{ type: 'block' }, inlineImage] },

    {
      name: 'seoDescription',
      title: 'SEO description',
      type: 'text',
      rows: 2,
      description:
        'Shown in Google results and link previews. Falls back to the excerpt if left blank.',
    },
    {
      name: 'shareImage',
      title: 'Social share image',
      type: 'image',
      description: 'Shown when the article is shared. Looks best at 1200×630.',
    },
    {
      name: 'cta',
      title: 'Call to action',
      type: 'object',
      description: 'Optional button shown at the end of the article.',
      fields: [
        { name: 'label', title: 'Button label', type: 'string' },
        {
          name: 'href',
          title: 'Button link',
          type: 'url',
          validation: (rule: Rule) => rule.uri({ scheme: ['http', 'https', 'mailto', 'tel'] }),
        },
      ],
    },
  ],
}

export default article
