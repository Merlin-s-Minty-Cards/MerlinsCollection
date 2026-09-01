"""Application settings, loaded from environment variables or a ``.env`` file.

A single module-level ``settings`` instance is imported across the app. Field
names map to upper-case env vars (``aws_region`` ← ``AWS_REGION``); unknown env
vars are ignored. Defaults are dev-friendly — production supplies real values
via the environment, and AWS credentials normally come from the ambient
credential chain rather than the (empty-by-default) fields here.
"""

from decimal import Decimal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed configuration for AWS, Cognito, DynamoDB, Bedrock, and integrations."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    aws_region: str = "us-east-1"
    cognito_user_pool_id: str = ""
    cognito_client_id: str = ""
    dynamodb_table_name: str = "merlins-cards"
    bedrock_model_id: str = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    mcp_server_path: str = "../mcp-server/dist/index.js"
    # EUR->USD rate used when a card is priced only by Cardmarket (Japanese stock
    # mostly is). Prices are DISPLAYED in USD, so a converted figure needs a rate;
    # a constant rather than a live feed because the alternative is a new external
    # dependency, key and outage mode for a few percent of accuracy on a figure
    # that is already a second-choice fallback inside a wide low/high spread. The
    # exact rate used is printed into every converted figure's ``value_note``, so
    # correcting it is a config change with no deploy (RFC 0003 §5).
    eur_usd_rate: Decimal = Decimal("1.08")
    # How old a provider's own `updated` stamp may get before the depth pass
    # calls the figure stale. A stale price is still STORED and still displayed —
    # the age is appended to `value_note` instead, so a customer-facing number is
    # never silently ancient and never silently withheld either (RFC 0003 §7).
    catalog_price_stale_days: int = 30
    # How many UNHELD catalog cards the nightly job re-prices (RFC 0010 T17).
    # The owner's requirement is "the entire catalog re-priced by Friday of each
    # week", and this is the knob that delivers it: 31,300 / 5,500 = 5.7 nights,
    # so a cycle starting Saturday finishes Thursday and Friday is slack — which
    # is what survives a bad night, rather than merely being true when nothing
    # goes wrong. It is a tunable and not a magic number because the arithmetic
    # changes the moment the catalog does.
    #
    # Do NOT raise this toward a full nightly pass. 31,603 x 0.262 s is 2h18m,
    # which outlives the catalog lock's 3600 s TTL; `_CATALOG_MAX_RUNTIME_SECONDS`
    # in `services/catalog_sync.py` is the backstop and explains what that costs.
    catalog_refresh_cards_per_night: int = 5500
    # How long a price-history point (card-level `price_point` or item-level
    # `item_price_point`) is kept before DynamoDB's native TTL reaps it — the
    # owner does not need more than two years of trend (RFC 0015). Computed
    # from the point's own `date`, not write time, so a backfilled or
    # late-written point still expires on the same schedule as one written on
    # time would have.
    price_history_retention_days: int = 730
    # How long a chat conversation is kept before DynamoDB's native TTL reaps
    # it (RFC 0017, decision 7 — six months). The owner's chosen reading is
    # "six months from LAST USE": the conversation row's ttl is pushed forward
    # on every append, while each message row keeps its own clock from its own
    # created_at. Since updated_at is by definition >= the newest message's
    # created_at, the conversation row always outlives its own messages — so
    # ownership can never be orphaned by expiry.
    conversation_retention_days: int = 183
    # Admin analyst threads are kept for TWO YEARS, not six months (RFC 0018,
    # Open Question 3 — a deliberate owner call). A quarter's margin analysis is
    # worth comparing against next year's, which a six-month clock destroys.
    # The branch between the two lives in exactly one function,
    # `services/dynamodb._conversation_ttl`; two writers computing a TTL
    # independently is how half a thread expires early.
    admin_conversation_retention_days: int = 730
    # Comma-separated browser origins allowed to call the API (CORS).
    cors_origins: str = "http://localhost:3000"
    # Dev-only: inject a fake user instead of verifying Cognito JWTs.
    # NEVER set in production.
    auth_disabled: bool = False

    # --- Graded-slab providers (RFC 0009) ---
    # PokemonPriceTracker, the per-grade market-value source for slabs. The raw
    # TCGplayer/Cardmarket feed prices ungraded singles only, so without this a
    # PSA 10 and a PSA 4 of the same card carry the same number.
    pokemonpricetracker_api_key: str = ""
    # Credits per UTC day, NOT lookups per day. A graded lookup costs 2 (1 for
    # the card + 1 for the eBay sales block), and the free tier is 100 credits —
    # so this default is FIFTY slab lookups a day. Measured against a live
    # response, not read off the docs; see docs/plans/rfc-0009/spike-findings.md
    # §2.1, which also records that you are billed on `limit` even when the
    # search matches nothing.
    pricing_daily_quota: int = 100

    # --- Admin API key (Retool / external tool access) ---
    # A static bearer token that bypasses Cognito JWT validation for admin routes.
    # Set this to a long random string (e.g. `openssl rand -hex 32`) and configure
    # the same value in Retool's REST API resource as the Authorization header.
    # When unset (empty), API key auth is disabled and only Cognito JWTs work.
    admin_api_key: str = ""

    # --- App-side rate limiting (DynamoDB-backed & distributed; see rate_limit.py) ---
    # Master switch. Keep ON in production; an ops kill-switch if a limit ever
    # locks legitimate traffic out.
    rate_limit_enabled: bool = True
    # Dedicated DynamoDB table holding the rate-limit counters. Kept SEPARATE from
    # the business `merlins-cards` table so ephemeral counter items can never be
    # mistaken for import-owned business data by the importer's generation sweep.
    rate_limit_table_name: str = "merlins-rate-limits"
    # Limits are "<count>/<period>" strings (period: second/minute/hour/day),
    # keyed per authenticated Cognito `sub` (or client IP when auth is bypassed).
    # `/chat` hits Bedrock and costs real money per call, so it is the strictest:
    # a per-minute burst limit plus a per-user per-day ceiling.
    rate_limit_chat: str = "10/minute"
    rate_limit_chat_daily: str = "200/day"
    # GLOBAL account-wide daily ceiling on /chat across ALL users combined —
    # bounds worst-case daily Bedrock cost even if Cognito self-signup is open and
    # an attacker mints many accounts. NOTE: this is a FIXED epoch-day window, so a
    # request stream straddling UTC midnight can spend this cap twice in ~1-2 min
    # (see rate_limit.rate_limit_chat). The TRUE worst case is therefore 2x this
    # value — set this to HALF the tolerable daily Bedrock spend. Default 1000/day
    # → true worst-case ceiling of 2000 Bedrock calls per rolling 24h.
    rate_limit_chat_global_daily: str = "1000/day"
    # The ADMIN analyst chat (RFC 0018 decision 4): "same limiter, higher admin
    # ceiling". Per-user tiers are raised because an admin working through a
    # month's numbers legitimately asks more questions than a customer browsing
    # cards — but the GLOBAL tier is deliberately NOT duplicated. Both surfaces
    # spend from `global#chat`, because the thing that ceiling protects is the
    # account's Bedrock bill, and two independent global counters would let
    # admin + customer together exceed the budget it exists to cap.
    rate_limit_admin_chat: str = "30/minute"
    rate_limit_admin_chat_daily: str = "500/day"
    # Filter-mode search and the auth endpoints are cheap DynamoDB/JWT calls, so
    # they get looser limits — still enough to blunt a scraper or a stuck client.
    rate_limit_search: str = "60/minute"
    rate_limit_auth: str = "30/minute"
    # The unauthenticated /public/* endpoints each do a full inventory fan-out, so
    # they are the anonymous abuse surface. Keyed per client IP (no Cognito sub),
    # fail-open (cheap read). Blunts a burst that would slip past the 300s cache in
    # a cold/just-expired window.
    rate_limit_public: str = "60/minute"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
