# TDD Guidelines
Always follow the outside-in Test-Driven Development (TDD) process.
1. RED: Write failing tests first. Do NOT implement the feature.
2. GREEN: Write minimal code to make the tests pass.
3. REFACTOR: Improve code quality, ensuring tests remain green.
Never combine phases. Wait for user confirmation after confirming tests fail.

# Agent Workflow
Custom sub-agents live in `.claude/agents/`. The `orchestrator` agent conducts this whole flow — deciding what's trivial vs. non-trivial and routing each piece to the right specialist. **Reference it into the main chat with `@orchestrator` (or `/`); never spawn it as a sub-agent.** Referencing loads its instructions into the main thread, which is the only thread that can spawn other agents — spawning the orchestrator instead would trap it in a sub-agent that cannot delegate, defeating its purpose.

For **non-trivial feature work** (new functionality, multi-step changes, anything that will touch more than a couple of files), default to this flow without waiting to be asked:
1. Start with the `initializer` agent to audit the workspace and create/update `progress.txt`, unless one already exists and is current for the active feature.
2. Route each roadmap item to the appropriate agent (`design-doc`, `code-writer`, `test-qa`, `doc-writer`, `pull-request`, `web-browser`) based on its own description.
3. Every `code-writer` submission must clear the Council Loop (`advisor-contrarian`, `advisor-security`, `advisor-chaos`, `advisor-architect` → `council-judge`) before being considered done.

Skip this default for small fixes, one-off questions, or anything the user frames as quick — go straight to the relevant single agent (or no agent) instead. The user can also override explicitly at any time (e.g. "skip the initializer", "just write the code").

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

# Third-Party APIs (Planned)
Both currently UNBUILT and ON HOLD pending owner-provided API keys (see
claude-progress.txt Phase 4, PAUSED as of 2026-07-27 — this is not the active
phase; do not resume it without the owner's go-ahead).
- **PSA cert API** — slab identity verification for graded PSA cards. Cert
  number -> verified name/set/year/card#/grade/grade label/population/official
  images. The cert number IS the identity for a PSA slab (no fuzzy matching).
  When Phase 4 resumes, PSA-graded slabs go through this automated cert
  lookup.
- **PriceCharting API** — per-grade graded-card market values (the raw
  TCGplayer/Cardmarket price feed does not price slabs). Sheet
  Sticker/Current Market is the fallback when no key/budget or no coverage.
- **Non-PSA slabs (CGC/BGS/SGC) are handled differently, by design** — they
  arrive too rarely to justify their own automated cert-lookup pipeline.
  Instead, an admin-only manual-entry flow (staff keys in the slab's info
  directly, including grading company) is planned for the future. This is
  also on hold; see claude-progress.txt Section 4 Q3.

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
