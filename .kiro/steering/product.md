# Product Context — Merlin's Minty Cards

## What It Is
A Pokemon card business website combining public-facing content pages with an authenticated inventory management and search tool.

## Target Users
- **Collectors** browsing the public site for show schedules, articles, and the Collectors Dictionary
- **Business owner** (Merlin) managing inventory, pricing, and card valuations via the authenticated tool

## Public Pages
| Route | Purpose |
|---|---|
| `/` | Home — brand intro, highlights, featured cards |
| `/shows` | Upcoming and past card show events |
| `/about` | Business story, team, contact info |
| `/dictionary` | Collectors Dictionary — reference for card terminology and grading |
| `/articles` | Article listing from Sanity CMS |
| `/articles/[slug]` | Individual article (statically generated) |

## Authenticated Tool — Inventory Search (`/inventory`)
Two interaction modes behind login:

### Filter Mode
Structured search with dropdowns (set, condition, rarity), price range slider, and name search. Calls `GET /inventory/search`.

### Chat Mode
Natural language queries processed by Claude (AWS Bedrock) using MCP tools. User types plain English; AI interprets intent and calls inventory tools. Endpoint: `POST /chat`.

### MCP Tools Available to Chat
- `get_inventory_summary` — total count, value, top cards
- `search_inventory` — filter by name, set, condition, value range
- `get_card_price_history` — historical price data for a card
- `calculate_inventory_value` — full portfolio valuation breakdown
- `flag_underpriced_cards` — cards priced below market threshold

## Content Management
Articles are authored in Sanity CMS and rendered via Next.js static generation.

## Design Identity
- Color scheme inspired by Spriggatito (forest greens, cream whites)
- Business brand images organized under `frontend/public/images/`

## Current Focus
Database redesign supporting multilingual catalog (TCGdex), graded card variants, and condition-aware pricing.
