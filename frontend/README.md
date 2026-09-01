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
│  ├─ (admin)/               # Route group: admin panel (gated by admin session)
│  │  └─ admin/              #   /admin, /admin/inventory, /admin/sell, etc.
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

The parenthesized folders (`(public)`, `(auth)`, `(admin)`) are
[Next.js route groups](https://nextjs.org/docs/app/building-your-application/routing/route-groups):
they organize files and give each group its own `layout.tsx` **without** adding a
URL segment. `(public)` pages share the brand-green Navbar/Footer; `(auth)` wraps
the inventory tool; `(admin)` gates the admin panel behind an admin session check.
The layouts are intentionally separate so each group can enforce its own auth posture.

## The data layer (`lib/`)

UI components never call `fetch` directly. They go through `lib/`, which keeps the
backend contract in one typed place:

- **`api.ts`** — `apiFetch<T>()`, the single typed wrapper around `fetch` for the
  FastAPI backend (prefixes `NEXT_PUBLIC_API_URL`, throws on non-2xx). A **204
  No Content** resolves to `undefined` instead of throwing — gated on that
  status exactly, so a malformed empty 200 still fails loudly.
- **`inventory.ts`** — types + helpers for the inventory tool, modeled on the
  [pokemontcg.io v2](https://docs.pokemontcg.io/) card schema. Includes
  `searchInventory` (filter mode → `GET /inventory/search`), `getInventorySummary`
  (authenticated dashboard header stats → `GET /inventory/summary`), `sendChat`
  (chat mode → `POST /chat/`), and pure helpers (`pickMarketPrice`, `formatPrice`,
  `buildSearchQuery`).
- **`conversations.ts`** — typed client for the five conversation routes
  (RFC 0017): `listConversations`, `getConversation`, `renameConversation`,
  `deleteConversation`, `clearConversations`. The transcript is server-owned,
  so `sendChat` carries a `conversation_id` rather than a `history` array —
  nothing here pushes transcript content back up, and nothing should grow a
  way to. A thread the caller does not own answers **404, never 403**.
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

## Deploying to AWS

Two independent paths — **Containers (ECS Fargate)**, current production,
and **Serverless (Lambda + CloudFront)**, RFC 0014's in-progress migration
spike. See the root [`README.md`](../README.md#deploying-to-aws) for how the
two relate.

### Containers (ECS Fargate) — current production path

The frontend runs as a Docker container on ECS Fargate behind the `merlins` cluster.

#### Prerequisites

- AWS CLI configured with credentials for account `560151615792`
- Docker installed and running
- ECR repository `merlins-frontend` exists in `us-east-1`

#### Deploy Frontend

Run from the **repo root** (the Dockerfile uses repo root as build context):

```bash
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 560151615792.dkr.ecr.us-east-1.amazonaws.com
docker build -f frontend/Dockerfile --build-arg NEXT_PUBLIC_API_URL=https://me-227b5d9d4f6444e9aea830a909f923c8.ecs.us-east-1.on.aws -t 560151615792.dkr.ecr.us-east-1.amazonaws.com/merlins-frontend:latest .
docker push 560151615792.dkr.ecr.us-east-1.amazonaws.com/merlins-frontend:latest
aws ecs update-service --cluster merlins --service merlins-frontend --force-new-deployment --region us-east-1
```

#### Build Args (compile-time)

These are baked into the client bundle at build time via `--build-arg`:

| Arg | Value |
|-----|-------|
| `NEXT_PUBLIC_API_URL` | `https://me-227b5d9d4f6444e9aea830a909f923c8.ecs.us-east-1.on.aws` |
| `NEXT_PUBLIC_SANITY_PROJECT_ID` | Your Sanity project ID (optional) |
| `NEXT_PUBLIC_SANITY_DATASET` | `production` (default) |

#### Runtime Env (on the container)

Server-side secrets are passed as ECS task definition environment variables — they are NOT in the Docker image:

- `AUTH_SECRET` — NextAuth encryption key
- `AWS_COGNITO_CLIENT_ID` / `AWS_COGNITO_CLIENT_SECRET` / `AWS_COGNITO_ISSUER` — Cognito provider
- `AWS_COGNITO_DOMAIN` — Hosted UI domain (e.g. `https://<domain-prefix>.auth.<region>.amazoncognito.com`), used only for the silent access-token refresh POST to `/oauth2/token`. This is a **different host** than `AWS_COGNITO_ISSUER` — the issuer has no `/oauth2/token` route, so the refresh silently fails without this var set, and the user is signed out the first time the access token needs renewing (roughly hourly)
- `COGNITO_ADMIN_GROUP` — admin group name. **Set this explicitly; do not rely
  on the code's own fallback.** `frontend/lib/admin.ts` falls back to
  `'admins'` (plural) when unset, but the pool's actual Cognito group
  (confirmed via `aws cognito-idp list-groups`) is `admin` (singular) — the
  fallback does not match production and never has. Every real deployment
  (this container's task def, and the serverless Lambda below) sets it
  explicitly to `admin` for exactly this reason; omitting it silently
  demotes every admin to a regular user rather than erroring.

#### Infrastructure

| Resource | Value |
|----------|-------|
| AWS Account | `560151615792` |
| Region | `us-east-1` |
| ECS Cluster | `merlins` |
| Frontend Service | `merlins-frontend` |
| Frontend ECR | `560151615792.dkr.ecr.us-east-1.amazonaws.com/merlins-frontend` |
| Backend URL | `https://me-227b5d9d4f6444e9aea830a909f923c8.ecs.us-east-1.on.aws` |

### Serverless (Lambda + CloudFront) — RFC 0014 spike

Deployed via `cdk-nextjs-standalone` (the CDK stack `MerlinsFrontendStack` in
`infra/`) rather than this project's own Dockerfile — OpenNext builds the
Next.js app into a Lambda-compatible bundle, and the construct provisions the
CloudFront distribution, server Lambda, image-optimization Lambda, and ISR
revalidation queue. See the root [`README.md`](../README.md#deploying-to-aws)
for exact commands, required environment variables (same list above, read
from `infra/bin/infra.ts` instead of a task definition — `AUTH_URL` is
deliberately never set here, since `frontend/lib/auth.config.ts` sets
`trustHost: true` specifically because the CloudFront domain isn't known
until after the first deploy), and the manual Cognito-callback-URL /
backend-CORS follow-up steps that only apply on this path.

Two confirmed Windows-specific quirks in this toolchain, documented in
`infra/lib/frontend-stack.ts` and RFC 0014: the OpenNext build hangs when
invoked through `cdk`'s own nested process chain (worked around by
`skipOpenNextBuild`/`SKIP_OPENNEXT_BUILD`, see the root README), and the
image-optimization Lambda's dependency install fails with an `ENOENT
mkdtemp` error on Windows — non-blocking, since it's the server Lambda that
matters for this spike, not image optimization.

Deployed and reachable, but nothing in production points at it yet — this is
a parallel validation spike (RFC 0014 Task 6), not a cutover.

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
