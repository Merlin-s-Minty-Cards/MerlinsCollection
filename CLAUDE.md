# TDD Guidelines
Always follow the outside-in Test-Driven Development (TDD) process.
1. RED: Write failing tests first. Do NOT implement the feature.
2. GREEN: Write minimal code to make the tests pass.
3. REFACTOR: Improve code quality, ensuring tests remain green.
Never combine phases. Wait for user confirmation after confirming tests fail.

# Agent Workflow
Development stays in the main thread — no subagent-driven orchestration. Custom skills live in `.claude/skills/`; the two remaining custom agents (`.claude/agents/test-qa.md`, `.claude/agents/web-browser.md`) exist only because their output is long-running or heavy and belongs off the main thread, not because they get orchestrated.

For **non-trivial feature work** (new functionality, multi-step changes, anything touching more than a couple of files), default to this flow without waiting to be asked:
1. `initialize-roadmap` skill — audit the workspace, create/update `claude-progress.txt`, unless one already exists and is current for the active feature.
2. `design-doc` skill for architecture/schema/contract design on substantial features.
3. `tdd` skill for implementation — it nests `adversarial-review` as an inline pre- and post-change critique step (logic, security, chaos, bloat), no subagent spawn.
4. `sync-docs` then `pr-description` skills to close out.
5. `test-qa` and `web-browser` agents dispatch only when their isolation is actually needed (a long test run, heavy research output).

Skip this default for small fixes, one-off questions, or anything the user frames as quick — go straight to the relevant skill (or none) instead. The user can also override explicitly at any time (e.g. "skip the roadmap step", "just write the code").

**Closing the loop is a separate, always-on concern, not part of the feature flow above.** `lesson-capture` fires whenever the user reports that something Claude built or decided fell short, or Claude itself notices it took a long or circuitous path a clearer rule would have avoided — it writes the generalized lesson (never a narrow one-off fix) to CLAUDE.md or a skill, gated on the lesson actually generalizing. `skill-curator` is the periodic, hand-run counterpart that reviews `.claude/skills/` for drift — near-duplicates to merge, bloated skills to split, over-narrow entries that slipped past the gate. Any skill file either one touches goes through `writing-great-skills`, never `superpowers:writing-skills`.

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
| `/admin`               | Dashboard      | Quick actions, needs-attention queues, position, today, coverage |
| `/admin/inventory`     | Inventory      | Inventory CRUD, granular filters, ownership column |
| `/admin/sell`          | Sell           | Sale flow, large image preview        |
| `/admin/buy`           | Buy            | Purchase flow, catalog-linked autocomplete, manual-entry mode |
| `/admin/slabs`         | Slabs          | Graded intake (manual/wedge-scan cert → staged batch → commit) + the slab list. See "Slabs" below |
| `/admin/trade`         | Trade          | Trade flow — Coming In / Going Out, basis modes (see below) |
| `/admin/vault`         | Vault          | Sortable inventory table, ownership column |
| `/admin/market`        | Market         | Prices, sync trigger, coverage/confidence, "check for new sets" |
| `/admin/show-prep`     | Show Prep      | Bulk-move to a show location, inline sticker/TCG-link editing |
| `/admin/shows`         | Shows          | Show CRUD — see "Shows" below         |
| `/admin/outgoing`      | **Prep Queue** | See "Prep Queue" below — route path is unchanged, the UI/purpose is not |
| `/admin/triage`        | Triage         | See "Triage" below — the `needs_review` queue + the two repair tools |
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

**Triage** (`/admin/triage`) — the one place to correct data the automation got
wrong. It **is** the `needs_review` queue, not a second flag: "Send to Triage"
sets `needs_review = True`. Two things were added to that bare boolean —
`review_reason` (why; **internal**, deliberately NOT in `_CUSTOMER_ITEM_FIELDS`)
and `reviewed_at` (stamped server-side when an admin clears the flag, so
automation cannot re-flag what a human already passed).

