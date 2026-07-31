# Merlin's Minty Cards — Frontend

The public website and authenticated inventory tool for Merlin's Minty Cards, a
Pokémon-card business. Built with **Next.js 14 (App Router)**, **TypeScript**,
and **Tailwind CSS**, tested with **Vitest** + **Testing Library**.

> New here? Read this top to bottom once, then keep the [Project layout](#project-layout)
> and [Design system](#design-system) sections handy.

## Quick start

```bash
npm install                 # from the repo root (npm workspaces)
npm run dev --workspace=frontend     # http://localhost:3000
```

Common commands (run from `frontend/`, or add `--workspace=frontend` from root):

| Command              | What it does                                  |
|----------------------|-----------------------------------------------|
| `npm run dev`        | Start the dev server                          |
| `npm run build`      | Production build                              |
| `npm test`           | Run the Vitest suite once                     |
| `npm run test:watch` | Run tests in watch mode                       |
| `npm run lint`       | ESLint (`next/core-web-vitals`)               |

## How it fits together

This package is the **frontend only**. It talks to a separate **FastAPI backend**
(see `backend/`) for inventory data and to **Sanity** for article content. Nothing
here queries AWS directly — the backend owns that.

```
Browser ──▶ Next.js (this app) ──▶ FastAPI backend ──▶ DynamoDB / Bedrock / S3
                     └────────────▶ Sanity CMS (articles, planned)
```

### Environment variables

All are optional in development (sensible fallbacks are baked in):

| Variable                          | Used by              | Default                  |
|-----------------------------------|----------------------|--------------------------|
| `NEXT_PUBLIC_API_URL`             | `lib/api.ts`         | `http://localhost:8000`  |
| `NEXT_PUBLIC_SANITY_PROJECT_ID`   | `lib/sanity.ts`      | `''`                     |
| `NEXT_PUBLIC_SANITY_DATASET`      | `lib/sanity.ts`      | `production`             |

## Project layout

```
frontend/
├─ app/                      # Next.js App Router (routes + layouts)
│  ├─ layout.tsx             # Root layout: fonts, <html>/<body>, metadata
│  ├─ globals.css            # Tailwind entry + custom effect styles
│  ├─ (public)/              # Route group: marketing/content pages
│  │  ├─ layout.tsx          #   Navbar + Footer chrome (brand green)
│  │  ├─ page.tsx            #   Home (/)
│  │  ├─ shows/              #   /shows
│  │  ├─ about/              #   /about
│  │  ├─ dictionary/         #   /dictionary
│  │  └─ articles/           #   /articles and /articles/[slug] (SSG)
│  ├─ (auth)/                # Route group: the inventory tool
│  │  └─ inventory/          #   /inventory  (dark "vault" theme)
│  └─ api/auth/[...nextauth] # NextAuth route handler (providers TBD)
├─ components/
│  ├─ ui/                    # Reusable primitives (Button, Badge, Container…)
│  ├─ layout/                # Navbar, Footer
│  ├─ home/                  # Home-page sections (Hero, TrustStrip, …)
│  ├─ inventory/             # Inventory tool (filter + chat modes)
│  ├─ articles/              # Article list/card
│  └─ dictionary/            # Dictionary explorer
├─ hooks/                    # Custom React hooks (useCardTilt)
├─ lib/                      # Data layer + framework-free helpers
├─ sanity/schemas/           # Sanity document schemas
└─ vitest.setup.ts           # Global test setup (jsdom stubs, next/image mock)
```

### Route groups

The parenthesized folders (`(public)`, `(auth)`) are
[Next.js route groups](https://nextjs.org/docs/app/building-your-application/routing/route-groups):
they organize files and give each group its own `layout.tsx` **without** adding a
URL segment. `(public)` pages share the brand-green Navbar/Footer; `(auth)` wraps
the inventory tool. The two layouts are intentionally separate so the inventory
group can grow a real sign-in gate later (currently deferred — see
`app/(auth)/layout.tsx`).

## The data layer (`lib/`)

UI components never call `fetch` directly. They go through `lib/`, which keeps the
backend contract in one typed place:

- **`api.ts`** — `apiFetch<T>()`, the single typed wrapper around `fetch` for the
  FastAPI backend (prefixes `NEXT_PUBLIC_API_URL`, throws on non-2xx).
- **`inventory.ts`** — types + helpers for the inventory tool, modeled on the
  [pokemontcg.io v2](https://docs.pokemontcg.io/) card schema. Includes
  `searchInventory` (filter mode → `GET /inventory/search`), `getInventorySummary`
  (authenticated dashboard header stats → `GET /inventory/summary`), `sendChat`
  (chat mode → `POST /chat`), and pure helpers (`pickMarketPrice`, `formatPrice`,
  `buildSearchQuery`).
- **`public.ts`** — typed client for the backend's unauthenticated `/public/*`
  endpoints: `getPublicShows` (`GET /public/shows`, upcoming/past) and
  `getFeaturedCards` (`GET /public/featured-cards`, homepage cards). Both
  fetches opt into a 300s Next.js `revalidate` window matching the backend's
  own TTL cache, plus `isSafeImageUrl` — a client-side mirror of the backend's
  image-host allowlist so a bad catalog URL is dropped before it ever reaches
  `next/image`.
- **`articles.ts`** — article content. Currently static sample data shaped so it
  can be swapped to Sanity without touching components.
- **`collectionFocus.ts`** — pure math (`focusScale`) for the mobile
  centre-focus carousel effect, kept framework-free so it's trivially testable.

Because these helpers are plain functions, tests mock `@/lib/api` and assert on
the exact URL/body sent to the backend (see `components/inventory/__tests__`).

## Design system

Two palettes, both defined **once** in [`tailwind.config.ts`](./tailwind.config.ts):

- **Brand (light):** Spriggatito-inspired forest greens on cream/paper — used
  across the public site.
- **Vault (dark):** the `pine.*` scale — used only on `/inventory`, scoped by the
  `.vault-scope` class.

Colors live in the Tailwind config and are applied with utility classes; there are
**no parallel CSS color variables** (don't reintroduce them — that's a source of
truth split). The only runtime CSS variables are `--mouse-x` / `--mouse-y` (set
inline by the tilt + glare effects) and the `--font-*` vars from `next/font`.
Bespoke effects that can't be expressed as utilities (the 3D flip card, the
holographic glare, scroll reveals, hover lifts, the vault background) live in
[`app/globals.css`](./app/globals.css), each under a labeled comment block.

**Motion is accessible:** every effect checks `prefers-reduced-motion` (in JS via
`matchMedia` and in CSS via the media query) and falls back to a static state.

## Deploying to AWS ECS

The frontend runs as a Docker container on ECS Fargate behind the `merlins` cluster.

### Prerequisites

- AWS CLI configured with credentials for account `560151615792`
- Docker installed and running
- ECR repository `merlins-frontend` exists in `us-east-1`

### Build & Deploy

Run from the **repo root** (the Dockerfile uses repo root as build context):

```bash
# 1. Authenticate Docker with ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 560151615792.dkr.ecr.us-east-1.amazonaws.com

# 2. Build the production image
docker build -f frontend/Dockerfile --build-arg NEXT_PUBLIC_API_URL=https://me-227b5d9d4f6444e9aea830a909f923c8.ecs.us-east-1.on.aws -t 560151615792.dkr.ecr.us-east-1.amazonaws.com/merlins-frontend:latest .

# 3. Push to ECR
docker push 560151615792.dkr.ecr.us-east-1.amazonaws.com/merlins-frontend:latest

# 4. Force ECS to pull the new image
aws ecs update-service --cluster merlins --service merlins-frontend --force-new-deployment --region us-east-1
```

### Build Args (compile-time)

These are baked into the client bundle at build time:

| Arg | Value |
|-----|-------|
| `NEXT_PUBLIC_API_URL` | `https://me-227b5d9d4f6444e9aea830a909f923c8.ecs.us-east-1.on.aws` |
| `NEXT_PUBLIC_SANITY_PROJECT_ID` | Your Sanity project ID (optional) |
| `NEXT_PUBLIC_SANITY_DATASET` | `production` (default) |

### Runtime Env (on the container)

Server-side secrets are passed as ECS task definition environment variables — they are NOT in the Docker image:

- `AUTH_SECRET` — NextAuth encryption key
- `AWS_COGNITO_CLIENT_ID` / `AWS_COGNITO_CLIENT_SECRET` / `AWS_COGNITO_ISSUER` — Cognito provider
- `COGNITO_ADMIN_GROUP` — admin group name (default: `admins`)

### Deploying the backend

Same pattern from the repo root:

```bash
docker build -f backend/Dockerfile -t 560151615792.dkr.ecr.us-east-1.amazonaws.com/merlins-backend:latest .
docker push 560151615792.dkr.ecr.us-east-1.amazonaws.com/merlins-backend:latest
aws ecs update-service --cluster merlins --service merlins-backend --force-new-deployment --region us-east-1
```

## Testing

- **Runner:** Vitest in a `jsdom` environment; tests live in `__tests__/` folders
  next to the code (`include: **/__tests__/**/*.test.{ts,tsx}`).
- **Global setup:** [`vitest.setup.ts`](./vitest.setup.ts) registers jest-dom
  matchers, stubs browser APIs jsdom lacks (`matchMedia`, `IntersectionObserver`),
  and mocks `next/image` once for every test (renders a plain `<img>`).
- **What to test:** component behavior and the data-layer contract. For inventory
  components, mock `@/lib/api` and assert on the request shape rather than hitting
  a network.

This project follows **outside-in TDD** (red → green → refactor); see the repo-root
`CLAUDE.md` for the workflow.
