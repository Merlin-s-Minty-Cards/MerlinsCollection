import Container from '@/components/ui/Container'
import SectionHeading from '@/components/ui/SectionHeading'
import Button from '@/components/ui/Button'
import Reveal from '@/components/ui/Reveal'

// Next upcoming show, sourced from the business's own show data (DynamoDB
// SHOWLIST / the vending-tracker spreadsheet). The spreadsheet records only a
// show's name and date — no venue, time, or street address — so we surface only
// what the data actually contains rather than inventing details. Keep this in
// sync with the /shows page (the source of truth for the full schedule).
export default function ShowsPreview() {
  return (
    <section className="bg-paper py-[clamp(44px,7vw,74px)]">
      <Container>
        <Reveal>
          <SectionHeading
            eyebrow="In person"
            title="Catch us at a card show."
            subtitle="Come find us in person at a show. Here is where we are headed to next:"
          />
        </Reveal>
        <Reveal delay={80}>
          <div className="flex flex-wrap gap-5 items-center bg-cream border border-line rounded-2xl px-6 py-5 hover-lift">
            <div className="flex flex-col items-center justify-center w-[74px] h-[74px] rounded-[14px] bg-forest text-white shrink-0">
              <b className="font-serif text-[23px] leading-none">AUG</b>
              <span className="text-[12px] uppercase tracking-[0.08em]">14</span>
            </div>
            <div className="flex-1 min-w-[160px]">
              <h3 className="font-serif font-semibold text-forest-deep text-[20px] mb-1">
                Seattle Trading Card Con
              </h3>
              <div className="text-muted text-[15px]">Seattle, WA · Aug 14–16, 2026</div>
            </div>
            <Button href="/shows" variant="ghost">
              All shows
            </Button>
          </div>
        </Reveal>
      </Container>
    </section>
  )
}