One list, with a chip per reason — items routinely qualify under several at once:

| Reason | Kind | Cleared by |
|---|---|---|
| `flagged` | stored `needs_review` | an admin, explicitly |
| `missing_card_id` | derived: no catalog link | self-healing — re-point the card |
| `missing_english_name` | derived: JP item, no `display_name_override` | self-healing — assign a name |

The list is `GET /admin/inventory/search?triage=true` (the one OR on that
endpoint), **not** a parallel endpoint; `GET /admin/triage/counts` backs the
sidebar badge. "Send to Triage" lives in `CardDetailModal`, so it reaches the
six pages that mount it (inventory, outgoing, sell, show-prep, vault, triage).
The row-level quick action with undo (`TriageRowAction`) is on **Prep Queue
only**. Buy, Trade, Market, History, Cosigners and `/admin/card/[id]` do not
mount the modal and have **no** send-to-triage path at all — the "every tab"
goal is not met yet; see `docs/plans/rfc-0008/follow-ups.md` (T5 row 1).

`display_name_override` is editable **only from the Triage page**, not from
`CardDetailModal` — the modal's "Display Name" row still edits `display_name`,
the import-materialized fallback, which is a silent no-op on a catalog-matched
item (follow-ups.md, T10 row 3).

**The one rule that must not be broken:** assigning an English display name
writes `display_name_override` and **never** `card_id`. Re-pointing a card is a
separate, confirmed action with a before/after diff and warnings for trade
lineage and cross-language links.

**Slabs** (`/admin/slabs`, sidebar position: **between Buy and Trade**) — graded
intake and the slab list, from RFC 0009. Intake is one cert field serving both a
keyboard-wedge scanner and the keyboard (Enter *advances*, never submits), a
catalog-autocomplete card picker with a free-text fallback, a client-side staging
batch, then a commit that runs the ordinary buy session's create → items →
confirm. `GET /admin/slabs/certs/{cert}` warns on a cert already owned — a
**warning with override**, never a gate, because a slab sold and bought back is a
legitimate re-entry. `/admin/slabs?priced=false` is the unpriced worklist. The
per-grade pricing behind it is documented under "Third-Party APIs" below.

**The intake toolbar has four buttons, and two of them are deliberately dead.**
"Manual entry" is a disclosure — the form is **put away by default**, like the
other admin tabs, and stays open across adds because intake is a batch workflow.
"Scan cert" is **real**: it opens the form, focuses the cert field and shows a
"waiting for scan" state, which is all a wedge scanner needs (it is just a fast
keyboard). "Camera scan" and "Auto-fill from cert" are rendered **disabled with
`aria-describedby` naming PSA approval as the blocker** — they are placeholders on
purpose, so the gap reads as known rather than forgotten. Do not try to implement
either: PSA 403s at the **account**, re-confirmed 2026-08-10 against their Swagger
with both bearer spellings (see "Third-Party APIs").

The page uses the **vault design system** (`vault-panel`, `vault-field`,
`text-pine-*`, `bg-mint/15`) like every other admin tab. It previously used none
of it, which is why its dropdowns rendered light-green-on-white: the admin theme
is dark (`.vault-scope`, `#06150b`) with light-green text, so an unstyled
`<select>` inherited the theme's text colour over the browser's default white
background. **Never ship an admin control without `vault-field`.**

Two gaps remain live and deliberate — **no per-row editing in the staging table**
(so its commit gating is unbuilt on purpose) and **no pin control**. Full list:
`docs/plans/rfc-0009/follow-ups.md`.

**Shows** (`/admin/shows`) — CRUD for show/event days. Note this is a
*different page* from Show Prep (`/admin/show-prep`, which moves inventory into
show boxes) and from Show Analytics' Shows tab (`/admin/analytics`, which reads
per-show numbers). Routes live in `routers/admin/analytics.py`, not a new
module: `GET/POST /admin/shows`, `PUT /admin/shows/{id}`,
`POST /admin/shows/{id}/archive` and `/unarchive`.

