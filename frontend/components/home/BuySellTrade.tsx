import Container from '@/components/ui/Container'
import SectionHeading from '@/components/ui/SectionHeading'
import Badge from '@/components/ui/Badge'
import Reveal from '@/components/ui/Reveal'

const cards: { badge: string; title: string; body: string }[] = [
  {
    badge: 'Buy',
    title: 'Find your next card',
    body: 'Come look through our collection; we have everything from cheap singles to PSA slabs. If you are looking for something specific, we can check if we have it.',
  },
  {
    badge: 'Sell',
    title: 'Cash in your collection',
    body: 'Bring your cards to the table, and Merlin will appraise them.',
  },
  {
    badge: 'Trade',
    title: 'Tired of your old cards?',
    body: 'We are always open to trades of any price or amount. Come stop by, and we will take a look.',
  },
]

export default function BuySellTrade() {
  return (
    <section className="bg-paper py-[clamp(44px,7vw,74px)]">
      <Container>
        <SectionHeading
          eyebrow="What we do"
          title="Three reasons to stop by our table."
          subtitle="Whether you're buying your first card or moving a whole collection, come say hi."
        />
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-5">
          {cards.map((c, i) => (
            <Reveal key={c.badge} delay={i * 80}>
              <div className="h-full bg-cream border border-line rounded-2xl p-[26px] hover-lift hover:border-mint hover:shadow-card-lg">
                <Badge>{c.badge}</Badge>
                <h3 className="font-serif font-semibold text-forest-deep text-[21px] mt-3.5 mb-2">
                  {c.title}
                </h3>
                <p className="text-muted text-[15px]">{c.body}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </Container>
    </section>
  )
}
