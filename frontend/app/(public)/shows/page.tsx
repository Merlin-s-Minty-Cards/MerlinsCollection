import type { Metadata } from 'next'
import Link from 'next/link'
import Container from '@/components/ui/Container'
import Eyebrow from '@/components/ui/Eyebrow'
import Reveal from '@/components/ui/Reveal'

export const metadata: Metadata = { title: 'Shows' }

// Shows are sourced from the business's own records (DynamoDB SHOWLIST, imported
// from the vending-tracker spreadsheet). Those records carry only a show's name
// and date — there is no venue, time, or street address in the data — so we show
// exactly that and no invented details. Dates spanning multiple days use the
// first day for the calendar badge.
type Show = {
  month: string
  day: string
  title: string
  city: string
  dates: string
}

const upcoming: Show[] = [
  { month: 'JUL', day: '25', title: 'Lloyd Center, Portland', city: 'Portland, OR', dates: 'Jul 25, 2026' },
  { month: 'AUG', day: '14', title: 'Seattle Trading Card Con', city: 'Seattle, WA', dates: 'Aug 14–16, 2026' },
]

const past: Show[] = [
  { month: 'JUL', day: '18', title: 'Lloyd Center, Portland', city: 'Portland, OR', dates: 'Jul 18, 2026' },
  { month: 'JUL', day: '04', title: 'Lloyd Center, Portland', city: 'Portland, OR', dates: 'Jul 4, 2026' },
  { month: 'JUN', day: '13', title: 'Front Row Portland', city: 'Portland, OR', dates: 'Jun 13–14, 2026' },
  { month: 'JUN', day: '06', title: 'Lloyd Center, Portland', city: 'Portland, OR', dates: 'Jun 6, 2026' },
  { month: 'MAY', day: '29', title: 'TCG Con Portland', city: 'Portland, OR', dates: 'May 29–31, 2026' },
]

function DateBadge({ month, day, past }: { month: string; day: string; past?: boolean }) {
  return (
    <div
      className={`flex w-[74px] shrink-0 flex-col items-center justify-center rounded-[14px] py-2 text-white ${
        past ? 'bg-forest-deep' : 'bg-forest shadow-[0_10px_24px_rgba(31,110,50,0.25)]'
      }`}
    >
      <b className="font-serif text-[23px] leading-none">{month}</b>
      <span className="text-[12px] uppercase tracking-[0.08em]">{day}</span>
    </div>
  )
}

function ShowRow({ show, past }: { show: Show; past?: boolean }) {
  return (
    <div
      className={`flex flex-wrap items-center gap-5 rounded-2xl border border-line px-6 py-5 ${
        past ? 'bg-cream' : 'bg-cream hover-lift hover:border-mint hover:shadow-card'
      }`}
    >
      <DateBadge month={show.month} day={show.day} past={past} />
      <div className="min-w-[180px] flex-1">
        <h3 className="font-serif text-[20px] font-semibold text-forest-deep">{show.title}</h3>
        <div className="mt-0.5 text-[15px] text-muted">{show.city}</div>
      </div>
      <div className="font-sans text-[14px] font-semibold uppercase tracking-[0.06em] text-forest">
        {show.dates}
      </div>
    </div>
  )
}

export default function ShowsPage() {
  return (
    <>
      <section className="py-[clamp(48px,8vw,84px)]">
        <Container>
          <Reveal>
            <Eyebrow>In person</Eyebrow>
            <h1 className="mt-3 max-w-[16ch] font-serif text-[clamp(34px,6.4vw,52px)] font-semibold leading-[1.05] tracking-[-0.01em] text-forest-deep">
              Catch us at a card show.
            </h1>
            <p className="mt-4 max-w-[52ch] text-[clamp(16px,2.4vw,19px)] text-[#4a4339]">
              We pack the cases and hit the road most weekends. Come dig through the binders, talk
              cards, and say hi to the crew. Here&apos;s where we&apos;re headed next.
            </p>
          </Reveal>
        </Container>
      </section>

      <Container className="pb-[clamp(48px,8vw,84px)]">
        <section>
          <Reveal>
            <h2 className="mb-5 font-serif text-[clamp(24px,4vw,32px)] font-semibold text-forest-deep">
              Upcoming shows
            </h2>
          </Reveal>
          <div className="space-y-4">
            {upcoming.map((show, i) => (
              <Reveal key={`${show.month}-${show.day}-${show.title}`} delay={i * 80}>
                <ShowRow show={show} />
              </Reveal>
            ))}
          </div>
        </section>

        <section className="mt-14">
          <Reveal>
            <h2 className="mb-5 font-serif text-[clamp(24px,4vw,32px)] font-semibold text-forest-deep">
              Past shows
            </h2>
          </Reveal>
          <div className="space-y-4">
            {past.map((show, i) => (
              <Reveal key={`${show.month}-${show.day}-${show.title}`} delay={i * 80}>
                <ShowRow show={show} past />
              </Reveal>
            ))}
          </div>
        </section>

        <Reveal>
          <div className="mt-14 flex flex-col items-start gap-4 rounded-3xl bg-forest px-7 py-8 text-white sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className="font-serif text-[24px] font-semibold text-white">Running an event?</h2>
              <p className="mt-1 max-w-[46ch] text-[#eaf6ec]">
                We love setting up at new shows. Tell us about yours and we&apos;ll bring a table.
              </p>
            </div>
            <Link
              href="/about#contact"
              className="shrink-0 rounded-full bg-white px-6 py-3 font-semibold text-forest transition-transform hover:-translate-y-0.5 hover:bg-cream"
            >
              Get in touch
            </Link>
          </div>
        </Reveal>
      </Container>
    </>
  )
}