**"Delete" is an archive, by owner decision** (RFC 0008 Q6). `Show.archived`
is a boolean; nothing is ever destroyed, so there is no repo-level show delete
and **no 409 in-use guard** — a show with transactions behind it archives like
any other, and its analytics snapshot never dangles. `GET /admin/shows` hides
archived shows unless `?include_archived=true`; `repo.list_shows()` and
`repo.get_show()` stay archive-agnostic so `/shows/{id}/analytics` keeps
resolving for an archived show.

**`put_show` gotcha:** the SK embeds the show DATE and, during an import, the
generation. Both move underneath an ordinary admin edit, so `put_show` now
sweeps superseded rows for the same `show_id` after writing — otherwise
rescheduling a show, or editing any import-created show, forks it into two
rows. The sweep is skipped mid-import, where coexisting generations are the
whole point of load-then-swap.

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

**Customer prices are CONDITION-ADJUSTED.** The catalog relays one market
figure per finish and that figure is a **Near Mint** price. Every
customer-facing surface scales it by the item's condition
(`services/condition_pricing.py` — LP ×0.82, MP ×0.58, HP ×0.33, DMG ×0.15,
`+`/`-` take the midpoint with the neighbouring tier). Before this, a DMG card
was shown to a buyer at **~6.7× what the business valued it at**, wrong in the
business's favour. Measured on live stock 2026-08-06: this moved the
customer-visible total from **$6,143 to $5,005 (−18.5%)** across 73 of 228
items.

**The adjustment is applied in exactly ONE place per surface — do not add a
second.** `_condition_adjust` in `routers/inventory.py` rewrites
`summary.market_price` at enrichment, so the tile, the sort and the price bound
all inherit the same number (this is what keeps RFC 0008 T1's single-authority
invariant). `/inventory/summary` applies it to its **live** branch only, and MCP
mirrors both via `mcp-server/src/condition-pricing.ts`. The stored
`current_market_value` already has the multiplier baked in by the nightly
denormalizer — **adjusting that would apply it twice.**

**Name resolution: `display_name_override` wins EVERYWHERE.** One rule, four
implementations, kept deliberately in sync — `itemTitle`
(`frontend/lib/inventory.ts`, customer tiles), `adminItemName`
(`frontend/lib/admin-item-name.ts`, every admin list), `admin_item_name`
(`backend/services/card_text.py`, admin API responses) and MCP's `toCard`
(chat). Never inline `display_name || product_name` in new code; call the
helper. `CardDetailModal` shows **both** name fields, since editing
`display_name` on a catalog-matched item is a silent no-op.

**Card art: import the size, never re-pick it.** `TABLE_THUMB_SIZE` (`xs`,
56×78 — real card proportions) and `TABLE_THUMB_COLUMN` (`w-16`) are exported
from `components/admin/shared/CardImage.tsx`. Every admin list row uses them.
Hand-picking a size per page is what went wrong before: Inventory, Vault and
Show Prep each chose `md` (160×224) while Prep Queue chose `lg` (224×320), and
their columns disagreed too, so every one of them rendered an image several
times wider than its own cell.

Art now appears on Inventory, Vault, Show Prep, Prep Queue (behind each page's
`ImageToggle`) and — always on, no toggle, because the list is short and
identifying the card *is* the task — Triage, History (search hits, the item
header, and every trade-lineage node) and Trade (both staged legs). All of them
resolve through `useCardImages`, which batches the lookup and, since
2026-08-07, **attempts each id once**: callers pass a freshly-mapped array so
the hook's effect re-runs every render, and re-queueing failed ids meant one
POST per keystroke on Trade. A failed or card-less id renders the placeholder.

