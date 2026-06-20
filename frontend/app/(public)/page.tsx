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
