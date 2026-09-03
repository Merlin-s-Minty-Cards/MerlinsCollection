# Merlin's Collection — Backend API

FastAPI service powering the authenticated inventory tool for Merlin's Minty Cards.
It serves the `/inventory` search experience (filter mode) and the AI chat mode,
backed by AWS Cognito (auth), DynamoDB (inventory + catalog), and Bedrock (Claude).

## Package layout

```
src/merlins_collection/
  main.py            # FastAPI app: creates `app`, mounts the routers
  config.py          # Pydantic `Settings` loaded from env / .env
  dependencies.py    # FastAPI dependency providers (auth, repo, bedrock)
  models/            # Pydantic DTOs (request/response + domain shapes)
    auth.py          #   AuthenticatedUser
    inventory.py     #   Raw/Graded inventory items (discriminated union)
    catalog.py       #   CatalogCard + PricePoint (TCGdex-derived, USD)
    chat.py          #   ChatRequest / ChatResponse
  routers/           # HTTP layer — thin, delegates to services
    auth.py          #   GET /auth/me
    inventory.py     #   GET /inventory/search, GET /inventory/summary, GET /inventory/facets
    chat.py          #   POST /chat/
    public.py        #   GET /public/shows, GET /public/featured-cards (unauthenticated)
    health.py        #   GET /health
    admin/           #   /admin/* — Retool admin panel (inventory, sales, buys, trades, show prep, market)
  services/          # Business logic / integrations (no FastAPI imports)
    cognito.py       #   Cognito JWT verification
    dynamodb.py      #   Single-table DynamoDB repository
    tcgdex.py        #   TCGdex v2 HTTP client + mapping
    catalog_sync.py  #   Daily catalog/price sync orchestration
    bedrock.py       #   Bedrock Converse chat loop with MCP tools
tests/               # Pytest suite mirroring the src/ tree
```

The dependency direction is one-way: `routers → services → models`. Services never
import from `routers`, which keeps the business logic unit-testable without HTTP.

## Running it

```bash
# Install (editable, with dev extras) from backend/
pip install -e ".[dev]"

# Run the API locally
uvicorn merlins_collection.main:app --reload

# Tests + lint (run from the repo root)
python -m pytest backend/tests -q --tb=short
ruff check backend/src
```

Interactive API docs are served at `/docs` once the app is running.

## Configuration

All settings live in `config.py` (`Settings`) and are read from environment
variables or a `.env` file. Unset values fall back to the defaults below; AWS
credentials are normally supplied by the ambient credential chain (IAM role,
`~/.aws`, or env) rather than hard-coded here.

| Setting | Env var | Default |
|---------|---------|---------|
| AWS region | `AWS_REGION` | `us-east-1` |
| Cognito user pool id | `COGNITO_USER_POOL_ID` | `""` |
| Cognito app client id | `COGNITO_CLIENT_ID` | `""` |
| DynamoDB table | `DYNAMODB_TABLE_NAME` | `merlins-cards` |
| Bedrock model id | `BEDROCK_MODEL_ID` | Claude 3.5 Sonnet |
| MCP server path | `MCP_SERVER_PATH` | `../mcp-server/dist/index.js` |
| EUR->USD rate | `EUR_USD_RATE` | `1.08` |
| Catalog price staleness threshold | `CATALOG_PRICE_STALE_DAYS` | `30` |
| Graded-pricing API key | `POKEMONPRICETRACKER_API_KEY` | `""` (disables graded pricing) |
| Graded-pricing daily budget, in **credits** | `PRICING_DAILY_QUOTA` | `100` (= **50** lookups, at 2 credits each) |

**There is no `PSA_API_KEY`, and there will not be one.** It was removed from
`.env.example` by RFC 0010 T14: it is not a `Settings` field, `extra="ignore"`
swallows the env var, and the cert lookup (RFC 0009 T2) is **WON'T DO** — PSA's
API became paid and the owner declined it on 2026-08-10 (RFC 0010 §H). A blank
placeholder for a setting nothing reads is how an operator comes to believe cert
lookup is configured.

