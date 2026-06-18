import type { Metadata } from 'next'

type Props = { params: { slug: string } }

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  return { title: params.slug }
}

export default function ArticlePage({ params }: Props) {
  return null
}
