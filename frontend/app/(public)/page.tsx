import type { Metadata } from 'next'
import Hero from '@/components/home/Hero'
import TrustStrip from '@/components/home/TrustStrip'
import StoryTeaser from '@/components/home/StoryTeaser'
import BuySellTrade from '@/components/home/BuySellTrade'
import FeaturedFinds from '@/components/home/FeaturedFinds'
import ShowsPreview from '@/components/home/ShowsPreview'
import LearnHub from '@/components/home/LearnHub'
import FinalCTA from '@/components/home/FinalCTA'

export const metadata: Metadata = { title: 'Home' }

/**
 * Match `/shows` (300) and `/articles` (60): declare the ISR window on the
 * PAGE, not only on the fetch inside `FeaturedFinds`.
 *
 * Without this the homepage's freshness depended on `getFeaturedCards`'
 * `next: { revalidate: 300 }` actually running at build time. When that fetch
 * throws instead — which it now correctly does whenever the backend base URL
 * is an unsubstituted build-time placeholder, see lib/api-base.ts — Next
 * observes no revalidating fetch, treats the page as fully static, and emits
 * `cache-control: s-maxage=31536000`. CloudFront then pins the build-time
 * FALLBACK content at the edge for a year, and no amount of ISR at the origin
 * ever dislodges it. Measured live 2026-08-26: `/shows` and `/articles`
 * self-healed within ~2 minutes of a deploy while `/` was still serving
 * placeholder cards 12 minutes later.
 *
 * A page's cache policy must not be a side effect of whether a fetch inside it
 * happened to succeed.
 */
export const revalidate = 300

export default function HomePage() {
  return (
    <>
      <Hero />
      <TrustStrip />
      <StoryTeaser />
      <BuySellTrade />
      <FeaturedFinds />
      <ShowsPreview />
      <LearnHub />
      <FinalCTA />
    </>
  )
}
