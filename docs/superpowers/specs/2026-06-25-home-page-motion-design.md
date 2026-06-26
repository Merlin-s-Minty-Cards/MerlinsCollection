# Home Page Motion & Interactivity — Design

**Date:** 2026-06-25
**Status:** Approved (pending spec review)

## Problem

The top of the home page is lively — the Hero `FlipCard` (3D tilt, holographic
glare, flip, auto-peek on view) and the `FeaturedFinds` `CollectionRow` (cursor
tilt, glare, mobile centre-focus scaling) have real personality. Everything
below the fold then goes flat: `TrustStrip`, `StoryTeaser`, `BuySellTrade`,
`ShowsPreview`, `LearnHub`, and `FinalCTA` are static, with at most a tiny
`hover:-translate-y-0.5`. The page reads as "alive, then dead."

## Goal

Make the whole page feel a little more alive and interactive — in the same
visual language already established — **without** redesigning anything. Refined
and subtle: gentle entrances and tasteful hover states, nothing flashy.

## Non-goals

- No layout, copy, or color changes.
- No new dependencies (no Framer Motion). Animations stay hand-rolled with CSS +
  small hooks/components, matching the existing pattern.
- No changes to the already-rich Hero `FlipCard` or `FeaturedFinds` card tilt.
- No parallax, idle float, count-up counters, or holo shine sweeps (those were
  the "playful" option; we chose "refined").

## Constraints

- Every effect must be gated behind `prefers-reduced-motion: reduce` — reveals
  show instantly, hover transforms are disabled.
- Must degrade safely where `IntersectionObserver` is unavailable (SSR / jsdom):
  content renders fully visible, never stuck hidden.
- Existing tests must stay green (`Hero.test.tsx`, `sections-mid.test.tsx`,
  `sections-bottom.test.tsx`, `page.test.tsx`).
- Follow outside-in TDD per `CLAUDE.md` (RED → GREEN → REFACTOR).

## Design

### 1. New primitive: `<Reveal>`

`frontend/components/ui/Reveal.tsx` (client component).

Wraps children and animates them from hidden (opacity 0, `translateY(16px)`) to
shown (opacity 1, no transform) when they scroll into view, using
`IntersectionObserver` — the same approach as `FlipCard`'s peek effect.

- **Props:**
  - `children: ReactNode`
  - `delay?: number` — ms before the reveal transition starts, for stagger.
  - `as?: keyof JSX.IntrinsicElements` — element tag (default `div`), so it can
    wrap grids without adding stray wrappers that break layout.
  - `className?: string` — merged onto the element.
- **Behavior:**
  - On mount: if `prefers-reduced-motion` is set, or `IntersectionObserver` is
    undefined, render in the revealed state immediately.
  - Otherwise start hidden; when ≥ ~20% of the element is visible, switch to the
    revealed state once (then unobserve).
  - `delay` applied via inline `transition-delay`.
- **Styling** (in `globals.css`):
  - `.reveal { opacity: 0; transform: translateY(16px); transition: opacity .6s
    ease, transform .6s cubic-bezier(0.2,0.8,0.2,1); }`
  - `.reveal-in { opacity: 1; transform: none; }`
  - `@media (prefers-reduced-motion: reduce) { .reveal { opacity: 1; transform:
    none; transition: none; } }`

### 2. Apply scroll-reveal to the static sections

Wrap section content in `<Reveal>`:

- `TrustStrip` — the four items stagger in (~70ms apart) on reveal.
- `StoryTeaser` — image and text column fade up.
- `BuySellTrade` — heading reveals; the three cards stagger.
- `FeaturedFinds` — heading reveals; the row reveals (card tilt unchanged).
- `ShowsPreview` — heading + listing row fade up.
- `LearnHub` — heading reveals; the two panels stagger.
- `FinalCTA` — the panel fades up.

No layout or copy changes — only wrapper elements that default to visible.

### 3. Refined hover upgrades (reuse existing card language)

- **BuySellTrade cards** — replace the tiny lift with a softer lift + warmer
  border/shadow on hover; badge gets a subtle accent. Gated to hover/fine
  pointers; disabled under reduced motion.
- **LearnHub panels** — lift on hover plus a `→` arrow that slides in,
  reinforcing that they are links.
- **ShowsPreview** — date chip + row lift gently together on hover.
- **TrustStrip** — icons get a slight scale on hover (in addition to the
  staggered reveal).
- **Button** (`components/ui/Button.tsx`) — add a small hover lift + shadow-grow
  on `primary`, a subtle fill on `ghost` (today they only animate on `:active`).

### 4. Hero

Leave the `FlipCard` exactly as-is. Add only a fade-up `<Reveal>` on the text
column so it enters with the same rhythm as the rest of the page. No other Hero
changes.

## Testing strategy (outside-in TDD)

The eased visuals themselves aren't unit-testable, but the structure and
fallbacks are:

- **`Reveal` component:**
  - Renders its children.
  - When `IntersectionObserver` is unavailable (jsdom default), children render
    in the revealed state (not hidden).
  - Honors the `as` prop (renders the requested tag) and merges `className`.
- **Sections:** each updated section still renders its existing content
  (existing tests) and now renders through a reveal wrapper (assert presence of
  the reveal class / wrapper where it doesn't conflict with existing queries).
- **Reduced motion / no-IO safety:** assert content is visible without relying
  on an IntersectionObserver callback firing.

Existing section/page tests must continue to pass unchanged.

## Rollback

Each effect is additive and isolated (a wrapper or a hover class). Anything that
feels like "too much" can be removed independently without touching the rest.
