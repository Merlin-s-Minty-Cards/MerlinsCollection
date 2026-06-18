# Merlin's Minty Cards — Repository Setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scaffold the full repository structure for the Merlin's Minty Cards website so implementation can begin immediately without any structural decision-making overhead.

**Architecture:** Next.js 14 (App Router, TypeScript) frontend with public pages and an authenticated inventory search tool. Python FastAPI backend handles auth, inventory queries, and a Bedrock-powered chatbot. A TypeScript MCP server exposes inventory tools to the AI.

**Tech Stack:** Next.js 14, React 18, Tailwind CSS, NextAuth.js v4, Sanity, Vitest, Python FastAPI, pydantic-settings, pytest, MCP SDK, GitHub Actions

## Global Constraints

- TypeScript strict mode everywhere — no `any`, no `skipLibCheck` workarounds in app code
- Node.js 20, Python 3.12
- Next.js App Router only — no Pages Router files
- Tailwind CSS with Spriggatito green theme tokens defined in `tailwind.config.ts`
- No feature implementation code — placeholder files must be syntactically valid but contain no logic
- All Python packages managed via `pyproject.toml` (hatchling build system)
- TDD: all feature implementation follows CLAUDE.md TDD cycle (red → green → refactor)
- Commits use conventional commit format: `feat:`, `docs:`, `chore:`, `ci:`

---

### Task 1: Update .gitignore

**Files:**
- Modify: `.gitignore`

The existing `.gitignore` is empty. Without it, `node_modules/`, `.next/`, `__pycache__`, and `.env.local` will all be tracked by git.

- [ ] **Step 1: Replace .gitignore with complete content**

```gitignore
# Dependencies
node_modules/
.pnp
.pnp.js

# Next.js
.next/
out/
build/

# Environment files — never commit secrets
.env
.env.local
.env.development.local
.env.test.local
.env.production.local

# Python
__pycache__/
*.py[cod]
*.pyo
*.pyd
.Python
*.egg-info/
dist/
.venv/
venv/
.pytest_cache/
.ruff_cache/

# TypeScript build output
dist/
*.tsbuildinfo

# Coverage
coverage/
.nyc_output/
lcov.info

# OS
.DS_Store
Thumbs.db

# IDE
.vscode/
.idea/
*.swp
*.swo

# Sanity
.sanity/
```

- [ ] **Step 2: Commit**

```bash
git add .gitignore
git commit -m "chore: add complete .gitignore for Next.js, Python, and Node"
```

---

### Task 2: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Replace CLAUDE.md with updated content**

Replace the full contents of `CLAUDE.md` with:

