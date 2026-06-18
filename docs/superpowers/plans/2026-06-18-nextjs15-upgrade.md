# Next.js 15 Dependency Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade Next.js 14 → 15, next-auth v4 → v5, and associated dev dependencies to resolve 32 npm security vulnerabilities.

**Architecture:** Three sequential tasks — bump package versions and install, migrate the next-auth v5 API surface (two files), then run safe audit patches. Each task ends with a passing build and a commit.

**Tech Stack:** Next.js 15, Auth.js (next-auth v5), vitest v3, TypeScript 5, Tailwind CSS 3, pnpm/npm workspace at `frontend/`.

## Global Constraints

- All commands run from `frontend/` unless stated otherwise.
- React stays on v18 (do not upgrade to v19).
- `next-sanity` stays at current version (^9.4.0) — compatible with Next.js 15, no change needed.
- Do not implement Cognito providers — `providers: []` stays empty; that is a separate task.
- Next.js 15 makes `cookies()`, `headers()`, `params`, and `searchParams` async — no current code uses these, so no page changes are needed. Leave a comment in `lib/auth.ts` for future reference.

---

### Task 1: Bump package versions and install

**Files:**
- Modify: `frontend/package.json`

**Interfaces:**
- Produces: Updated `package.json` with new version ranges; clean `node_modules` and `package-lock.json`.

- [ ] **Step 1: Update `frontend/package.json` version ranges**

Replace the `dependencies` and `devDependencies` blocks so they read exactly:

```json
{
  "name": "@merlins-collection/frontend",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "lint": "next lint",
    "test": "vitest run",
    "test:watch": "vitest",
    "test:coverage": "vitest run --coverage"
  },
  "dependencies": {
    "next": "^15.3.0",
    "react": "^18.3.0",
    "react-dom": "^18.3.0",
    "next-auth": "^5.0.0",
    "@sanity/client": "^6.22.0",
    "next-sanity": "^9.4.0"
  },
  "devDependencies": {
    "@types/node": "^20.0.0",
    "@types/react": "^18.3.0",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.0",
    "@vitest/coverage-v8": "^3.0.0",
    "autoprefixer": "^10.4.0",
    "eslint": "^8.0.0",
    "eslint-config-next": "^15.3.0",
    "jsdom": "^24.0.0",
    "postcss": "^8.4.0",
    "tailwindcss": "^3.4.0",
    "typescript": "^5.0.0",
    "vitest": "^3.0.0"
  }
}
```

- [ ] **Step 2: Install updated packages**

```bash
cd frontend
npm install
```

Expected: Install completes without hard errors. There may be peer-dependency warnings — these are acceptable at this stage and will be resolved in subsequent tasks.

- [ ] **Step 3: Verify the build compiles**

```bash
npm run build
```

Expected: Build exits with code 0. If it fails with a next-auth type error, proceed to Task 2 (the API migration) and re-run the build there.

- [ ] **Step 4: Commit**

```bash
cd ..
git add frontend/package.json frontend/package-lock.json
git commit -m "chore: bump next 14→15, next-auth 4→5, vitest 2→3, eslint-config-next 14→15"
```

---

### Task 2: Migrate next-auth v4 → v5 API

**Files:**
- Modify: `frontend/lib/auth.ts`
- Modify: `frontend/app/api/auth/[...nextauth]/route.ts`

**Interfaces:**
- Consumes: `next-auth@^5.0.0` installed in Task 1.
- Produces:
  - `frontend/lib/auth.ts` exports `{ handlers, auth, signIn, signOut }` and `config: NextAuthConfig`
  - `frontend/app/api/auth/[...nextauth]/route.ts` exports `{ GET, POST }` via `handlers`

- [ ] **Step 1: Rewrite `frontend/lib/auth.ts`**

Replace the entire file with:

```ts
import NextAuth from 'next-auth'
import type { NextAuthConfig } from 'next-auth'

// Next.js 15 note: cookies(), headers(), params, searchParams are now async.
// When adding Cognito providers, await these where needed.
export const config: NextAuthConfig = {
  providers: [],
  callbacks: {},
}

export const { handlers, auth, signIn, signOut } = NextAuth(config)
```

- [ ] **Step 2: Rewrite `frontend/app/api/auth/[...nextauth]/route.ts`**

Replace the entire file with:

```ts
import { handlers } from '@/lib/auth'
export const { GET, POST } = handlers
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd frontend
npm run build
```

Expected: Build exits with code 0. No TypeScript errors.

- [ ] **Step 4: Verify lint passes**

```bash
npm run lint
```

Expected: No errors. Warnings about missing Cognito provider config are acceptable.

- [ ] **Step 5: Verify tests run**

```bash
npm test
```

Expected: vitest exits with code 0. Output will say "No test files found" or similar — that is correct since no tests exist yet.

- [ ] **Step 6: Commit**

```bash
cd ..
git add frontend/lib/auth.ts "frontend/app/api/auth/[...nextauth]/route.ts"
git commit -m "chore: migrate next-auth v4 → v5 (Auth.js) API"
```

---

### Task 3: Apply safe audit patches and verify

**Files:**
- Modify: `frontend/package.json` (indirect — npm audit fix updates dependency resolutions)
- Modify: `frontend/package-lock.json`

**Interfaces:**
- Consumes: Updated `node_modules` from Tasks 1–2.
- Produces: Reduced vulnerability count; patched `js-yaml` and `prismjs` transitive dependencies.

- [ ] **Step 1: Run safe audit fix**

```bash
cd frontend
npm audit fix
```

Expected: Output lists packages updated. Should NOT propose any `--force` changes — if it does, type `n` / do not apply forced changes.

- [ ] **Step 2: Verify the build still passes**

```bash
npm run build
```

Expected: Build exits with code 0.

- [ ] **Step 3: Check remaining vulnerability count**

```bash
npm audit
```

Expected: Vulnerability count is significantly lower than the original 32. Remaining vulnerabilities (if any) will be those requiring breaking changes beyond this upgrade scope (e.g., Sanity's internal dependencies). Review the output and confirm no new high/critical vulns were introduced.

- [ ] **Step 4: Commit**

```bash
cd ..
git add frontend/package.json frontend/package-lock.json
git commit -m "chore: npm audit fix — patch js-yaml and prismjs transitive deps"
```

---

## Final Verification

After all three tasks are committed, run the full verification suite from `frontend/`:

```bash
npm run build   # must exit 0
npm run lint    # must exit 0
npm test        # must exit 0
npm audit       # review output — no new critical/high vulns
```

If any step fails, check which task introduced the failure by running `git bisect` or reviewing the commit that changed the relevant file.
