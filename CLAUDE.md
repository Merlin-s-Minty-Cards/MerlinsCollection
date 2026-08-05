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
| `/admin`             | Yes (admin)   | Admin panel — see Admin Panel below  |

# Admin Panel

`/admin` (gated by admin Cognito group) covers inventory ops end to end. Sidebar
order (`frontend/components/admin/AdminShell.tsx`):

| Route                  | Label          | Purpose                              |
|------------------------|----------------|---------------------------------------|
| `/admin`               | Dashboard      | Landing overview                      |
| `/admin/inventory`     | Inventory      | Inventory CRUD, granular filters, ownership column |
| `/admin/sell`          | Sell           | Sale flow, large image preview        |
| `/admin/buy`           | Buy            | Purchase flow, catalog-linked autocomplete, manual-entry mode |
| `/admin/trade`         | Trade          | Trade flow — Coming In / Going Out, basis modes (see below) |
| `/admin/vault`         | Vault          | Sortable inventory table, ownership column |
| `/admin/market`        | Market         | Prices, sync trigger, coverage/confidence, "check for new sets" |
| `/admin/show-prep`     | Show Prep      | Bulk-move to a show location, inline sticker/TCG-link editing |
| `/admin/outgoing`      | **Prep Queue** | See "Prep Queue" below — route path is unchanged, the UI/purpose is not |
| `/admin/analytics`     | Show Analytics | Tabbed Daily / Shows dashboard (see below) |
| `/admin/history`       | History        | Transaction history with profit visibility (see below) |
| `/admin/cosigners`     | Cosigners      | Cosigner CRUD + payout link tool     |
| `/admin/card/[id]`     | (card detail)  | Single-item detail, price chart, timeline — not in sidebar, reached via links |

**Prep Queue gotcha:** the route path is still `/admin/outgoing` (unchanged
since before Round 3) but the page itself was repurposed in Task 3.4 from a
sold/shipment tracker into a queue of unstickered available inventory
(`GET` filtered to `status=available, missing_sticker=true`). Reading the URL
alone will mislead — it no longer tracks outgoing shipments. Pricing an item
inline removes it from the queue immediately ("Priced → removed" toast).

**Show Analytics** (`/admin/analytics`) — tabbed `Daily` / `Shows` view. Daily
tab shows a single day's dashboard (`GET /analytics/daily`); Shows tab lists
the show archive (`GET /admin/shows`) with a detail drill-in per show.

**History** (`/admin/history`) — searches an item's full transaction timeline
and trade lineage. Shows `step_profit` per lineage hop (color-coded, guarded
against a $0 cost-basis overstating profit on consigned items) and a rolled-up
"Chain Profit" summary when a chain has more than one hop; lineage nodes are
clickable to navigate the chain.

**Cosigners** (`/admin/cosigners`) — CRUD + payout-link tool for consignors;
card assignment is still raw item-ID entry (no picker UI, deliberately out of
scope).

**Condition vocabulary.** Display strings are `NM, LP+, LP, LP-, MP, HP, DMG`,
but storage is ALWAYS two separate fields — `condition` (the tier: `NM/LP/MP/
HP/DMG`, `Condition` enum) plus `condition_modifier` (`ConditionModifier`:
`"+"`/`"-"`/`null`) — never a combined `"LP+"` enum value. That combined form
used to be sent straight to the backend and failed enum validation (the Round 1
bug); `normalize_condition()` (`backend/src/merlins_collection/models/
inventory.py`) now splits a display string into the two stored fields, mirrored
on the frontend by `parseCondition`/`formatCondition` (`frontend/lib/
constants.ts`).

**Locations.** Admin-managed, DB-backed list — not a hardcoded enum. Seeded
once from the legacy `InventoryLocation` enum unioned with distinct location
values already present on inventory, then editable by admins. Endpoints
(`backend/src/merlins_collection/routers/admin/locations.py`):
`GET /admin/locations`, `POST /admin/locations`, `DELETE /admin/locations/
{value}` (blocked with 409 if the location is still in use by any item).
Frontend reads it via `useLocations()`; never hardcode a location list in new
code.

# Ops

**Catalog seed + sync (one-time owner action, not scheduled).** The live
`merlins-cards` DynamoDB table currently has an empty card catalog, which is
why market prices show nothing and the Buy page's catalog search returns no
matches — both read from the same catalog. This must be run once, with AWS
creds, from `backend/`, before either will work:

```bash
python scripts/seed_catalog.py --help    # read the rails; it is dry-run by default
python scripts/seed_catalog.py --execute --confirm-table merlins-cards
```

then press **Sync Prices** on `/admin/market`, or run `python scripts/
daily_sync.py`. This is not part of the scheduled daily sync — the daily sync
refreshes prices for cards already in the catalog, it does not seed the
catalog itself.

# Test Commands

| Layer      | Command                                        |
|------------|------------------------------------------------|
| All        | `npm test` (from repo root)                    |
| Frontend   | `npm test --workspace=frontend`                |
| MCP Server | `npm test --workspace=mcp-server`              |
| Backend    | `python -m pytest backend/tests -q --tb=short` |
| Lint (FE)  | `cd frontend && npm run lint`                  |
| Lint (BE)  | `ruff check backend/src`                       |

## Running Tests in Kiro/Cursor (Agent-Specific)

The shell tool (`execute_pwsh`) has a hard ~10-15s effective timeout. Tests
take longer than that, so you MUST use **background processes** to capture
full output.

### Pattern: Start → Wait → Poll

```
# Backend (runs from workspace root — cwd works here)
control_pwsh_process start:
  command: "python -m pytest backend/tests -q --tb=short 2>&1"

# Frontend (use cmd /c wrapper — cwd param is broken for subdirs)
control_pwsh_process start:
  command: cmd /c "cd /d c:\Users\ethar\.cursor\projects\MerlinsCollection-Secondary\frontend & npx vitest run --reporter=verbose" 2>&1

# MCP Server
control_pwsh_process start:
  command: cmd /c "cd /d c:\Users\ethar\.cursor\projects\MerlinsCollection-Secondary\mcp-server & npx vitest run --reporter=verbose" 2>&1
```

Then use `get_process_output` (with `terminalId`) to poll for results.
Wait 30s+ for backend, 15s+ for frontend/mcp before first poll.

### Approximate Runtimes
- Backend: ~10 minutes (1050+ tests)
- Frontend: ~25 seconds (41 test files)
- MCP Server: ~60 seconds

### Quick commands that DO work with execute_pwsh
- `ruff check backend/src` (lint, ~3s)
- `npm run lint --workspace=frontend` (~5s)
- `dir`, `git status`, `type <file>` (instant)

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
