# Merlin's Minty Cards — Frontend Design Foundation & Home Page

**Date:** 2026-06-19
**Scope:** The first frontend implementation pass — a reusable **design system / foundation**, the **shared Navbar + Footer**, and the **Home page** built from those primitives. Other public pages (Shows, About, Dictionary, Articles) are explicitly deferred to follow-up specs that reuse this foundation.
**Reference mockup:** [`assets/2026-06-19-home-mockup.html`](./assets/2026-06-19-home-mockup.html) — the approved, responsive HTML mockup this spec is derived from. Open it in a browser and resize to see the intended responsive behavior.

---

## 1. Goals & Decisions

Decisions locked during brainstorming:

| Decision | Choice | Rationale |
|---|---|---|
| Visual direction | **"Editorial Warmth"** | Cream canvas, generous whitespace, warm modern serif headings over clean sans body. Reads as a refined, trustworthy craft brand — "professional and clean with an interesting modern design, not overly flashy." |
| Home page primary job | **Brand story & trust** | Hero leads with who Merlin is, the buy/sell/trade promise, and card-show presence. Relationship-first, fitting a collector-run local business. |
| Mascot usage | **Accent only** | Logo in nav/footer + small touches. The site stays professional; the cat adds warmth without dominating. |
| Type pairing | **Fraunces** (display) + **Inter** (body/UI) | Fraunces is a warm, modern "old-style" serif with personality; Inter is neutral and highly legible. |
| Signature interaction | **Flippable hero card** | A Pokémon card that flips front↔back. Ties "interesting modern" to the product without flashiness. |
| Mobile priority | **First-class** | Customers use the inventory tool on phones at card shows. Mobile layouts get explicit, deliberate treatment — not an afterthought. |

**Non-goals for this pass:** auth wiring, the inventory tool UI, Sanity content, the other public pages, real photography (placeholders only), animations beyond the flip card.

---

## 2. Tech Context

- Next.js 15.3 (App Router, no `src/`), React 18, TypeScript, Tailwind CSS 3.4. Vitest + jsdom already configured.
- Fonts loaded via **`next/font/google`** (`Fraunces`, `Inter`) exposed as CSS variables on `<html>` — no external `<link>` tags, no layout shift.
- Icons via **`lucide-react`** (new dependency) — a consistent, lightweight set. No emoji in UI.
- Testing additions required: `@testing-library/react`, `@testing-library/jest-dom`, `@testing-library/user-event`, and a Vitest setup file registering jest-dom matchers + a jsdom `IntersectionObserver`/`matchMedia` stub.

---

## 3. Design Tokens