```markdown
# TDD Guidelines
Always follow the outside-in Test-Driven Development (TDD) process.
1. RED: Write failing tests first. Do NOT implement the feature.
2. GREEN: Write minimal code to make the tests pass.
3. REFACTOR: Improve code quality, ensuring tests remain green.
Never combine phases. Wait for user confirmation after confirming tests fail.

# Project Overview
Merlin's Minty Cards — a Pokemon card business website.
- Public website: Home, Shows, About, Collectors Dictionary, Articles
- Authenticated inventory search tool (filter mode + AI chat mode)
- Article/content hub for beginner collectors, managed via Sanity CMS

# Architecture

| Layer       | Language   | Framework       | Location       |
|-------------|------------|-----------------|----------------|
| Frontend    | TypeScript | Next.js 14      | `frontend/`    |
| Backend API | Python     | FastAPI         | `backend/`     |
| MCP Server  | TypeScript | MCP SDK         | `mcp-server/`  |
| CMS         | -          | Sanity          | `frontend/sanity/` |

# Site Pages

| Route                | Auth Required | Purpose                              |
|----------------------|---------------|--------------------------------------|
| `/`                  | No            | Home — brand intro, highlights       |
| `/shows`             | No            | Upcoming and past card show events   |
| `/about`             | No            | Business story, team, contact        |
| `/dictionary`        | No            | Collectors Dictionary (beginner terminology) |
| `/articles`          | No            | Article listing (Cluster Hub)        |
| `/articles/[slug]`   | No            | Individual article (SSG via Sanity)  |
| `/inventory`         | Yes           | Inventory search (filter + chat)     |

# Test Commands

| Layer      | Command                                        |
|------------|------------------------------------------------|
| All        | `npm test` (from repo root)                    |
| Frontend   | `npm test --workspace=frontend`                |
| MCP Server | `npm test --workspace=mcp-server`              |
| Backend    | `python -m pytest backend/tests -q --tb=short` |
| Lint (FE)  | `cd frontend && npm run lint`                  |
| Lint (BE)  | `ruff check backend/src`                       |

# Inventory Search Tool
Located at `/inventory` — authenticated customers only.
Two distinct modes (user picks one at a time):
- **Filter mode**: dropdowns (set, condition, rarity), price range, name search → `GET /inventory/search`
- **Chat mode**: plain text to Claude via Bedrock + MCP tools → `POST /chat`

# MCP Tools
- `get_inventory_summary` — total count, value, top cards
- `search_inventory` — filter by name, set, condition, value range
- `get_card_price_history` — historical price data for a card
- `calculate_inventory_value` — full valuation with breakdown by set/condition
- `flag_underpriced_cards` — cards listed below market price threshold

# AWS Services
| Service         | Purpose                                              |
|-----------------|------------------------------------------------------|
| S3              | Card image storage, inventory data exports           |
| CloudFront      | CDN for serving card images                          |
| DynamoDB        | Card inventory database (flexible schema)            |
| Lambda          | Serverless price lookup and image processing         |
| API Gateway     | REST API gateway for the backend                     |
| Cognito         | Customer authentication                              |
| Rekognition     | Image analysis (future: identify cards from photos)  |
| Bedrock         | Claude AI integration for chat mode queries          |

# Design System
- Color scheme based on Spriggatito (forest greens, cream whites)
- Business/brand images stored in `frontend/public/images/` organized by:
  - `logo/` — logo variants
  - `brand/` — business photos, team, storefront
  - `shows/` — card show photos
  - `cards/` — card reference images

# Code Review
All PRs require review. CODEOWNERS enforces review by @EthanHarter934.
Branch protection rules must be enabled in GitHub Settings > Branches:
- Require a pull request before merging
- Require status checks (CI) to pass
- Require review from Code Owners
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for Merlin's Minty Cards website"
```

---

### Task 3: Add README.md

**Files:**
- Create: `README.md`

- [ ] **Step 1: Create README.md**

Create `README.md` at the repo root with:

```markdown
# Merlin's Minty Cards

Pokemon card business website with an authenticated inventory search tool.

## Stack

| Layer | Tech |
|---|---|
| Frontend | Next.js 14, TypeScript, Tailwind CSS, NextAuth.js, Sanity |
| Backend | Python 3.12, FastAPI, pydantic-settings, boto3 |
| MCP Server | TypeScript, MCP SDK |
| Database | AWS DynamoDB |
| Auth | AWS Cognito |
| AI | AWS Bedrock (Claude) |
| CDN | AWS CloudFront + S3 |
| CMS | Sanity |

## Local Development

### Prerequisites

- Node.js 20+
- Python 3.12+
- npm 10+

### Frontend

```bash
cd frontend
cp .env.example .env.local   # fill in values
npm install
npm run dev                  # http://localhost:3000
```

### Backend

```bash
cd backend
cp .env.example .env
pip install -e ".[dev]"
uvicorn src.merlins_collection.main:app --reload  # http://localhost:8000
```

### MCP Server

```bash
cd mcp-server
npm install
npm run build
```

## Running Tests

```bash
# All tests
npm test

# Frontend only
npm test --workspace=frontend

# Backend only
python -m pytest backend/tests -q --tb=short

# MCP server only
npm test --workspace=mcp-server
```

## Linting

```bash
# Frontend
cd frontend && npm run lint