## Authentication

Every protected route depends on `get_current_user`, which reads a `Bearer`
token and validates it with `CognitoJwtVerifier`. We verify **Cognito access
tokens** (not ID tokens): RS256 signature against the pool's JWKS, issuer,
expiry (with 60s clock-skew leeway), `token_use == "access"`, and a strict
`client_id` match. Admin status comes from the `cognito:groups` claim.

The status codes are deliberate and distinguish *whose* problem it is:

| Code | Meaning |
|------|---------|
| 401 | Missing / malformed / invalid token (the client's problem) |
| 403 | Valid token, but not an admin (`require_admin` routes) |
| 503 | Signing keys couldn't be fetched (our infrastructure problem) |

`require_admin` builds on `get_current_user` for admin-only routes.

## HTTP endpoints

| Method & path | Auth | Purpose |
|---------------|------|---------|
| `GET /auth/me` | Bearer | Identity + role of the caller |
| `GET /inventory/search` | Bearer | Filter inventory by name/set/rarity/condition/price |
| `GET /inventory/summary` | Bearer | Dashboard header stats (`cards_in_vault`, `sets_tracked` — `est_value` was removed, RFC 0025 T5) |
| `GET /inventory/facets` | Bearer | Distinct sets/rarities/conditions/languages for filter dropdowns |
| `POST /chat/` | Bearer | Natural-language inventory chat via Bedrock; takes `conversation_id`, returns it + `title` |
| `GET /chat/conversations` | Bearer | The caller's own threads, ≤50, `updated_at` descending |
| `GET /chat/conversations/{id}` | Bearer | One transcript (≤200 messages) + live-rehydrated panel |
| `PATCH /chat/conversations/{id}` | Bearer | Rename a thread (does not touch `updated_at`) |
| `DELETE /chat/conversations/{id}` | Bearer | Hard delete one thread (204) |
| `DELETE /chat/conversations` | Bearer | Delete every thread the caller owns (204) |
| `GET /public/shows` | **None** | All shows split into `upcoming`/`past` by the business's Pacific "today" |
| `GET /public/featured-cards` | **None** | Up to 5 homepage cards (`name` + `image_url` only) |
| `GET /admin/*` | Admin | Retool admin panel (inventory CRUD, sales, buys, trades, show prep, market) |

### `/admin/slabs` — graded intake and pricing (RFC 0009)

`routers/admin/slabs.py`. Admin-only like the rest of `/admin/*` (the auth
dependency is on `admin_router`, not re-declared per route).

| Method & path | Purpose |
|---------------|---------|
| `GET /admin/slabs/certs/{cert}?company=PSA` | "Do I already own this cert?" — a point read on the `CERT#` pointer row, **not** a search. **"Not owned" is a `200 {"owned": false}`, never a 404**, and the answer is a warning with override (RFC 0009 §9), never a gate |
| `GET /admin/slabs` | The graded stock list, joined to each slab's `GRADEDPRICE#` value. Filters: `company`, `grade`, `status`, `priced`, `limit`. `priced=false` is the **unpriced worklist** — the only place an unjoinable slab surfaces, since it is deliberately not Triage-flagged |
| `POST /admin/slabs/refresh-prices` | Kicks off `refresh_graded_prices` in the background; `202` + `{"state": "started"}`. **`409` while one is already running** — not politeness, money: each run can spend the whole day's credits |
| `GET /admin/slabs/refresh-prices/status` | Poll the current/most recent run. Reports `state`, counts and `credits_remaining`. **`state: "failed"` when no key is configured** — the opposite of the nightly job, which degrades quietly |
| `PUT /admin/slabs/{item_id}/price/pin` | `{"pinned": bool}` — protect this slab's stored price from the nightly provider pass, or release it. `404` if the item, its `card_id` or its price row is missing (a pin is a promise about a *specific* figure); `400` for a non-graded item. **No frontend control calls this yet**, so nothing is pinned in practice |

There is **no** `/admin/slabs/lookup/{cert}`. RFC 0009 §7 specifies one, but it
would be a PSA mapper with nothing to map (see External integrations below), and
manual intake needs no such endpoint — catalog search and the duplicate check
already exist.

`/inventory/search` loads inventory and filters in-process; `cost_basis`
(our purchase price) is stripped from the response and never reaches customers.
Filters run cheapest-first, with one deliberate exception: a `min_price`/
`max_price` bound is applied **last**, after every other filter. The response
carries `hidden_no_price` — the count of otherwise-matching items excluded
purely because they have no resolvable price (an unpriced item can't honestly
be claimed to fall inside a price range). Running the price bound last is what
makes that count meaningful: it reflects only what the price bound itself hid,
not items some earlier filter had already ruled out. `hidden_no_price` is
always `0` when no price bound is set. See the `search_inventory` module
docstring in `routers/inventory.py` for the full ordering rationale.

### The customer-visible cohort

`/inventory/search`, `/inventory/summary`, and the anonymous `/public/featured-cards`
all read the exact same set of items: **available** (not sold/held) items of a
**customer-visible kind** (`raw` or `graded` — bulk lots and sealed product are
internal-only per RFC 0001). This predicate lives in exactly one place,
`customer_visible_items()` in `routers/inventory.py`, and is imported by
`routers/public.py` rather than re-implemented — a future exclusion (e.g. a
`needs_review` gate) is then added once and can never drift between the
authenticated and anonymous surfaces. `/inventory/summary` reuses the same
`rate_limit_search` cap as `/inventory/search` since it does an equally heavy
full inventory scan + catalog batch-get.

### `/public/*` — the unauthenticated read surface

`GET /public/shows` and `GET /public/featured-cards` (`routers/public.py`) are
the two routes a signed-out visitor's browser calls (home page, `/shows`).
Both:

- Expose **purpose-built response models** (`PublicShow`, `FeaturedCard`) that
  contain only safe fields by construction — internal `Show`/inventory fields
  are never on the model at all, so a field added upstream later can't leak
  through it.
- Are capped per client IP by `rate_limit_public` (fails open — these are
  cheap reads; the cap blunts a burst, not a correctness gate).
- Share an in-process, single-flight, 300-second TTL cache (`_TTLCache`) that
  coalesces a *concurrent* burst in a cold/just-expired window to one DynamoDB
  scan and serves the last-known-good value if a recompute fails. This
  suppresses a thundering herd, not a sustained brownout: after a failed
  recompute the next request retries immediately (serialized behind the lock,
  never concurrently, but with no backoff) until a scan succeeds.

`/public/shows` splits shows into `upcoming`/`past` using the business's
**Pacific** "today" (`America/Los_Angeles`, via the `tzdata` package — needed
because production runs on UTC and a same-day show would otherwise misfile as
"past" for the last several hours of every show day). A show dated today
counts as upcoming. `venue`/`city` are optional on `Show` and may be `null`.

`/public/featured-cards` ranks the customer-visible cohort by
`current_market_value ?? listed_price ?? 0` (market-value-first; unpriced items
rank last rather than being excluded), keeps only items whose catalog image
is an `https://images.pokemontcg.io/...` URL, de-duplicates by `card_id`, and
returns the top 5. This ranking helper (`_market_first`) is intentionally
separate from `/inventory/search`'s price filter (`_price`, which since Phase
12 returns `current_market_value` outright with no `listed_price` fallback,
since `listed_price` is null on every item by owner decision) — one ranks for
display, the other excludes for a price bound, and they are allowed to diverge.

