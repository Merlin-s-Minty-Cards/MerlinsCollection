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
    # Comma-separated browser origins allowed to call the API (CORS).
    cors_origins: str = "http://localhost:3000"
    # Dev-only: inject a fake user instead of verifying Cognito JWTs.
    # NEVER set in production.
    auth_disabled: bool = False

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
