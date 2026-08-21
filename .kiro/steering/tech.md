# Technical Architecture & Project Structure

## Stack

| Layer | Tech | Key Details |
|---|---|---|
| Frontend | TypeScript, Next.js 15 (App Router), Tailwind 3.4, React 18 | Vitest, `@testing-library/react` |
| Backend | Python 3.12, FastAPI, pydantic-settings, boto3 | pytest + moto, ruff linter |
| MCP Server | TypeScript, `@modelcontextprotocol/sdk`, zod | Vitest, ES modules |
| CMS | Sanity | GROQ queries, `next-sanity` |
| Database | AWS DynamoDB | Single-table design |
| Auth | AWS Cognito | NextAuth.js 5 beta wrapping Cognito |
| AI | AWS Bedrock | Claude Sonnet 4.5 (`us.anthropic.claude-sonnet-4-5-20250929-v1:0`) |
| Storage | AWS S3 + CloudFront | Card images, exports |

## Monorepo Layout

npm workspaces: `frontend`, `mcp-server`. Root `package.json` orchestrates all.

```
.
├── backend/src/merlins_collection/
│   ├── config.py              # pydantic-settings (env-based config)
│   ├── dependencies.py        # FastAPI deps (require_user, require_admin)
│   ├── main.py                # App factory, router mounts, CORS
│   ├── models/                # Pydantic models
│   │   ├── catalog.py         #   Card, CardSet (TCGdex schema)
│   │   ├── inventory.py       #   InventoryItem, InventoryFilters
│   │   ├── business.py        #   Transaction, Show, SellSession, BuySession, TradeSession
│   │   ├── auth.py            #   TokenPayload, UserInfo
│   │   └── chat.py            #   ChatMessage, ChatRequest
│   ├── services/
│   │   ├── dynamodb.py        #   InventoryRepository (full CRUD + queries)
│   │   ├── tcgdex.py          #   External TCGdex API client
│   │   ├── bedrock.py         #   Claude AI integration
│   │   ├── mcp_client.py      #   MCP server process management
│   │   ├── cognito.py         #   JWT verification
│   │   ├── catalog_sync.py    #   TCGdex → DynamoDB sync
│   │   ├── condition_pricing.py  # Grade-aware pricing
│   │   ├── sales.py           #   SellEngine, PurchaseEngine, TradeEngine
│   │   ├── card_text.py       #   Card description generation
│   │   └── spreadsheet_import.py # CSV/Excel import
│   └── routers/
│       ├── admin/             #   Retool API (CRUD, market, sell, buy, trade, show-prep)
│       ├── auth.py            #   Login/logout
│       ├── chat.py            #   AI chat endpoint
│       ├── health.py          #   Health check
│       ├── inventory.py       #   User-facing inventory search
│       └── public.py          #   Public card data, shows, daily-feature
├── backend/tests/             # pytest suites (mirror src structure)
├── backend/scripts/           # CLI: seed_catalog, import_spreadsheet, daily_sync
├── frontend/
│   ├── app/
│   │   ├── (public)/          # Route group: /, /shows, /about, /dictionary, /articles
│   │   ├── (auth)/            # Route group: authenticated pages
│   │   ├── (admin)/           # Route group: admin pages
│   │   ├── api/               # Next.js API routes (NextAuth)
│   │   ├── studio/            # Sanity Studio embedded
│   │   ├── layout.tsx         # Root layout (Fraunces + Inter fonts)
│   │   └── globals.css        # Flip card, glare, vault theme, reveal animations
│   ├── components/
│   │   ├── admin/             # Admin UI components
│   │   ├── articles/          # Article rendering
│   │   ├── dictionary/        # Dictionary components
│   │   ├── home/              # Home page (hero, featured cards, FlipCard)
│   │   ├── inventory/         # Filter mode + Chat mode UI
│   │   ├── layout/            # Header, Footer, Nav
│   │   ├── providers/         # SessionProvider (NextAuth)
│   │   └── ui/                # Shared UI primitives
│   ├── lib/
│   │   ├── api.ts             # Backend API client
│   │   ├── admin-api.ts       # Admin API client
│   │   ├── auth.ts / auth.config.ts  # NextAuth config
│   │   ├── sanity.ts          # Sanity client + GROQ queries
│   │   ├── inventory.ts       # Inventory types and helpers
│   │   └── public.ts          # Public API helpers
│   └── sanity/                # Sanity schema definitions
├── mcp-server/src/
│   ├── index.ts               # Entry point
│   ├── server.ts              # MCP server setup
│   ├── repository.ts          # Repository interface
│   ├── dynamodb-repository.ts # DynamoDB implementation
│   └── tools/                 # 5 MCP tool implementations
├── shared/tool-contract.json  # MCP tool interface definitions
├── docs/rfcs/                 # Design decisions
├── .kiro/plans/               # Per-plan roadmap, follow-ups, Council artifacts
└── CLAUDE.md                  # AI agent instructions
```