**Model fields added by RFC 0008.** On `InventoryItem`:
`display_name_override` (admin-typed English name; **customer-facing**, bounded
200 chars, outranks the catalog name — nothing in sync/import ever writes it),
`review_reason` (**internal**, bounded 500 chars, must stay out of
`_CUSTOMER_ITEM_FIELDS`), and `reviewed_at` (server-stamped on clear). On
`Show`: `archived` (bool). Plus a new `catalog_set` entity backing
`GET /admin/catalog/sets`.

There is **no `name_en` and no `dex_number`.** The RFC originally specified an
automated `dexId`/Pokédex-map pipeline for Japanese names; the owner dropped it
on 2026-08-05 in favour of the hands-on `display_name_override` above. If a doc
or comment still claims those fields exist, it is stale — the pipeline was never
built.

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

**The catalog is NOT empty.** An earlier version of this file claimed the live
`merlins-cards` table had an empty card catalog and that this was why market
prices and the Buy page's catalog search came back blank. **That was wrong** —
measured 2026-08-05, the table holds **31,603 catalog rows**. The real cause was
performance, not missing data: `GET /admin/market/search` has no index on card
name, so every keystroke triggered a full-table scan — 11.7 MB over 12
sequential 1 MB pages, **11.2 seconds per request**, on a 300ms debounce. RFC
0008 T9 fixed it with an in-process catalog cache
(`services/catalog_cache.py`); read that module's docstring before touching it,
especially the ~93 MB resident sizing note. Do not go looking for missing data
here — this dead end has already cost one investigation.

**The ECS task role must grant `dynamodb:Scan` and `dynamodb:UpdateItem`.**
Diagnosed 2026-08-07 from CloudWatch: catalog search was returning **HTTP 500**
on the live site, not failing to connect. `merlins-backend-task-role` had
neither action on `table/merlins-cards`, so everything routed through
`_scan_catalog` died — `GET /admin/market/search`, `GET /admin/market/coverage`,
and (via `upsert_catalog_card_preserving_prices`) the price sync. The catalog
cache T9 added is what introduced the Scan dependency; the policy was never
updated to match. `deploy/backend-task-role-permissions.json` is the source of
truth — apply it with `aws iam put-role-policy` (no ECS redeploy needed, task
roles are read per request). **A blank catalog dropdown is far more likely to be
this than missing data.**

**Never write a bare `float` to DynamoDB.** boto3 rejects it outright
("Float types are not supported"), and `_serialize`
(`services/dynamodb.py`) is the one place that coerces `float` → `Decimal`,
via `str()` so a price still round-trips. This matters because the sell/buy/
trade session routers persist **raw request JSON**, where a price arrives as a
float — `POST /admin/sales/{id}/items` 500'd in production for exactly this
reason. Tests missed it for months because they all send prices as **strings**;
when testing a money path, send a JSON **number**, which is what the frontend
actually sends.

**Catalog seed + sync (one-time owner action, not scheduled).** Needed only for
a fresh/empty table, which the live one is not. With AWS creds, from `backend/`:

```bash
cd backend
../.venv/Scripts/python.exe scripts/seed_catalog.py --help    # dry-run by default
../.venv/Scripts/python.exe scripts/seed_catalog.py --execute --confirm-table merlins-cards
```

then press **Sync Prices** on `/admin/market`, or run `scripts/daily_sync.py`
the same way. This is not part of the scheduled daily sync — the daily sync
refreshes prices for cards already in the catalog, it does not seed the
catalog itself.

**Every script here needs the venv interpreter spelled out.** A bare `python`
resolves to an unrelated environment that cannot import `merlins_collection`,
and these files have no shebang — so `scripts/foo.py` hands the file to the
shell, which tries to run its docstring as commands.

**Catalog set registry backfill (one-time owner action).** The admin
inventory page's Set filter lists every set in the catalog — including ones we
own nothing from, which is the whole point of it — from a `catalog_set`
registry rather than from a full catalog scan. `sync_new_sets` (the **check
for new sets** button on `/admin/market`) maintains that registry going
forward, but it deliberately never walks a set that already has cards, so it
will not backfill a catalog seeded before the registry existed.