# Backend
ruff check backend/src
```

## Environment Variables

See `frontend/.env.example` and `backend/.env.example` for required variables.

## Contributing

All PRs require review from @EthanHarter934. See CLAUDE.md for TDD guidelines and branch protection requirements.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add README with setup and dev instructions"
```

---

### Task 4: Configure Frontend for Next.js

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/tsconfig.json`
- Modify: `frontend/vitest.config.ts`
- Create: `frontend/next.config.ts`
- Create: `frontend/tailwind.config.ts`
- Create: `frontend/postcss.config.mjs`
- Create: `frontend/.eslintrc.json`
- Create: `frontend/.env.example`

- [ ] **Step 1: Replace frontend/package.json**

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
    "next": "^14.2.0",
    "react": "^18.3.0",
    "react-dom": "^18.3.0",
    "next-auth": "^4.24.0",
    "@sanity/client": "^6.22.0",
    "next-sanity": "^9.4.0"
  },
  "devDependencies": {
    "@types/node": "^20.0.0",
    "@types/react": "^18.3.0",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.0",
    "@vitest/coverage-v8": "^2.0.0",
    "autoprefixer": "^10.4.0",
    "eslint": "^8.0.0",
    "eslint-config-next": "^14.2.0",
    "jsdom": "^24.0.0",
    "postcss": "^8.4.0",
    "tailwindcss": "^3.4.0",
    "typescript": "^5.0.0",
    "vitest": "^2.0.0"
  }
}
```

- [ ] **Step 2: Replace frontend/tsconfig.json**

Next.js requires a different tsconfig shape than the current plain-TypeScript config.

```json
{
  "compilerOptions": {
    "lib": ["dom", "dom.iterable", "esnext"],
    "allowJs": true,
    "skipLibCheck": true,
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "preserve",
    "incremental": true,
    "plugins": [{ "name": "next" }],
    "paths": {
      "@/*": ["./*"]
    }
  },
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
  "exclude": ["node_modules"]
}
```

- [ ] **Step 3: Replace frontend/vitest.config.ts**

Add the React plugin and `@` path alias so Vitest understands JSX and the same imports Next.js uses.

```ts
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    include: ["**/__tests__/**/*.test.{ts,tsx}"],
    coverage: {
      provider: "v8",
      reporter: ["text", "lcov"],
    },
  },
});
```

- [ ] **Step 4: Create frontend/next.config.ts**

```ts
import type { NextConfig } from 'next'

const nextConfig: NextConfig = {
  images: {
    remotePatterns: [
      // Add CloudFront domain here when provisioned:
      // { protocol: 'https', hostname: '<id>.cloudfront.net' }
    ],
  },
}

export default nextConfig
```

- [ ] **Step 5: Create frontend/tailwind.config.ts**

```ts
import type { Config } from 'tailwindcss'

const config: Config = {
  content: [
    './app/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        spriggatito: {
          50:  '#f2faf3',
          100: '#d4f0d9',
          200: '#a9e0b3',
          300: '#72c882',
          400: '#4aae5e',
          500: '#2d8f44',
          600: '#1f6e32',
          700: '#175427',
          800: '#103b1c',
          900: '#082110',
        },
        cream: '#f5f0e8',
      },
    },
  },
  plugins: [],
}

export default config
```

- [ ] **Step 6: Create frontend/postcss.config.mjs**

```js
const config = {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
}

export default config
```

- [ ] **Step 7: Create frontend/.eslintrc.json**

```json
{
  "extends": "next/core-web-vitals"
}
```

- [ ] **Step 8: Create frontend/.env.example**

```
# NextAuth
NEXTAUTH_URL=http://localhost:3000
NEXTAUTH_SECRET=

# Backend API
NEXT_PUBLIC_API_URL=http://localhost:8000

# CloudFront CDN (set when provisioned)
NEXT_PUBLIC_CLOUDFRONT_URL=

# AWS Cognito
AWS_COGNITO_CLIENT_ID=
AWS_COGNITO_CLIENT_SECRET=
AWS_COGNITO_ISSUER=

# Sanity CMS
NEXT_PUBLIC_SANITY_PROJECT_ID=
NEXT_PUBLIC_SANITY_DATASET=production
SANITY_API_TOKEN=
```

