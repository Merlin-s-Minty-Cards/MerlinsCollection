import Container from '@/components/ui/Container'
import Reveal from '@/components/ui/Reveal'
import { Award, Tag, Users, MapPin } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

const items: { Icon: LucideIcon; title: string; sub: string }[] = [
  { Icon: Award, title: 'Raw & graded', sub: 'Loose singles to PSA, BGS, and CGC slabs.' },
  { Icon: Tag, title: 'Fair prices', sub: 'Set off real recent sales, not wishlist numbers.' },
  { Icon: Users, title: 'We collect too', sub: 'Just college kids who never quit Pokémon.' },
  { Icon: MapPin, title: 'At the shows', sub: 'Come find our table and say hi.' },
]

export default function TrustStrip() {
  return (
    <div className="bg-forest-deep text-[#eaf6ec]">
      <Container>
        <div className="grid grid-cols-1 xs:grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-[18px] sm:gap-[22px] px-4 py-[26px]">
          {items.map(({ Icon, title, sub }, i) => (
            <Reveal
              key={title}
              delay={i * 70}
              className="flex gap-3 items-start justify-center group"
            >
              <span className="shrink-0 flex items-center justify-center">
                <Icon
                  className="w-6 h-6 text-mint transition-transform group-hover:scale-110"
                  strokeWidth={1.8}
                />
              </span>
              <div className="grow-0 shrink basis-[170px]">
                <h4 className="font-sans font-bold text-[15px] text-white">{title}</h4>
                <p className="text-[13px] text-[#aecbb4]">{sub}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </Container>
    </div>
  )
}
