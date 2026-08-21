# Product: Merlin's Minty Cards

Pokemon card business website. Public content pages + authenticated inventory/trading tool.

## Users
- **Collectors** — browse shows, articles, dictionary
- **Business owner (Merlin)** — manage inventory, pricing, trades at card shows via Retool admin panel

## Routes

### Public (route group: `app/(public)/`)
| Route | Page |
|---|---|
| `/` | Home — brand intro, featured cards with 3D flip/tilt effect |
| `/shows` | Card show schedule |
| `/about` | Business story |
| `/dictionary` | Card terminology and grading reference |
| `/articles` | Articles from Sanity CMS |
| `/articles/[slug]` | Individual article (static generation) |

### Authenticated (route group: `app/(auth)/`)
| Route | Page |
|---|---|
| `/inventory` | Inventory search — Filter Mode + Chat Mode |

### Admin (route group: `app/(admin)/`)
| Route | Page |
|---|---|
| `/admin/*` | Admin panel pages |

## Inventory Tool — Two Modes

**Filter Mode:** Dropdowns (set, condition, rarity), price slider, name search → `GET /inventory/search`

**Chat Mode:** Natural language → Claude (Bedrock) → MCP tools → response. Endpoint: `POST /chat`

### MCP Tools (defined in `mcp-server/src/tools/`)
- `get_inventory_summary` — count, value, top cards
- `search_inventory` — filter by name/set/condition/value
- `get_card_price_history` — historical prices
- `calculate_inventory_value` — portfolio breakdown
- `flag_underpriced_cards` — below-market detection

## Admin API (Retool Integration)
Backend router: `backend/src/merlins_collection/routers/admin/`
- Inventory CRUD (create/read/update/delete items)
- Market lookup (TCGdex search, prices, watchlist)
- Sell flow (sessions, fee calc, atomic confirmation)
- Buy flow (sessions, policy calc, item creation)
- Trade engine (state machine, balance/margin, multi-directional)
- Show prep (mispriced detection, bulk location moves)

## Design Identity
- **Color palette:** Spriggatito-inspired (forest greens + cream)
- **Fonts:** Fraunces (serif headings) + Inter (sans body)
- **Key colors:** cream `#f2eede`, forest `#1f6e32`, mint `#a9e0b3`, ink `#241f1b`
- **Dark inventory theme ("vault"):** pine-950 `#06150b` base with mint accents
- **Brand images:** `frontend/public/images/` (logo/, brand/, shows/, cards/)

## Current Focus
- Retool admin API (Phases 1-6 done, 7-8 remaining: photo upload + analytics)
- Database redesign for multilingual catalog (TCGdex), graded variants, condition pricing
- Active branch: `retool-admin-api` (based on `Polishing-For-Deployment`)