## DynamoDB single-table design

All entities share one table (default `merlins-cards`) with a composite primary
key (`PK`/`SK`) and one global secondary index (`GSI1` with `GSI1PK`/`GSI1SK`).
Each item carries an `entity` attribute tagging its type. The repository
(`services/dynamodb.py`) is the only code that knows these key formats.

| Entity | PK | SK | GSI1PK | GSI1SK |
|--------|----|----|--------|--------|
| Catalog card | `CARD#<card_id>` | `META` | `SET#<set_id>` | `CARD#<card_id>` |
| Inventory item (raw) | `INV#<shard>` | `CARD#<card_id>#RAW#<finish>#<condition>` | `CARD#<card_id>` | `INV#RAW#<finish>#<condition>` |
| Inventory item (graded) | `INV#<shard>` | `CARD#<card_id>#GRADED#<company>#<grade>#<cert>` | `CARD#<card_id>` | `INV#GRADED#<company>#<grade>` |
| Graded market value | `CARD#<card_id>` | `GRADEDPRICE#<company>#<grade>` | — | — |
| Price history point | `CARD#<card_id>` | `PRICE#RAW#<finish>#<date>` or `PRICE#GRADED#<company>#<grade>#<date>` | — | — |

Access patterns this supports:

- **Get a catalog card** — point read on `CARD#<id> / META`.
- **List a set's cards** — `GSI1` query on `SET#<id>`.
- **List all inventory** — query each `INV#0`..`INV#9` shard and concatenate.
- **List inventory for one card** — `GSI1` query on `CARD#<id>` (begins_with `INV#`).
- **Price history for a card** — query `CARD#<id>` with an `SK` prefix/`between` range.