- [ ] **Step 9: Commit**

```bash
git add frontend/package.json frontend/tsconfig.json frontend/vitest.config.ts frontend/next.config.ts frontend/tailwind.config.ts frontend/postcss.config.mjs frontend/.eslintrc.json frontend/.env.example
git commit -m "chore: configure frontend for Next.js 14 with Tailwind and Vitest"
```

---

### Task 5: Scaffold frontend/app/ Directory

**Files (all create):**
- `frontend/app/layout.tsx`
- `frontend/app/globals.css`
- `frontend/app/(public)/layout.tsx`
- `frontend/app/(public)/page.tsx`
- `frontend/app/(public)/shows/page.tsx`
- `frontend/app/(public)/about/page.tsx`
- `frontend/app/(public)/dictionary/page.tsx`
- `frontend/app/(public)/articles/page.tsx`
- `frontend/app/(public)/articles/[slug]/page.tsx`
- `frontend/app/(auth)/layout.tsx`
- `frontend/app/(auth)/inventory/page.tsx`
- `frontend/app/api/auth/[...nextauth]/route.ts`

- [ ] **Step 1: Create frontend/app/globals.css**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;
```

- [ ] **Step 2: Create frontend/app/layout.tsx**

```tsx
import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: {
    default: "Merlin's Minty Cards",
    template: "%s | Merlin's Minty Cards",
  },
  description: "Pokemon card inventory and collector resources from Merlin's Minty Cards.",
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}
```

- [ ] **Step 3: Create frontend/app/(public)/layout.tsx**

```tsx
// Wraps all public pages — Navbar and Footer added here during implementation
export default function PublicLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>
}
```

- [ ] **Step 4: Create frontend/app/(public)/page.tsx**

```tsx
import type { Metadata } from 'next'

export const metadata: Metadata = { title: 'Home' }

export default function HomePage() {
  return null
}
```

- [ ] **Step 5: Create frontend/app/(public)/shows/page.tsx**

```tsx
import type { Metadata } from 'next'

export const metadata: Metadata = { title: 'Shows' }

export default function ShowsPage() {
  return null
}
```

- [ ] **Step 6: Create frontend/app/(public)/about/page.tsx**

```tsx
import type { Metadata } from 'next'

export const metadata: Metadata = { title: 'About' }

export default function AboutPage() {
  return null
}
```

- [ ] **Step 7: Create frontend/app/(public)/dictionary/page.tsx**

```tsx
import type { Metadata } from 'next'

export const metadata: Metadata = { title: 'Dictionary' }

export default function DictionaryPage() {
  return null
}
```

- [ ] **Step 8: Create frontend/app/(public)/articles/page.tsx**

```tsx
import type { Metadata } from 'next'

export const metadata: Metadata = { title: 'Articles' }

export default function ArticlesPage() {
  return null
}
```

- [ ] **Step 9: Create frontend/app/(public)/articles/[slug]/page.tsx**

```tsx
import type { Metadata } from 'next'

type Props = { params: { slug: string } }

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  return { title: params.slug }
}

export default function ArticlePage({ params }: Props) {
  return null
}
```

- [ ] **Step 10: Create frontend/app/(auth)/layout.tsx**

```tsx
// Redirects unauthenticated users to sign-in — guard added during implementation
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>
}
```

- [ ] **Step 11: Create frontend/app/(auth)/inventory/page.tsx**

```tsx
import type { Metadata } from 'next'

export const metadata: Metadata = { title: 'Inventory Search' }

export default function InventoryPage() {
  return null
}
```

- [ ] **Step 12: Create frontend/app/api/auth/[...nextauth]/route.ts**

```ts
import NextAuth from 'next-auth'
import { authOptions } from '@/lib/auth'

