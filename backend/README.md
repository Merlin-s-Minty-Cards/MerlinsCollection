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
    inventory.py     #   GET /inventory/search, GET /inventory/summary
    chat.py          #   POST /chat/
    public.py        #   GET /public/shows, GET /public/featured-cards (unauthenticated)
    health.py        #   GET /health
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
| `GET /inventory/summary` | Bearer | Dashboard header stats (`cards_in_vault`, `est_value`, `sets_tracked`) |
| `POST /chat/` | Bearer | Natural-language inventory chat via Bedrock |
| `GET /public/shows` | **None** | All shows split into `upcoming`/`past` by the business's Pacific "today" |
| `GET /public/featured-cards` | **None** | Up to 5 homepage cards (`name` + `image_url` only) |

`/inventory/search` loads inventory and filters in-process; `cost_basis`
(our purchase price) is stripped from the response and never reaches customers.

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
`current_market_value ?? listed_price ?? 0` (market-value-first, the opposite
of search's listed-price-first ordering), keeps only items whose catalog image
is an `https://images.pokemontcg.io/...` URL, de-duplicates by `card_id`, and
returns the top 5.

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

## Daily sync

`catalog_sync.run_daily_sync(repo, client, today)` is the batch job, run on a
schedule via **`python scripts/daily_sync.py`**. The depth pass runs FIRST —
the order is load-bearing, since step 4 denormalizes whatever prices step 1
just wrote:

1. `refresh_held_prices` — the Tier 2 DEPTH pass, and the only step here that
   talks to an upstream API. Fetches per-card rarity + prices from TCGdex for
   every held *raw* Singles card (graded slabs are excluded by design — see
   below). Never deletes, zeroes, or nulls an existing price on failure or on
   a priceless response; aborts after 25 consecutive per-card failures rather
   than burning the whole run against a dead endpoint (RFC 0003 §7).
2. `snapshot_graded_prices` — record a daily history point for each owned graded
   slab that has a manual market value.
3. `snapshot_sealed_prices` — the same for sealed products, whose history hangs
   off the item rather than a catalog card.
4. `refresh_inventory_market_values` — denormalize the latest market value onto
   each inventory item so search/list reads don't need a second lookup.

Steps 2-4 touch no upstream API — only step 1 does, and only for cards the
business actually holds (~300 requests/day, paced). The site itself never
reads from TCGdex; every customer-facing read comes from DynamoDB, so a TCGdex
outage delays a refresh without taking the site down.

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
  are excluded permanently, by owner decision — their price and detail come
  from the PSA cert API + PriceCharting once Phase 4 resumes, so a card held
  only as a slab keeps `rarity: null` until then.