**Why inventory is sharded.** Inventory items use `PK = INV#<shard>` where the
shard is `md5(card_id) % 10` (see `_bucket`). Spreading writes across 10
partitions avoids a single hot "all inventory" partition; `list_inventory`
fans out across all shards to reassemble the full set. `md5` is used instead of
the builtin `hash()` because `hash()` is salted per-process (`PYTHONHASHSEED`)
and would not be stable across restarts.

**Grade canonicalization.** Grades are decimals (`9`, `9.5`, `10`). To keep keys
stable regardless of how a grade was spelled, `_grade_key` normalizes them
(`9.50` → `9.5`, `10.0` → `10`) before composing any key that contains a grade.

## External integrations

- **TCGdex** (`tcgdex.py`) — read-only, unauthenticated HTTP client for
  multilingual card metadata and prices (TCGplayer USD + Cardmarket EUR).
  Retries 429/5xx with exponential backoff; treats other 4xx as hard failures
  and maps 404 to `None`. Card ids are language-qualified (`en:base1-4`,
  `ja:M5-001`) so a Japanese card and its English twin are distinct rows, and
  every stored price is USD — Cardmarket figures are converted at `EUR_USD_RATE`
  with the conversion recorded in `value_note`.
- **Bedrock** (`bedrock.py`) — chat mode runs a bounded Converse tool-use loop
  (max 5 tool turns) with the MCP inventory tools. Errors map to typed
  exceptions (`BedrockThrottledError`, `BedrockLoopError`, …) that the chat
  router translates into 429/503/422/502 responses.
- **MCP server** (`services/mcp_client.py`) — placeholder. Until it lands,
  `get_bedrock_service` wires a stub tool executor, so chat answers reach
  Bedrock but tool calls return a "not configured" message.
