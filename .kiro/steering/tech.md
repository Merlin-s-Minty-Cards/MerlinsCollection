# Technical Architecture — Merlin's Minty Cards

## Stack Overview

| Layer | Language | Framework / Service |
|---|---|---|
| Frontend | TypeScript | Next.js 14 (App Router), Tailwind CSS, NextAuth.js |
| Backend API | Python 3.12 | FastAPI, pydantic-settings, boto3 |
| MCP Server | TypeScript | MCP SDK |
| CMS | — | Sanity |
| Database | — | AWS DynamoDB |
| Auth | — | AWS Cognito (via NextAuth.js) |
| AI | — | AWS Bedrock (Claude) |
| CDN/Storage | — | AWS CloudFront + S3 |

## AWS Services Used
- **S3** — card images, export files
- **CloudFront** — CDN for images and static assets
- **DynamoDB** — inventory and catalog storage
- **Lambda** — price lookup, image processing
- **API Gateway** — HTTP routing to backend
- **Cognito** — user authentication pools
- **Rekognition** — future: card photo identification
- **Bedrock** — Claude AI for chat mode

## Monorepo Setup
npm workspaces monorepo. Root `package.json` orchestrates frontend, mcp-server, and shared packages.

## Test Commands
| Scope | Command |
|---|---|
| All | `npm test` (repo root) |
| Frontend | `npm test --workspace=frontend` |
| MCP Server | `npm test --workspace=mcp-server` |
| Backend | `python -m pytest backend/tests -q --tb=short` |
| Lint (FE) | `cd frontend && npm run lint` |
| Lint (BE) | `ruff check backend/src` |

## TDD Process (Mandatory)
1. **RED** — Write failing tests first
2. **GREEN** — Minimal code to pass
3. **REFACTOR** — Improve quality, tests stay green

Never combine phases. Every behavioral change requires outside-in TDD.

## Key Backend Patterns
- Pydantic models split into: `models/catalog/`, `models/inventory/`, `models/business/`
- Services: `tcgdex` (external API), `dynamodb` (data access), `catalog_sync`, `spreadsheet_import`
- Routers: `inventory`, `public`, `chat`, `auth`, `health`
- CLI scripts in `backend/scripts/` for seeding, importing, syncing

## Key Frontend Patterns
- Next.js 14 App Router with file-based routing
- Server components by default; client components marked with `"use client"`
- Sanity integration for article content (GROQ queries)
- NextAuth.js wrapping AWS Cognito for session management

## Database Design
DynamoDB single-table design (being redesigned for multilingual catalog support via TCGdex, graded card variants, condition-aware pricing).

## Branch Strategy
- PRs required for all changes to main
- CI must pass (GitHub Actions: `.github/workflows/ci.yml`)
- CODEOWNERS review enforced
- Current active branch: `Database-Redesign-Second-Round`
