# Design: Next.js 15 All-at-once Dependency Upgrade

**Date:** 2026-06-18
**Status:** Approved
**Goal:** Resolve 32 npm security vulnerabilities by upgrading Next.js 14 → 15, next-auth v4 → v5, and associated dependencies in a single pass.

---

## Context

The frontend (`frontend/`) is an early scaffold on Next.js 14 with App Router. Most pages are stubs; auth is an empty config; no tests exist yet. The low code volume makes a combined upgrade cheap.

Vulnerabilities addressed:
- `next` — HTTP request smuggling (GHSA-ggv3-7p47-pfv8), cache poisoning (GHSA-3g8h-86w9-wvmq), and others
- `postcss` (nested in Next.js) — XSS via unescaped `</style>` (GHSA-qx2v-qp2m-jg93)
- `eslint-config-next` / `glob` — CLI command injection (GHSA-5j98-mcp5-4vw2)
- `uuid` / `next-auth` — buffer bounds check (GHSA-w5hq-g745-h8pq)
- `esbuild` / `vitest` — dev server CORS bypass (GHSA-67mh-4wv8-2f99)
- `js-yaml`, `prismjs` — safe-fixable via `npm audit fix`

---

## Package Version Bumps

| Package | From | To |
|---|---|---|
| `next` | ^14.2.0 | ^15.3.0 |
| `next-auth` | ^4.24.0 | ^5.0.0 |
| `eslint-config-next` | ^14.2.0 | ^15.3.0 |
| `vitest` | ^2.0.0 | ^3.0.0 |
| `@vitest/coverage-v8` | ^2.0.0 | ^3.0.0 |

After bumping versions, run `npm audit fix` to pick up the safe patches for `js-yaml` and `prismjs`.

---

## next-auth v4 → v5 (Auth.js) Migration

### `lib/auth.ts`

Replace the v4 `authOptions` export with the v5 pattern: a single file that calls `NextAuth()` and exports `{ handlers, auth, signIn, signOut }`.

```ts
import NextAuth from 'next-auth'
import type { NextAuthConfig } from 'next-auth'

export const config: NextAuthConfig = {
  providers: [],
  callbacks: {},
}

export const { handlers, auth, signIn, signOut } = NextAuth(config)
```

### `app/api/auth/[...nextauth]/route.ts`

Replace the v4 handler pattern with the v5 `handlers` re-export:

```ts
import { handlers } from '@/lib/auth'
export const { GET, POST } = handlers
```

No other files reference `authOptions`, so this is the complete migration scope.

---

## Next.js 15 Breaking Changes

**Async request APIs:** `cookies()`, `headers()`, `params`, and `searchParams` are now async in Next.js 15. None are currently used in the codebase, so no page/layout changes are needed now. Future code must `await` these.

**Fetch caching:** `fetch` is no longer cached by default in Next.js 15. No data fetching exists yet, so no impact now. When Sanity fetches are added, use `cache: 'force-cache'` or `next: { revalidate }` explicitly if caching is desired.

**`next.config.ts`:** Only `images.remotePatterns` is configured — unchanged in v15.

---

## Verification Checklist

1. `npm install` — resolves new lockfile cleanly
2. `npm run build` — no TypeScript or compile errors
3. `npm run lint` — eslint-config-next v15 passes
4. `npm test` — vitest v3 runs (zero tests currently, should exit cleanly)
5. `npm audit` — vulnerability count drops to near zero

---

## Out of Scope

- Implementing Cognito providers in next-auth v5 (separate task)
- Upgrading `next-sanity` beyond current v9.4.0 (compatible with Next.js 15, no change needed)
- Upgrading React 18 → 19 (Next.js 15 supports both; stay on 18 for now)