- **PokemonPriceTracker** (`services/slab/pricing.py`) — the per-grade **slab**
  price source, and the only outbound integration that needs a credential. The
  TCGdex feed prices ungraded singles only, so without this a PSA 10 and a PSA 4
  of the same card carry the same number. Free tier: 100 credits/day, 60 req/min,
  **2 credits per lookup** → **50 slab lookups a day**; billed on `limit` even
  when the search matches nothing, so `limit=1` is pinned. Budgets are enforced
  **before the socket opens** by `services/slab/quota.py` (`DailyQuota` hard
  budget + `MinuteWindow` pacer, both per-process and in-memory, self-correcting
  from the vendor's `x-ratelimit-daily-remaining`). A price is attached **only on
  a verified join** — the response's `externalCatalogId`, read as
  `en:<id>`, must equal the item's own `card_id`, because the vendor's name search
  returns the wrong card roughly a third of the time and a wrong answer is
  indistinguishable from a right one. Japanese cards carry no `externalCatalogId`,
  so JP slabs are unpriceable by construction. Missing key → `None` from
  `build_pricing_provider()`, which the nightly job treats as "skip", never a
  raise.
- **PSA cert API** — **WITHDRAWN 2026-08-10. Never built, never successfully
  called, and never will be.** The API became a **paid** feature and the owner
  declined it, so RFC 0009 T2 (lookup) and T5 (camera) are **WON'T DO** and RFC
  0010 §H is the authority. Every authenticated request ever made returned `403
  "Access to this API is limited to approved customers"` — the key was valid, the
  **account** was never entitled, and no code change reaches it. **Do not retry
  it and do not email `collectors-apis@collectors.com`.** Slab intake is
  hand-entered by design, not as a stopgap; `PSA_API_KEY` is read by nothing and
  is gone from `.env.example`; the mapper was never written against a guessed
  shape, which is why the withdrawal cost nothing to absorb.

## Daily sync

`catalog_sync.run_daily_sync(repo, client, today)` is the batch job, run on a
schedule via **`python scripts/daily_sync.py`** (in production, via
`python -m scripts.scheduled_sync --job prices`). **Five steps**, and the order is
load-bearing: the two writing steps come first because step 5 denormalizes
whatever prices steps 1 and 3 just wrote.

1. `refresh_held_prices` — the Tier 2 DEPTH pass. Fetches per-card rarity +
   prices from TCGdex for every held *raw* Singles card (graded slabs are
   excluded by design — see below). Never deletes, zeroes, or nulls an existing
   price on failure or on a priceless response; aborts after 25 consecutive
   per-card failures rather than burning the whole run against a dead endpoint
   (RFC 0003 §7).
2. `refresh_graded_prices` — **per-grade slab prices from PokemonPriceTracker**
   (RFC 0009 T7). Owned slabs, stalest-first (never-priced first), deduped by
   `(card_id, company, grade)`, capped at what today's credits can pay for —
   **50 lookups on the free tier**, so above 50 slabs the rest wait for the next
   night. Skips an unlinked slab and a **pinned** price for free, before any
   socket opens. Aborts after only **5** consecutive failures, against the depth
   pass's 25, because every failed call here is still billed. It **never calls
   PSA**. A missing key skips this step alone and logs a warning; steps 1 and 3-5
   run regardless.
3. `snapshot_graded_prices` — record a daily history point for each owned graded
   slab that has a market value (provider-fetched or hand-typed).
4. `snapshot_sealed_prices` — the same for sealed products, whose history hangs
   off the item rather than a catalog card.
5. `refresh_inventory_market_values` — denormalize the latest market value onto
   each inventory item so search/list reads don't need a second lookup.

Only steps 1 and 2 talk to an upstream API, and both only for stock the business
actually holds — ~300 paced TCGdex requests, plus at most 50 metered pricing
lookups. Steps 3-5 are DynamoDB-only. The site itself never reads from either
vendor; every customer-facing read comes from DynamoDB, so an upstream outage
delays a refresh without taking the site down.

`scripts/daily_sync.py` exits `0` on a completed run, `1` if the depth pass
aborted on consecutive failures, or `2` if it was skipped because a catalog
reseed held the lock — see that script's own module docstring for the full
exit-code table.

Catalog data arrives through two separate passes, because TCGdex serves pricing
**only** from its per-card detail endpoint:

- **Tier 1, breadth** — `scripts/seed_catalog.py`, one cheap request per
  language for the whole catalog, identity only, no prices. Dry run by default;
  see `docs/aws-setup.md` for the `--execute` / `--confirm-table` rails.
- **Tier 2, depth** — `refresh_held_prices` (above), one request per *held raw*
  card, which is where prices and rarity come from (RFC 0003 §7). Graded slabs
  are excluded permanently, by owner decision: TCGdex prices ungraded singles, so
  a slab's value comes from step 2's per-grade provider instead. A card held
  **only** as a slab still keeps `rarity: null` — that comes from the depth pass,
  which never visits it.

## Deploying to AWS

Two independent paths — **Containers (ECS Fargate)**, current production,
and **Serverless (Lambda)**, RFC 0014's in-progress migration spike. See the
root [`README.md`](../README.md#deploying-to-aws) for how the two relate.

### Containers (ECS Fargate) — current production path

The backend runs as a Docker container on ECS Fargate behind the `merlins` cluster.
It bundles the MCP server (Node.js) as a subprocess inside the same image.

#### Prerequisites

- AWS CLI configured with credentials for account `560151615792`
- Docker installed and running
- ECR repository `merlins-backend` exists in `us-east-1`

#### Deploy Backend

Run from the **repo root** (the Dockerfile uses repo root as build context because
the MCP server workspace and the lockfile live there):

```bash
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 560151615792.dkr.ecr.us-east-1.amazonaws.com
docker build -f backend/Dockerfile -t 560151615792.dkr.ecr.us-east-1.amazonaws.com/merlins-backend:latest .
docker push 560151615792.dkr.ecr.us-east-1.amazonaws.com/merlins-backend:latest
aws ecs update-service --cluster merlins --service merlins-backend --force-new-deployment --region us-east-1
```

#### Runtime Env (on the container)

All settings are ECS task definition environment variables (never baked into the image).
See `.env.example` for the complete list. Critical production settings:

- `COGNITO_USER_POOL_ID` / `COGNITO_CLIENT_ID` — Cognito pool for JWT verification
- `DYNAMODB_TABLE_NAME` — inventory table (default: `merlins-cards`)
- `RATE_LIMIT_TABLE_NAME` — rate-limit counters (default: `merlins-rate-limits`)
- `CORS_ORIGINS` — frontend origin(s) allowed by CORS
- `FORWARDED_ALLOW_IPS` — proxy trust boundary (see Dockerfile comments)

**Both bearer-token credentials are plain `environment` values, not
`secrets`** — owner decision, 2026-08-12 (see CLAUDE.md's "Third-Party APIs"
section and `docs/aws-setup.md` Phase 8): no Secrets Manager secret, no
execution-role grant, same `environment` array every other non-AWS config
value already goes through. Confirmed live on `merlins-merlins-backend`'s
current task definition — `secrets` is empty, both keys are in
`environment`:

- `ADMIN_API_KEY` — static bearer token for Retool admin access
- `POKEMONPRICETRACKER_API_KEY` — graded pricing (RFC 0009). The **first outbound
  third-party credential this service holds**. Unset is a supported state: slab
  pricing is skipped and nothing else changes

`PRICING_DAILY_QUOTA` is an ordinary non-secret `environment` value.

#### Infrastructure

| Resource | Value |
|----------|-------|
| AWS Account | `560151615792` |
| Region | `us-east-1` |
| ECS Cluster | `merlins` |
| Backend Service | `merlins-backend` |
| Backend ECR | `560151615792.dkr.ecr.us-east-1.amazonaws.com/merlins-backend` |
| Backend URL | `https://me-227b5d9d4f6444e9aea830a909f923c8.ecs.us-east-1.on.aws` |

### Serverless (Lambda) — RFC 0014 spike

Same image, different target: `backend/Dockerfile`'s `lambda` build stage
(alongside the `runtime` stage the container path above uses) packages the
same FastAPI app behind the Lambda Web Adapter. Deployed via the CDK stack
`MerlinsBackendStack` in `infra/` — see the root
[`README.md`](../README.md#deploying-to-aws) for exact commands, required
environment variables, and status-check commands. Docker Desktop must be
running locally since `cdk deploy` builds this stage as a Docker asset.

Runtime env is the same variable list as the container path above, minus
`FORWARDED_ALLOW_IPS` (the CDK stack sets it to `127.0.0.1/32` directly —
the Lambda Web Adapter is the app's only real peer here, not a VPC-scoped
load balancer). `CORS_ORIGINS` is a plain string literal in
`infra/bin/infra.ts` rather than a task-definition field — see that file's
comment before editing it.

Deployed and reachable (Function URL from `aws cloudformation
describe-stacks --stack-name MerlinsBackendStack --query
"Stacks[0].Outputs"`), but nothing in production points at it yet — see
`docs/rfcs/0014-ecs-to-serverless-migration.md`.
