// Sanity article schema — the shape of the editing form in the Studio.
// Each field here becomes an input the business can fill in at /studio.
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
    { name: 'body', title: 'Body', type: 'array', of: [{ type: 'block' }] },
  ],
}

export default article