Tokens are the single source of truth. They live in `tailwind.config.ts` (Tailwind theme) and are mirrored as CSS custom properties in `globals.css` for the rare case raw CSS is needed (e.g. the flip card's 3D faces).

### 3.1 Color

Built on the existing `spriggatito` green scale (already in `tailwind.config.ts`). Add semantic aliases so components reference intent, not raw hue:

| Semantic token | Value | Maps to | Use |
|---|---|---|---|
| `forest` | `#1f6e32` | spriggatito-600 | Primary actions, links, accents |
| `forest-deep` | `#103b1c` | ~spriggatito-800 | Headings, dark bands, footer |
| `forest-mid` | `#2d8f44` | spriggatito-500 | Gradients, hovers |
| `mint` | `#a9e0b3` | spriggatito-200 | Icon strokes on dark, soft accents |
| `mint-soft` | `#d4f0d9` | spriggatito-100 | Badges, CTA band background |
| `cream` | `#f5f0e8` | (existing) | Page background |
| `paper` | `#fffdf8` | new | Alternating section background |
| `ink` | `#241f1b` | new | Body text |
| `muted` | `#6f6457` | new | Secondary text |
| `line` | `#e6ddcc` | new | Borders, dividers |

Contrast: body `ink` on `cream`, white on `forest`/`forest-deep`, and `forest` on `mint-soft` all meet WCAG AA for their text sizes. Implementers must keep AA when substituting.

### 3.2 Typography

- **Display / headings (`font-serif` → Fraunces):** h1–h3 only.
- **Body / UI (`font-sans` → Inter):** paragraphs, buttons, nav, labels, small text — **and eyebrows** (the uppercase tracked labels are sans, not serif).

Fluid type scale (clamp, min↔max):

| Role | Size | Notes |
|---|---|---|
| Hero h1 | `clamp(34px, 6.4vw, 54px)` | Fraunces 600, letter-spacing -0.01em |
| Section h2 | `clamp(26px, 4.6vw, 36px)` | Fraunces 600 |
| Card h3 | `21–24px` | Fraunces 600 |
| Lead paragraph | `clamp(16px, 2.4vw, 19px)` | Inter 400, `muted` |
| Body | `15–17px` | Inter 400 |
| Eyebrow | `13px`, uppercase, `0.16em` tracking, `forest` | **Inter** 700 (sans, not serif) |
| Small / meta | `11–13px` | Inter |

Base line-height 1.6 for body; 1.1 for headings.

### 3.3 Spacing, radius, shadow, motion

- **Container:** max-width `1140px`, horizontal padding `28px` desktop → `20px` mobile.
- **Section vertical rhythm:** `clamp(44px, 7vw, 74px)`.
- **Radius:** cards/photos `16–18px`, pills/buttons `999px`, CTA band `24px`.
- **Shadow:** soft green-tinted — e.g. `0 14px 30px rgba(16,59,28,.12)` for raised cards; deeper for the hero card.
- **Breakpoints:** `1140` (container), `900` (hero/story stack, 3→2 cols), `860` (nav → hamburger), `640` (single column, full-width CTAs, swipe strip), `380` (trust strip → 1 col). Implement as Tailwind responsive variants; the values above are the source of truth.
- **Motion:** transitions ≤ `0.8s`, eased. **All non-essential motion disabled under `prefers-reduced-motion: reduce`.**

---

## 4. Global Setup

1. **`app/layout.tsx`** — load Fraunces + Inter via `next/font/google`, attach their CSS variables to `<html>`, set `<body>` base font/color/bg. Keep existing metadata; add brand metadata (title template already present).
2. **`app/globals.css`** — keep the three `@tailwind` directives; add a `:root` block exposing the color tokens as CSS variables (for the flip card's raw-CSS 3D faces) and base element defaults.
3. **`tailwind.config.ts`** — extend `theme.colors` with the semantic aliases (§3.1), `fontFamily.serif`/`sans` to the font CSS variables, and any custom `boxShadow`/`borderRadius` tokens. Keep the existing `spriggatito` scale and `cream`.

---

## 5. Component Architecture

Each component is small, single-purpose, independently testable, and lives where the repo's scaffold already expects it (`components/ui`, `components/layout`, plus a new `components/home`).

### 5.1 UI primitives — `components/ui/`

| Component | Responsibility | Key props / behavior |
|---|---|---|
| `Button` | Pill button/link | `variant: 'primary' \| 'ghost'`; renders `<a>` when `href` given (Next `Link`), else `<button>`; forwards `className`, children. |
| `Container` | Centered max-width wrapper | wraps children, applies container width + responsive padding. |
| `Eyebrow` | Uppercase tracked label | children; `forest` colored. |
| `SectionHeading` | Eyebrow + h2 + optional subtitle | `eyebrow`, `title`, `subtitle?`. |
| `Badge` | Pill tag (Buy/Sell/Trade) | children; mint-soft background. |

### 5.2 Layout — `components/layout/`

| Component | Responsibility | Key behavior |
|---|---|---|
| `Navbar` | Sticky top nav | Brand (cat logo + wordmark) → `/`; links Shows/About/Dictionary/Articles; pinned **Inventory** primary button → `/inventory`. Below `860px`: links collapse into a **hamburger-toggled** menu; Inventory button stays in the bar; wordmark stays on one line. Menu is keyboard-operable, closes on Escape and on link click, `aria-expanded` reflects state. |
| `Footer` | Site footer (deep-green) | Brand blurb; columns **Explore / Collect / Follow**; Instagram + Contact; copyright + Privacy/Terms. Columns reflow 4→2→1 responsively. |
| `MobileMenu` | (May be internal to Navbar) | The collapsible link panel; extracted only if it clarifies the Navbar. |

The shared layout (`app/(public)/layout.tsx`) renders `Navbar` + `children` + `Footer`.

### 5.3 Home sections — `components/home/`

Composed in order by `app/(public)/page.tsx`:

1. `Hero` — eyebrow, h1, lead, two CTAs (`Read our story` → `/about`, `See upcoming shows` → `/shows`), and `FlipCard` on the right. Stacks below `900px` with the card moving above the text.
2. `TrustStrip` — deep-green band, 4 items (icon + heading + sub). Each item is a **uniform-width, centered unit** so icons align on a consistent grid with balanced margins; row has `padding: 26px 16px`. Reflows 4→2→1 cols.
3. `StoryTeaser` — photo + "It started with one binder." narrative → `/about`.
4. `BuySellTrade` — three `Badge`-topped cards (Buy / Sell / Trade).
5. `FeaturedFinds` — "A peek at the collection" card strip → `/inventory`; becomes a horizontal **swipe** strip on mobile. Notes inventory is login-gated.
6. `ShowsPreview` — next-show card → `/shows`.
7. `LearnHub` — two tiles: Articles & guides → `/articles`, Collectors Dictionary → `/dictionary`.
8. `FinalCTA` — mint-soft band, "Let's find your card." → contact.

### 5.4 `FlipCard` — `components/ui/FlipCard.tsx` (the signature interaction)

The most behavior-rich component; its requirements are explicit:

- **Structure:** a **stable, non-transformed wrapper** (the perspective/hit target) containing an inner element that rotates `rotateY(180deg)`. Two faces (`front`, `back`), each `backface-visibility:hidden`.
- **Anti-shake (hard requirement):** hover/pointer handling binds to the **wrapper**, never the rotating element — the hitbox must not move during the flip. This was the specific bug to avoid.
- **Desktop:** flip on hover, gated by `@media (hover:hover) and (pointer:fine)` so touch devices never get a stuck hover state.
- **Touch:** flip on **tap** (class toggle), with a visible "👆 Tap to flip" hint at mobile widths (the pointer-finger emoji is intentionally retained here — it is the one allowed emoji).
- **Scroll-peek:** a one-time flip→back→front "wink" when the card first scrolls into view (IntersectionObserver), signaling interactivity.
- **Reduced motion:** under `prefers-reduced-motion: reduce`, disable the transition and skip the auto scroll-peek; manual flip still works.
- **Accessibility:** focusable, operable by keyboard (Enter/Space toggles), with an `aria-label` describing front/back; faces' decorative content hidden from AT as appropriate.
- **Content:** `front` = a real graded-card image (placeholder for now); `back` = the classic Pokémon card-back image (placeholder for now). Accepts `frontImage`/`backImage` (or children) so real assets drop in without code changes.

---

## 6. Image / Asset Manifest

Real assets present are used; everything else is a **labeled placeholder component** (`<ImagePlaceholder label="…" />`) rendering a tasteful colored block with the note of what belongs there, so gaps are obvious and swap-in is trivial.

| Slot | Asset | Status |
|---|---|---|
| Nav + footer logo | `images/logo/Merlin's Minty Cards Just the Cat Transparent Background.png` | **Have** — use real |
| Story photo | `images/about-us/childhood-card-collection.webp` | **Have** — use real |
| Flip card front | a graded card, e.g. `images/cards/laprassouthern.webp` | **Have** — use real |
| Flip card back | classic Pokémon card back | **Placeholder** — needs real back image |
| Featured finds (×5) | inventory card images via CloudFront | **Placeholder** — note CloudFront source |
| Shows preview image | a card-show photo | **Placeholder** — `images/shows/` is empty |
| Open Graph / social | brand OG image | **Placeholder** — note for later |

A short "Images needed" list is surfaced in the implementation report so the owner knows exactly what to provide.

---

## 7. Testing Strategy (Outside-In TDD)

Per `CLAUDE.md`, every behavioral unit is built RED → GREEN → REFACTOR. Tests describe **behavior**, not styling internals (we do not assert exact pixel values or class strings; we assert structure, content, roles, links, and interaction outcomes).

**Outside-in order** — start at the page, drive inward:

1. **Home page (outer):** renders the brand wordmark, all section headings, and CTAs pointing to the right routes (`/about`, `/shows`, `/inventory`, `/articles`, `/dictionary`). This fails first and stays red until the sections exist.
2. **Navbar:** renders links with correct `href`s + Inventory CTA; hamburger toggles the menu (`aria-expanded` flips, links appear/hide); Escape closes it.
3. **Footer:** renders the three column groups, Instagram/Contact, and copyright.
4. **Button:** renders a `<button>` by default and an anchor with the right `href` when `href` is passed; applies variant.
5. **FlipCard:** renders both faces; a click/Enter toggles the flipped state (assert via `aria` / data-state, not the transform); exposes an accessible label; does **not** throw when `IntersectionObserver`/`matchMedia` are stubbed; respects a reduced-motion stub (no auto-peek state change).
6. **SectionHeading / Badge / Eyebrow / Container:** render their content and children.

**Harness notes the plan must cover:** add Testing Library + a Vitest `setup.ts` that registers `@testing-library/jest-dom` and stubs `matchMedia` and `IntersectionObserver` (absent in jsdom). Keep `--passWithNoTests` until the first real test lands.

Verification gates before "done": `npm test --workspace=frontend`, `cd frontend && npm run lint`, and `next build` all green.

---

## 8. File Plan (additions)

```
frontend/
├── app/
│   ├── layout.tsx                 # + next/font (Fraunces, Inter), body base
│   ├── globals.css                # + token CSS vars, base defaults
│   └── (public)/
│       ├── layout.tsx             # Navbar + children + Footer
│       └── page.tsx               # composes Home sections
├── components/
│   ├── ui/
│   │   ├── Button.tsx
│   │   ├── Container.tsx
│   │   ├── Eyebrow.tsx
│   │   ├── SectionHeading.tsx
│   │   ├── Badge.tsx
│   │   ├── ImagePlaceholder.tsx
│   │   └── FlipCard.tsx
│   ├── layout/
│   │   ├── Navbar.tsx
│   │   └── Footer.tsx
│   └── home/
│       ├── Hero.tsx
│       ├── TrustStrip.tsx
│       ├── StoryTeaser.tsx
│       ├── BuySellTrade.tsx
│       ├── FeaturedFinds.tsx
│       ├── ShowsPreview.tsx
│       ├── LearnHub.tsx
│       └── FinalCTA.tsx
├── tailwind.config.ts             # + semantic color tokens, font families
├── vitest.config.ts               # + setupFiles: ['./vitest.setup.ts']
├── vitest.setup.ts                # jest-dom + matchMedia/IntersectionObserver stubs
└── package.json                   # + lucide-react, @testing-library/*
```

Plus `__tests__` (or co-located `*.test.tsx`) files per component, written before their implementation.

---

## 9. Open Questions / Assumptions

- **Assumed** the contact CTA links to an `/about#contact` anchor (no contact page in scope yet). Revisit when About is built.
- **Assumed** Instagram is the only live social link (TikTok not yet created, per repo setup spec).
- **Assumed** featured-finds images will eventually come from CloudFront; for now they are placeholders and the strip is static.
