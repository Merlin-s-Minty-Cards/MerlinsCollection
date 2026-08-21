import Container from '@/components/ui/Container'
import SectionHeading from '@/components/ui/SectionHeading'
import Button from '@/components/ui/Button'
import CollectionRow from '@/components/home/CollectionRow'
import Reveal from '@/components/ui/Reveal'
import { getFeaturedCards, isSafeImageUrl } from '@/lib/public'

// Static fallback set (bundled webp). Rendered ONLY when the backend returns zero
// cards or the fetch fails — the homepage must never show empty or broken tiles.
// This is the expected state today: ~93% of available items have card_id=NULL, so
// /public/featured-cards legitimately returns [] until the catalog match improves.
const staticFeatured: { src: string; alt: string }[] = [
  { src: '/images/cards/laprassouthern.webp', alt: 'Lapras — Southern Islands' },
  { src: '/images/cards/Lugia.webp', alt: 'Lugia' },
  { src: '/images/cards/M_Metagross.webp', alt: 'Mega Metagross' },
  { src: '/images/cards/slowking.webp', alt: 'Slowking' },
]

// Show five static cards, cycling the source images.
const staticCards = Array.from({ length: 5 }, (_, i) => staticFeatured[i % staticFeatured.length])

export default async function FeaturedFinds() {
  // Server-fetch the real featured cards (ISR: see getFeaturedCards' revalidate).
  // On ANY error, fall through to the static set — the section always renders.
  let liveCards: { src: string; alt: string }[] = []
  try {
    const { cards } = await getFeaturedCards()
    // Guard the render: drop any card whose image would throw inside next/image
    // (non-allowlisted host / non-https / malformed). The backend already filters
    // these, but this second layer means one bad URL can never 500 the home page.
    liveCards = cards
      .filter((c) => isSafeImageUrl(c.image_url))
      .map((c) => ({ src: c.image_url, alt: c.name }))
  } catch {
    liveCards = []
  }

  // All-or-nothing static fallback: only on zero/error. 1–4 real cards render as
  // those N tiles (no static padding) — real and placeholder are never blended.
  const cards = liveCards.length > 0 ? liveCards : staticCards

  return (
    <section className="py-[clamp(44px,7vw,74px)]">
      <Container>
        <Reveal>
          <SectionHeading
            eyebrow="From the case"
            title="A peek at the collection."
            subtitle="Some of our favorites. Sign in to search the full inventory by set, condition, and price!"
          />
        </Reveal>
        <Reveal delay={80}>
          <CollectionRow cards={cards} />
        </Reveal>
        <Reveal delay={140} className="mt-[22px]">
          <Button href="/inventory">Explore the inventory →</Button>
        </Reveal>
      </Container>
    </section>
  )
}