**DONE — run against `merlins-cards` on 2026-08-06**, registering **284 sets**
from 31,603 card rows; `GET /admin/catalog/sets` now returns all 284, of which
94 have owned cards. Re-running is a harmless upsert that refreshes the counts:

```bash
cd backend
../.venv/Scripts/python.exe scripts/backfill_catalog_sets.py            # DRY RUN
../.venv/Scripts/python.exe scripts/backfill_catalog_sets.py --execute
```

Until it has run, `GET /admin/catalog/sets` honestly returns `[]` and the Set
dropdown is empty. This is the one place a full catalog scan is acceptable —
offline, once, from a CLI; never on a request path.

# Test Commands

| Layer      | Command                                        |
|------------|------------------------------------------------|
| All        | `npm test` (from repo root)                    |
| Frontend   | `npm test --workspace=frontend`                |
| MCP Server | `npm test --workspace=mcp-server`              |
| Backend    | `./.venv/Scripts/python.exe -m pytest backend/tests -q --tb=short` |
| Lint (FE)  | `cd frontend && npm run lint`                  |
| Lint (BE)  | `./.venv/Scripts/python.exe -m ruff check backend/src` |

**Use `./.venv/Scripts/python.exe` explicitly, not bare `python`.** The `python`
on PATH resolves to an unrelated hermes-agent venv with no pytest and no ruff
installed, so the bare form fails with "No module named pytest". This checkout
is also a git worktree, and a global editable install can make Python import the
**sibling** repo's backend — if results look impossible, check which package
actually loaded before debugging anything else:

```bash
./.venv/Scripts/python.exe -c "import merlins_collection,os;print(os.path.dirname(merlins_collection.__file__))"
```

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
Measured 2026-08-07, after the fixture rework below:
- Backend: **~2 minutes** (1369 tests, 52 files) — was ~10 minutes
- Frontend: **~31 seconds** (545 tests, 73 files)
- MCP Server: **~1 second** (98 tests, 7 files)

**Do not reintroduce a per-test `mock_aws()`.** The backend suite spent **93% of
its wall time in fixture setup** until 2026-08-07. Entering a fresh `mock_aws()`
invalidates botocore's service-model caches, so the next
`boto3.resource("dynamodb")` pays a full model reload — measured **507ms** per
test to build the repo + table that way versus **15ms** inside a long-lived
mock. `tests/conftest.py` now starts **one** `mock_aws()` for the session and an
autouse `_clean_aws` fixture resets the moto DynamoDB backend between tests,
which wipes every table exactly as leaving the old context did. Isolation is
verified: a probe that wrote rows in one test and asserted an empty table in the
next goes red if the reset is removed. The RSA signing key is session-scoped for
the same reason (2048-bit keygen is ~53ms, and ~700 tests take a token).

Anything creating a table must depend on `_clean_aws` **explicitly**, not rely
on autouse ordering — nothing else drops a table now that the mock outlives the
test, so a second `create_table` with the same name raises `ResourceInUseException`.

Frontend: the ~20 pure-logic test files carry `// @vitest-environment node`,
since constructing a jsdom per file was the suite's largest single cost.
`vitest.setup.ts` guards its DOM work behind `HAS_DOM` and imports
testing-library dynamically — keep both if you add a setup step.

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

# Third-Party APIs

Authority: [`docs/rfcs/0009-slab-intake-and-graded-pricing.md`](docs/rfcs/0009-slab-intake-and-graded-pricing.md),
with per-task status in [`docs/plans/rfc-0009/progress.md`](docs/plans/rfc-0009/progress.md).
An earlier version of this section pointed at "claude-progress.txt Phase 4" — that
file has no Phase 4 and never will; the admin-enhancement rounds replaced it.