const handler = NextAuth(authOptions)
export { handler as GET, handler as POST }
```

- [ ] **Step 13: Commit**

```bash
git add frontend/app/
git commit -m "chore: scaffold Next.js App Router page and layout structure"
```

---

### Task 6: Scaffold frontend/components/, lib/, sanity/, and public/images/

**Files (all create):**
- `frontend/lib/auth.ts`
- `frontend/lib/sanity.ts`
- `frontend/lib/api.ts`
- `frontend/components/ui/.gitkeep`
- `frontend/components/layout/.gitkeep`
- `frontend/components/inventory/FilterPanel.tsx`
- `frontend/components/inventory/ChatPanel.tsx`
- `frontend/components/inventory/ModeToggle.tsx`
- `frontend/components/inventory/CardGrid.tsx`
- `frontend/components/inventory/CardTile.tsx`
- `frontend/components/articles/ArticleCard.tsx`
- `frontend/components/articles/ArticleList.tsx`
- `frontend/sanity/schemas/article.ts`
- `frontend/public/images/logo/.gitkeep`
- `frontend/public/images/brand/.gitkeep`
- `frontend/public/images/shows/.gitkeep`
- `frontend/public/images/cards/.gitkeep`

- [ ] **Step 1: Create frontend/lib/auth.ts**

```ts
import type { NextAuthOptions } from 'next-auth'

// Cognito provider and callbacks added via TDD
export const authOptions: NextAuthOptions = {
  providers: [],
  callbacks: {},
}
```

- [ ] **Step 2: Create frontend/lib/sanity.ts**

```ts
import { createClient } from '@sanity/client'

// Client configured via TDD once env vars are set
export const sanityClient = createClient({
  projectId: process.env.NEXT_PUBLIC_SANITY_PROJECT_ID ?? '',
  dataset: process.env.NEXT_PUBLIC_SANITY_DATASET ?? 'production',
  useCdn: true,
  apiVersion: '2024-01-01',
})
```

- [ ] **Step 3: Create frontend/lib/api.ts**

```ts
// Typed fetch wrapper for the FastAPI backend — implemented via TDD
const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, init)
  if (!res.ok) throw new Error(`API error ${res.status}: ${path}`)
  return res.json() as Promise<T>
}
```

- [ ] **Step 4: Create inventory component placeholders**

Create each file below with the content shown (replace `ComponentName` with the actual name):

`frontend/components/inventory/FilterPanel.tsx`:
```tsx
// Structured search: dropdowns, price range, name — implemented via TDD
export default function FilterPanel() {
  return null
}
```

`frontend/components/inventory/ChatPanel.tsx`:
```tsx
// Natural language chat interface to Bedrock — implemented via TDD
export default function ChatPanel() {
  return null
}
```

`frontend/components/inventory/ModeToggle.tsx`:
```tsx
// Switches between Filter mode and Chat mode — implemented via TDD
export default function ModeToggle() {
  return null
}
```

`frontend/components/inventory/CardGrid.tsx`:
```tsx
// Displays search results as a grid of cards — implemented via TDD
export default function CardGrid() {
  return null
}
```

`frontend/components/inventory/CardTile.tsx`:
```tsx
// Single card result tile — implemented via TDD
export default function CardTile() {
  return null
}
```

- [ ] **Step 5: Create article component placeholders**

`frontend/components/articles/ArticleCard.tsx`:
```tsx
// Preview card for an article — implemented via TDD
export default function ArticleCard() {
  return null
}
```

`frontend/components/articles/ArticleList.tsx`:
```tsx
// List of ArticleCards — implemented via TDD
export default function ArticleList() {
  return null
}
```

- [ ] **Step 6: Create ui/ and layout/ placeholder directories**

```bash
New-Item -ItemType File -Force frontend/components/ui/.gitkeep
New-Item -ItemType File -Force frontend/components/layout/.gitkeep
```

- [ ] **Step 7: Create frontend/sanity/schemas/article.ts**

```ts
// Sanity article schema — fields expanded via TDD
const article = {
  name: 'article',
  title: 'Article',
  type: 'document' as const,
  fields: [
    { name: 'title', title: 'Title', type: 'string' },
    { name: 'slug', title: 'Slug', type: 'slug', options: { source: 'title' } },
    { name: 'publishedAt', title: 'Published At', type: 'datetime' },
    { name: 'body', title: 'Body', type: 'array', of: [{ type: 'block' }] },
  ],
}

