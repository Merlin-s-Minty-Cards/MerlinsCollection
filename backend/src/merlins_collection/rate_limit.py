"""App-side request rate limiting — DynamoDB-backed and DISTRIBUTED.

Why this exists: ``/chat`` calls AWS Bedrock, which costs real money per query.
A client that exceeds its window must be turned away with **429 before the
Bedrock call is ever made** — so this limiter runs as a FastAPI dependency, which
resolves *before* the endpoint body (and therefore before ``BedrockChatService``).

WHY DYNAMODB (not in-process memory): the R14 limiter kept counters in the
worker process's RAM. That is wrong in production — every ECS/App Runner restart,
redeploy, crash-loop, or scale-out event reset the counters, and multiple
instances each kept their own count, so N instances let a user make N× the limit.
Counters here live in a dedicated DynamoDB table and are incremented with an
atomic ``ADD`` ``UpdateItem`` (atomic under concurrency — no check-then-set race),
so the limit is correct across restarts, redeploys, multiple instances, and any
compute model (ECS, App Runner, Lambda). Each counter item carries a numeric
``expires_at`` TTL attribute so old per-minute / per-day windows auto-expire and
the table never grows without bound. (TTL must be enabled on the table by the
owner — see ``DynamoRateLimiter.create_table`` and ``backend/.env.example``.)

TWO-TIER CAP on ``/chat``:
  * per-user (Cognito ``sub``): a per-minute burst cap AND a per-day ceiling.
  * a GLOBAL account-wide per-day cap across ALL users. Even if Cognito self-
    signup is open, this bounds total daily Bedrock spend for the business — an
    attacker minting N accounts still hits the one global ceiling.

KEYING: per authenticated Cognito ``sub`` so two customers never share a bucket.
Under the ``AUTH_DISABLED`` dev bypass every request carries the same synthetic
``dev-user`` sub, so we key by client IP instead.

IP KEYS AND THE PROXY TRUST BOUNDARY: every IP key here reads
``request.client.host`` and nothing else — this module never parses
``X-Forwarded-For`` itself, because hand-parsing it unconditionally is exactly
how a spoofable key gets introduced. In production ``request.client.host`` is
already the REAL client IP: the container runs uvicorn with ``--proxy-headers``
and a SCOPED ``FORWARDED_ALLOW_IPS`` (never ``*``), so uvicorn's
ProxyHeadersMiddleware validates the hop and rewrites ``scope["client"]`` before
any of this runs. Without that, everything behind the ALB would share one
bucket. The trust set is defined and justified in ``backend/Dockerfile`` — if it
is ever widened to ``*``, these IP keys become attacker-forgeable.

FAIL MODE when the limiter itself can't verify (table unreachable / throttled):
  * ``/chat`` FAILS CLOSED — returns 503 rather than proceeding to Bedrock
    uncapped. Unbounded spend is worse than a brief outage on the paid path.
  * ``/inventory/search`` and ``/auth`` FAIL OPEN — they are cheap, non-cost
    reads, so availability wins over strict limiting there.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from functools import lru_cache

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import Depends, HTTPException, Request, status

from merlins_collection.config import settings
from merlins_collection.dependencies import get_current_user
from merlins_collection.models.auth import AuthenticatedUser

logger = logging.getLogger(__name__)

# Counter items outlive their window by this grace so DynamoDB's (lazy, ≤48h)
# TTL sweep never deletes an item that is still inside its active window.
_TTL_GRACE_SECONDS = 3600

_PERIOD_SECONDS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}

# A per-minute burst trip clears in seconds; a daily-ceiling trip can be HOURS
# away. Above this many seconds of Retry-After we drop the "shortly" wording so
# the copy isn't misleading (Retry-After still carries the exact number).
_SHORTLY_THRESHOLD_SECONDS = 300


def _limited_detail(retry_after: int) -> str:
    """User-facing 429 message, worded for how long the caller must actually wait.

    A short (per-minute) trip says "shortly"; a long (per-day / global) trip does
    not, because its ``Retry-After`` can be many hours out — telling the user to
    "try again shortly" then would be a lie.
    """
    if retry_after > _SHORTLY_THRESHOLD_SECONDS:
        return (
            "Rate limit exceeded — you've hit a usage cap. Check the Retry-After "
            "header for when this resets (it may be a while)."
        )
    return "Rate limit exceeded — please slow down and try again shortly."


# Fail-closed 503s carry a small fixed Retry-After so a client backs off instead
# of retry-storming an already-degraded limiter table.
_UNAVAILABLE_RETRY_AFTER = 5
_UNAVAILABLE_DETAIL = (
    "The service is temporarily unable to verify usage limits; please retry shortly."
)


def parse_limit(raw: str) -> tuple[int, int]:
    """Parse a limit string like ``"10/minute"`` into ``(count, window_seconds)``.

    Accepts ``"<count>/<period>"``; period is one of second/minute/hour/day (a
    trailing ``s`` is allowed). Raises ``ValueError`` on anything malformed —
    callers validate at startup so a bad value fails LOUD.
    """
    if not raw or not isinstance(raw, str):
        raise ValueError(f"empty or non-string rate limit: {raw!r}")
    text = raw.strip().lower()
    if "/" in text:
        count_str, _, period = text.partition("/")
    else:
        raise ValueError(f"rate limit must look like '10/minute': got {raw!r}")
    count_str, period = count_str.strip(), period.strip().rstrip("s")
    try:
        count = int(count_str)
    except ValueError as exc:
        raise ValueError(f"rate-limit count is not an integer: {raw!r}") from exc
    if count <= 0:
        raise ValueError(f"rate-limit count must be positive: {raw!r}")
    if period not in _PERIOD_SECONDS:
        raise ValueError(
            f"unknown rate-limit period {period!r} in {raw!r}; "
            f"expected one of {sorted(_PERIOD_SECONDS)}"
        )
    return count, _PERIOD_SECONDS[period]


# Every limit setting parsed at startup so a malformed value crashes app
# construction instead of silently disabling the limit at request time.
_LIMIT_SETTINGS = (
    "rate_limit_chat",
    "rate_limit_chat_daily",
    "rate_limit_chat_global_daily",
    "rate_limit_search",
    "rate_limit_auth",
    "rate_limit_public",
)


def validate_rate_limit_settings(config=settings) -> None:
    """Parse every limit setting; raise ``RuntimeError`` on the first bad one.

    Called at import time in ``main.py`` so a typo'd limit value (``10/min``, an
    empty string, ``10 minute``) fails the deploy LOUDLY rather than shipping a
    silently-disabled cost cap. This closes the R14 fail-open gap.
    """
    for name in _LIMIT_SETTINGS:
        raw = getattr(config, name)
        try:
            parse_limit(raw)
        except ValueError as exc:
            raise RuntimeError(
                f"Invalid rate-limit setting {name.upper()}={raw!r}: {exc}"
            ) from exc


class RateLimiterUnavailable(Exception):
    """The limiter could not reach/verify its DynamoDB counter store.

    Callers decide the policy: the cost endpoint fails CLOSED (503), cheap
    endpoints fail OPEN (serve the request).
    """


@dataclass(frozen=True)
class RateLimitResult:
    """Outcome of a check: whether the caller is over a limit, and for how long."""

    limited: bool
    retry_after: int = 0


class DynamoRateLimiter:
    """Distributed fixed-window rate limiter backed by a dedicated DynamoDB table.

    One item per (key, window-bucket). ``UpdateItem`` with an ``ADD`` expression
    increments the counter atomically and returns the new value, so concurrent
    requests can never both read a stale count and slip past the cap. A numeric
    ``expires_at`` attribute lets DynamoDB TTL reap stale windows.

    The boto3 client is built with a tight ``botocore`` ``Config`` (short
    connect/read timeouts + a capped retry count) so a DynamoDB *brownout* (a
    slow, not dead, table) FAILS FAST instead of holding each blocking
    ``UpdateItem`` for boto3's ~60s default. Without this, the up-to-3 sequential
    hits per ``/chat`` call would saturate the sync anyio threadpool and hang the
    WHOLE app — including the endpoints that advertise fail-open. Failing fast
    turns a brownout into a prompt 503 (``/chat``, fail-closed) or a served
    request (search/auth, fail-open), never a hang.

    The table is normally provisioned out-of-band; ``create_table`` is for tests
    and local dev.
    """

    # connect 1s + read 2s, at most 3 attempts (initial + 2 retries; botocore
    # resolves max_attempts=2 to total_max_attempts=3) → worst case ~9s per
    # UpdateItem (~27s for /chat's three tiers) instead of minutes under boto3's
    # ~60s defaults. Bounds the brownout hang so the threadpool can't saturate.
    _CLIENT_CONFIG = Config(
        connect_timeout=1,
        read_timeout=2,
        retries={"max_attempts": 2, "mode": "standard"},
    )

    def __init__(self, table_name: str, *, region_name: str = "us-east-1"):
        self._resource = boto3.resource(
            "dynamodb", region_name=region_name, config=self._CLIENT_CONFIG
        )
        self._table_name = table_name
        self._table = self._resource.Table(table_name)

    def create_table(self) -> None:
        """Create the counter table (tests / local dev) and block until active.

        Single string partition key ``PK``, no sort key. The ``expires_at``
        attribute is NOT part of the key schema — TTL is a table property the
        owner must enable manually on the real table (there is no IaC)::

            aws dynamodb update-time-to-live \\
                --table-name <RATE_LIMIT_TABLE_NAME> \\
                --time-to-live-specification "Enabled=true,AttributeName=expires_at"
        """
        self._resource.create_table(
            TableName=self._table_name,
            BillingMode="PAY_PER_REQUEST",
            KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "PK", "AttributeType": "S"}],
        )
        self._table.wait_until_exists()

    def _hit(self, key: str, window_seconds: int, now: int) -> tuple[int, int]:
        """Atomically increment the counter for ``key``'s current window.

        Returns ``(new_count, window_end_epoch)``. Raises ``RateLimiterUnavailable``
        if DynamoDB can't be reached — the caller decides fail-open vs fail-closed.
        """
        window_start = (now // window_seconds) * window_seconds
        window_end = window_start + window_seconds
        pk = f"RL#{key}#{window_seconds}#{window_start}"
        try:
            resp = self._table.update_item(
                Key={"PK": pk},
                UpdateExpression="ADD #count :one SET #ttl = if_not_exists(#ttl, :ttl)",
                ExpressionAttributeNames={
                    "#count": "count",
                    "#ttl": "expires_at",
                },
                ExpressionAttributeValues={
                    ":one": 1,
                    ":ttl": window_end + _TTL_GRACE_SECONDS,
                },
                ReturnValues="UPDATED_NEW",
            )
        except (ClientError, BotoCoreError) as exc:
            raise RateLimiterUnavailable(str(exc)) from exc
        return int(resp["Attributes"]["count"]), window_end

    def check(self, tiers, *, now: int | None = None) -> RateLimitResult:
        """Increment each tier's counter in order; stop at the first one exceeded.

        ``tiers`` is an iterable of ``(key, limit_count, window_seconds)``. Tiers
        are evaluated in order and short-circuit: once a tier trips we return
        WITHOUT touching later tiers, so (e.g.) a per-minute rejection never
        consumes the per-day or global counters. A rejected request does consume
        the tiers up to and including the one it tripped, which only makes the cap
        stricter, never looser.
        """
        if now is None:
            now = int(time.time())
        for key, limit_count, window_seconds in tiers:
            count, window_end = self._hit(key, window_seconds, now)
            if count > limit_count:
                return RateLimitResult(limited=True, retry_after=max(window_end - now, 0))
        return RateLimitResult(limited=False)


@lru_cache
def get_rate_limiter() -> DynamoRateLimiter:
    """Provide the DynamoDB-backed limiter as a cached singleton.

    Overridden in tests via ``app.dependency_overrides``.
    """
    return DynamoRateLimiter(
        settings.rate_limit_table_name, region_name=settings.aws_region
    )


def caller_key(request: Request, user: AuthenticatedUser) -> str:
    """The rate-limit bucket for this caller.

    Keys by Cognito ``sub`` for real users; keys by client IP under the
    ``AUTH_DISABLED`` dev bypass (where every request shares the ``dev-user``
    sentinel sub and would otherwise collapse into one global bucket). The IP is
    read from ``request.client.host`` only — proxy-header trust is resolved
    upstream by uvicorn, never by hand here (see the module docstring).
    """
    if settings.auth_disabled or not user.sub or user.sub == "dev-user":
        host = request.client.host if request.client else "unknown"
        return f"ip:{host}"
    return f"user:{user.sub}"


def _apply(limiter: DynamoRateLimiter, tiers, *, fail_closed: bool, label: str) -> None:
    """Run the limiter for ``tiers`` and translate the outcome to HTTP.

    On a limiter error: fail CLOSED (503) for the cost path, or fail OPEN (serve)
    for cheap paths. On an over-limit: 429 with a ``Retry-After`` header.
    """
    try:
        result = limiter.check(tiers)
    except RateLimiterUnavailable as exc:
        if fail_closed:
            logger.error("rate limiter unavailable — failing CLOSED for %s: %s", label, exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=_UNAVAILABLE_DETAIL,
                # Back-off hint so a client doesn't retry-storm the degraded table.
                headers={"Retry-After": str(_UNAVAILABLE_RETRY_AFTER)},
            ) from exc
        logger.warning("rate limiter unavailable — failing OPEN for %s: %s", label, exc)
        return
    if result.limited:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=_limited_detail(result.retry_after),
            headers={"Retry-After": str(result.retry_after)},
        )


def rate_limit_chat(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
    limiter: DynamoRateLimiter = Depends(get_rate_limiter),
) -> AuthenticatedUser:
    """Cost-critical dependency for ``/chat``. Fails CLOSED if the limiter errors.

    Enforces three tiers in order: per-user minute, per-user day, then a global
    account-wide daily Bedrock ceiling. Runs before the endpoint body, so an
    over-limit request 429s without ever reaching Bedrock.
    """
    if not settings.rate_limit_enabled:
        return user
    key = caller_key(request, user)
    # The global tier is a FIXED epoch-day window, so a fresh counter is minted at
    # UTC midnight. Requests straddling 00:00 UTC can therefore spend the full cap
    # against today's bucket AND the full cap against tomorrow's within ~1-2 min:
    # the TRUE worst case is 2x the configured global cap, concentrated at midnight
    # — NOT a hard ceiling. The default (config.py) is deliberately set to HALF the
    # tolerable daily Bedrock spend so this 2x straddle still lands inside budget.
    #
    # ACCEPTED GRIEFING TRADEOFF: the global counter is shared-fate. Under open
    # Cognito self-signup, ~10 accounts each spending their per-user cap can exhaust
    # the global budget and 429 every honest user until the next UTC midnight. This
    # is the intentional cost-over-availability posture (same as fail-closed): a
    # bounded, recoverable outage of a non-critical feature beats unbounded Bedrock
    # dollars. Mitigations: gate Cognito signup + a CloudWatch alarm when the global
    # counter nears the cap so exhaustion is observed, not discovered by users.
    tiers = [
        (f"{key}#chat", *parse_limit(settings.rate_limit_chat)),
        (f"{key}#chat", *parse_limit(settings.rate_limit_chat_daily)),
        ("global#chat", *parse_limit(settings.rate_limit_chat_global_daily)),
    ]
    _apply(limiter, tiers, fail_closed=True, label="chat")
    return user


def rate_limit_search(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
    limiter: DynamoRateLimiter = Depends(get_rate_limiter),
) -> AuthenticatedUser:
    """Looser per-user limit for filter-mode search. Fails OPEN (cheap read)."""
    if not settings.rate_limit_enabled:
        return user
    key = caller_key(request, user)
    tiers = [(f"{key}#search", *parse_limit(settings.rate_limit_search))]
    _apply(limiter, tiers, fail_closed=False, label="search")
    return user


def rate_limit_auth(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
    limiter: DynamoRateLimiter = Depends(get_rate_limiter),
) -> AuthenticatedUser:
    """Per-user limit for the identity endpoints. Fails OPEN (cheap JWT echo)."""
    if not settings.rate_limit_enabled:
        return user
    key = caller_key(request, user)
    tiers = [(f"{key}#auth", *parse_limit(settings.rate_limit_auth))]
    _apply(limiter, tiers, fail_closed=False, label="auth")
    return user


def rate_limit_public(
    request: Request,
    limiter: DynamoRateLimiter = Depends(get_rate_limiter),
) -> None:
    """Per-IP cost cap for the UNAUTHENTICATED ``/public/*`` endpoints.

    These carry no Cognito ``sub``, so the bucket is the client IP from
    ``request.client.host``. Behind the ALB that is the REAL client IP rather
    than the ALB's — uvicorn's ``--proxy-headers`` with a scoped
    ``FORWARDED_ALLOW_IPS`` resolves it before this dependency runs, so anonymous
    callers get separate buckets instead of collapsing into one. Fails OPEN:
    the reads are cheap and the 300s cache absorbs the steady state, so this is a
    burst blunter, not a correctness gate. Runs before the endpoint body, so an
    over-limit anonymous burst 429s without launching a ``list_inventory`` scan.
    """
    if not settings.rate_limit_enabled:
        return
    host = request.client.host if request.client else "unknown"
    key = f"ip:{host}"
    tiers = [(f"{key}#public", *parse_limit(settings.rate_limit_public))]
    _apply(limiter, tiers, fail_closed=False, label="public")