**Slab intake is MANUAL-FIRST, and that is the shipped design, not a stopgap.**
An admin types (or wedge-scans) the cert number, identifies the card through
catalog autocomplete with a free-text fallback, types company/grade/cost, stages
a batch and commits it through the existing buy session — so slabs land in
purchase history, timeline and show analytics like any other acquisition. There
is **no camera** (never built) and **no cert lookup** (see PSA below). Every
grading company goes down the same manual path; CGC/BGS/SGC are not a special
case any more.

- **PokemonPriceTracker — the graded price source, and the one that is LIVE.**
  Per-grade market values from eBay sold comps. Not PriceCharting: the owner
  declined a paid subscription on 2026-08-07, and any doc still naming
  PriceCharting is stale. Free tier is **100 credits per UTC day**, and a graded
  lookup costs **2 credits** (1 card + 1 `includeEbay`, `costPerCard: 2` read off
  a live response) — so the real ceiling is **FIFTY lookups a day**. You are
  billed on `limit` **even when the search matches zero cards**, which is why
  `limit=1` is pinned. Key: `POKEMONPRICETRACKER_API_KEY`; budget knob:
  `PRICING_DAILY_QUOTA` (credits, default 100).
- **PSA cert API — has NEVER been called successfully. Do not build on it.**
  Every authenticated call returns `403 {"Message":"Access to this API is limited
  to approved customers."}`: the key is valid, the **account is not entitled**,
  and no code change reaches it. The remedy is an approval email to
  `collectors-apis@collectors.com`. Nothing about its response shape has ever
  been observed, so the mapper (RFC 0009 T2) is deferred whole rather than
  guessed at, and **`PSA_API_KEY` is read by no code** — there is no `psa_api_key`
  field on `Settings`, so setting it today does nothing. When approval lands, PSA
  returns as a **pre-fill** for the manual form, never a prerequisite. It will
  supply identity only: **`TotalPopulation`/`PopulationHigher` are always `null`**
  on the public API, so there is no population feature and no field for one.

**How a slab gets priced** (`services/slab/pricing.py`, wired by
`services/catalog_sync.py`):

- Prices live in the **pre-existing** `CARD#<card_id>` / `GRADEDPRICE#<company>#
  <grade>` rows. RFC 0009 added **no pricing schema** — the work was filling those
  rows from an API instead of by hand.
- `refresh_graded_prices` runs **nightly inside `run_daily_sync`** (step 3 of
  five) and also behind `POST /admin/slabs/refresh-prices` and the Market page's
  Sync Prices button. It walks owned slabs **stalest-first** (never-priced first),
  deduped by `(card_id, company, grade)`, capped at what today's credits can pay
  for. **It never calls PSA** — a cert's identity is immutable.
- **A price attaches only on a VERIFIED JOIN**: the vendor's `externalCatalogId`,
  read as `en:<id>`, must equal the item's own `card_id`. The vendor's name search
  returns the wrong card roughly a third of the time and a wrong answer looks
  exactly like a right one, so this rule is load-bearing. Japanese cards carry no
  `externalCatalogId` at all, so **JP slabs are unpriceable by construction** and
  are *not* Triage-flagged for it — they surface at `/admin/slabs?priced=false`.
- **A hand-typed graded price is REPLACED by the provider unless it is pinned**
  (owner decision, 2026-08-09). `PUT /admin/slabs/{id}/price/pin` sets the pin —
  but **no frontend control calls it yet**, so in practice nothing is pinned and
  the provider always wins. Anyone typing a graded value today should know it will
  be overwritten on the next run.

Both keys are bearer tokens spending a metered daily quota: never log one, never
return one from an endpoint. Real values live in `backend/.env` (gitignored) and,
in production, in **ECS secrets** — never a task-definition literal. An empty key
is a supported state: `build_pricing_provider()` returns `None`, the nightly job
skips graded pricing and every other step still runs, while the admin button
reports `state: "failed"` because a human is standing there waiting.

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