export default article
```

- [ ] **Step 8: Create public/images/ directory structure**

```bash
New-Item -ItemType File -Force frontend/public/images/logo/.gitkeep
New-Item -ItemType File -Force frontend/public/images/brand/.gitkeep
New-Item -ItemType File -Force frontend/public/images/shows/.gitkeep
New-Item -ItemType File -Force frontend/public/images/cards/.gitkeep
```

- [ ] **Step 9: Commit**

```bash
git add frontend/lib/ frontend/components/ frontend/sanity/ frontend/public/
git commit -m "chore: scaffold frontend components, lib, sanity schema, and image directories"
```

---

### Task 7: Scaffold Backend Structure

**Files:**
- Modify: `backend/pyproject.toml`
- Create: `backend/.env.example`
- Create: `backend/src/merlins_collection/config.py`
- Create: `backend/src/merlins_collection/routers/__init__.py`
- Create: `backend/src/merlins_collection/routers/auth.py`
- Create: `backend/src/merlins_collection/routers/inventory.py`
- Create: `backend/src/merlins_collection/routers/chat.py`
- Create: `backend/src/merlins_collection/services/__init__.py`
- Create: `backend/src/merlins_collection/services/cognito.py`
- Create: `backend/src/merlins_collection/services/dynamodb.py`
- Create: `backend/src/merlins_collection/services/bedrock.py`
- Create: `backend/src/merlins_collection/services/mcp_client.py`
- Create: `backend/src/merlins_collection/models/__init__.py`
- Create: `backend/src/merlins_collection/models/inventory.py`
- Create: `backend/src/merlins_collection/models/chat.py`
- Create: `backend/tests/routers/__init__.py`
- Create: `backend/tests/routers/test_auth.py`
- Create: `backend/tests/routers/test_inventory.py`
- Create: `backend/tests/routers/test_chat.py`
- Create: `backend/tests/services/__init__.py`
- Create: `backend/tests/services/test_dynamodb.py`
- Create: `backend/tests/services/test_bedrock.py`

- [ ] **Step 1: Update backend/pyproject.toml**

Add `pydantic-settings`, `python-jose`, and `ruff` to dependencies:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "merlins-collection-backend"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.111.0",
    "uvicorn[standard]>=0.30.0",
    "boto3>=1.34.0",
    "pydantic-settings>=2.3.0",
    "python-jose[cryptography]>=3.3.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "httpx>=0.27.0",
    "ruff>=0.4.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I"]

[tool.hatch.build.targets.wheel]
packages = ["src/merlins_collection"]
```

- [ ] **Step 2: Create backend/.env.example**

```
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
COGNITO_USER_POOL_ID=
COGNITO_CLIENT_ID=
DYNAMODB_TABLE_NAME=merlins-cards
BEDROCK_MODEL_ID=anthropic.claude-3-5-sonnet-20241022-v2:0
MCP_SERVER_PATH=../mcp-server/dist/index.js
```

- [ ] **Step 3: Create backend/src/merlins_collection/config.py**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    aws_region: str = "us-east-1"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    cognito_user_pool_id: str = ""
    cognito_client_id: str = ""
    dynamodb_table_name: str = "merlins-cards"
    bedrock_model_id: str = "anthropic.claude-3-5-sonnet-20241022-v2:0"
    mcp_server_path: str = "../mcp-server/dist/index.js"


settings = Settings()
```

- [ ] **Step 4: Create router placeholders**

`backend/src/merlins_collection/routers/__init__.py`: (empty file)

`backend/src/merlins_collection/routers/auth.py`:
```python
from fastapi import APIRouter