## Key Patterns

### Backend
- **Config:** `config.py` → `Settings` class (pydantic-settings, reads `.env`)
- **Auth:** `dependencies.py` → `require_user` / `require_admin` (Cognito JWT or API key)
- **Data access:** `services/dynamodb.py` → `InventoryRepository` (single instance)
- **Admin API key:** Static bearer token for Retool (bypasses Cognito)
- **EUR→USD:** Configurable rate for Cardmarket prices (`eur_usd_rate`)
- **CORS:** `cors_origins` setting (default: `http://localhost:3000`)

### Frontend
- **Server components by default;** client components marked `"use client"`
- **Tailwind theme:** Custom colors in `frontend/tailwind.config.ts`
- **Fonts:** Fraunces (serif, `--font-fraunces`) + Inter (sans, `--font-inter`)
- **Body classes:** `bg-cream text-ink font-sans antialiased`
- **Images:** `next/image` with CloudFront loader
- **Testing:** Vitest + React Testing Library + jsdom

### Naming Conventions
- **Python:** snake_case, ruff linter, pydantic models
- **TypeScript:** camelCase vars/functions, PascalCase components/types
- **Files:** kebab-case (frontend), snake_case (backend)
- **Commits:** `type(scope): description` (conventional commits)

## TDD Process (Mandatory)
1. **RED** — Write failing tests first
2. **GREEN** — Minimal code to pass
3. **REFACTOR** — Clean up, tests stay green

Never combine phases. Every behavioral change requires TDD.

## Branch Strategy
- PRs required for main
- CI: GitHub Actions (`.github/workflows/ci.yml`)
- CODEOWNERS enforced
- State tracked per plan under `.kiro/plans/` — see orchestrator.md

## Dependencies (pinned versions that matter)
- `next`: ^15.3.0, `react`: ^18.3.0
- `next-auth`: 5.0.0-beta.31
- `tailwindcss`: ^3.4.0
- `fastapi`: >=0.111.0
- `boto3`: >=1.34.0
- `@modelcontextprotocol/sdk`: ^1.0.0
- `@aws-sdk/client-dynamodb`: ^3.1079.0

## Agent & Skill File Editing

**Frontmatter is configuration, not prose — never drop a field while condensing.** Agent files in `.kiro/agents/` declare `tools:` (e.g. `[read, write, shell]`) alongside `name`, `description`, and `model`. Removing `tools:` does not fall back to "inherit everything"; it starves the agent, which then cannot read or edit files. This was observed live: stripping `tools:` from all 13 agents left the orchestrator able to activate skills and nothing else. Prune bodies freely; leave frontmatter keys intact unless a source confirms the field is optional.

**A section the original marks critical stays.** When an author has explicitly ranked a section ("read first"), that ranking is evidence; overriding it needs a reason beyond brevity.

**Delegation needs an explicit `subagent` tool grant.** An orchestrating agent with `tools: [read, write, shell]` cannot dispatch specialists — `subagent` must be listed (or `@builtin` / `*`). This is independent of the `subagent` capability rule in `.kiro/settings.json`, which governs permission, not tool availability. Optional `toolsSettings.subagent.availableAgents` (glob) and `.trustedAgents` (skip approval prompts) narrow the grant. Source: [subagents docs](https://kiro.dev/docs/custom-agents/subagents.md).

**Kiro's agent semantics differ from Claude Code's — don't port constraints across.** A Kiro custom agent set as the session agent *can* spawn subagents given the `subagent` grant; only a spawned subagent cannot spawn further. An earlier version of `orchestrator.md` carried Claude Code's "main thread only" rule verbatim and was wrong for this IDE.