# Cognito JWT validation and session endpoints — implemented via TDD
router = APIRouter(prefix="/auth", tags=["auth"])
```

`backend/src/merlins_collection/routers/inventory.py`:
```python
from fastapi import APIRouter

# Structured inventory search (filter mode) — implemented via TDD
router = APIRouter(prefix="/inventory", tags=["inventory"])
```

`backend/src/merlins_collection/routers/chat.py`:
```python
from fastapi import APIRouter

# AI chat endpoint via Bedrock + MCP (chat mode) — implemented via TDD
router = APIRouter(prefix="/chat", tags=["chat"])
```

- [ ] **Step 5: Create service placeholders**

`backend/src/merlins_collection/services/__init__.py`: (empty file)

`backend/src/merlins_collection/services/cognito.py`:
```python
# AWS Cognito client — JWT validation and user management — implemented via TDD
```

`backend/src/merlins_collection/services/dynamodb.py`:
```python
# DynamoDB inventory queries — implemented via TDD
```

`backend/src/merlins_collection/services/bedrock.py`:
```python
# Claude via AWS Bedrock — implemented via TDD
```

`backend/src/merlins_collection/services/mcp_client.py`:
```python
# MCP server client — spawns mcp-server process and calls tools — implemented via TDD
```

- [ ] **Step 6: Create model placeholders**

`backend/src/merlins_collection/models/__init__.py`: (empty file)

`backend/src/merlins_collection/models/inventory.py`:
```python
from pydantic import BaseModel

# Card inventory Pydantic models — implemented via TDD
```

`backend/src/merlins_collection/models/chat.py`:
```python
from pydantic import BaseModel

# Chat message Pydantic models — implemented via TDD
```

- [ ] **Step 7: Create test placeholders**

`backend/tests/routers/__init__.py`: (empty file)

`backend/tests/routers/test_auth.py`:
```python
# Auth router tests — written via TDD as features are implemented
```

`backend/tests/routers/test_inventory.py`:
```python
# Inventory router tests — written via TDD as features are implemented
```

`backend/tests/routers/test_chat.py`:
```python
# Chat router tests — written via TDD as features are implemented
```

`backend/tests/services/__init__.py`: (empty file)

`backend/tests/services/test_dynamodb.py`:
```python
# DynamoDB service tests — written via TDD as features are implemented
```

`backend/tests/services/test_bedrock.py`:
```python
# Bedrock service tests — written via TDD as features are implemented
```

- [ ] **Step 8: Verify backend still passes tests**

```bash
cd backend && pip install -e ".[dev]" && python -m pytest tests -q --tb=short
```

Expected: all existing tests pass (no new logic was added).

- [ ] **Step 9: Commit**

```bash
git add backend/
git commit -m "chore: scaffold backend routers, services, models, and test structure"
```

---

### Task 8: Update CI/CD Workflow

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Replace .github/workflows/ci.yml**

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test-frontend:
    name: Frontend Tests
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: "npm"
          cache-dependency-path: frontend/package.json
      - run: npm ci
        working-directory: frontend
      - run: npm test
        working-directory: frontend
      - run: npm run build
        working-directory: frontend

  test-mcp-server:
    name: MCP Server Tests
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: "npm"
          cache-dependency-path: mcp-server/package.json
      - run: npm ci
        working-directory: mcp-server
      - run: npm test
        working-directory: mcp-server

  test-backend:
    name: Backend Tests
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: "pip"
      - run: pip install -e ".[dev]"
        working-directory: backend
      - run: pytest
        working-directory: backend

  lint:
    name: Lint
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: "npm"
          cache-dependency-path: frontend/package.json
      - run: npm ci
        working-directory: frontend
      - run: npm run lint
        working-directory: frontend
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: "pip"
      - run: pip install ruff
      - run: ruff check backend/src
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add lint job and next build step to frontend test job"
```
