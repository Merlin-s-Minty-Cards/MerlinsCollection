"""App-side request rate limiting — DynamoDB-backed, distributed (Revision 15).

The whole point of the `/chat` limit is COST CONTROL: `/chat` calls AWS Bedrock,
which costs real money per query, so a client that exceeds its window must be
turned away with 429 *before* the Bedrock call is ever made.

Unlike the R14 in-process limiter, counters live in a dedicated DynamoDB table
(atomic `ADD` UpdateItem), so the limit is CORRECT across process restarts,
redeploys, and multiple instances. Two tiers cap `/chat`: a per-user (Cognito
`sub`) minute + day cap, PLUS a global account-wide daily Bedrock ceiling across
ALL users. The cost endpoint FAILS CLOSED (503) if the limiter itself can't
verify; the cheap endpoints fail open to stay available.
"""

import pytest
from fastapi.testclient import TestClient


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

RL_TABLE = "merlins-rate-limits-test"


@pytest.fixture
def rl_limiter(dynamo_repo):
    """A DynamoRateLimiter backed by a freshly-provisioned moto table.

    Depends on `dynamo_repo` so it runs inside the same `mock_aws` backend.
    """
    from merlins_collection.rate_limit import DynamoRateLimiter

    limiter = DynamoRateLimiter(RL_TABLE, region_name="us-east-1")
    limiter.create_table()
    return limiter


@pytest.fixture
def rl_client(cognito_config, jwks, dynamo_repo, rl_limiter):
    """TestClient with real JWT auth, an empty repo, a Bedrock SPY, and the
    DynamoDB-backed limiter wired to a moto table.

    The Bedrock spy lets each test assert the money call was (or was not) made.
    """
    from unittest.mock import MagicMock

    from merlins_collection.dependencies import (
        get_bedrock_service,
        get_repo,
        get_verifier,
    )
    from merlins_collection.main import app
    from merlins_collection.rate_limit import get_rate_limiter
    from merlins_collection.services.cognito import CognitoJwtVerifier

    verifier = CognitoJwtVerifier(
        region=cognito_config["region"],
        user_pool_id=cognito_config["user_pool_id"],
        client_id=cognito_config["client_id"],
        jwks=jwks,
    )
    app.dependency_overrides[get_verifier] = lambda: verifier
    app.dependency_overrides[get_repo] = lambda: dynamo_repo
    app.dependency_overrides[get_rate_limiter] = lambda: rl_limiter

    bedrock = MagicMock()
    bedrock.chat.return_value = "hi"
    app.dependency_overrides[get_bedrock_service] = lambda: bedrock

    client = TestClient(app, raise_server_exceptions=False)
    client.bedrock = bedrock  # type: ignore[attr-defined]  # expose spy to tests
    client.rate_limiter = rl_limiter  # type: ignore[attr-defined]
    yield client
    app.dependency_overrides.clear()


def _headers(mint_token, sub: str) -> dict:
    return {"Authorization": f"Bearer {mint_token({'sub': sub})}"}


class _BrokenLimiter:
    """Stand-in whose every check raises — simulates an unreachable table."""

    def check(self, *args, **kwargs):
        from merlins_collection.rate_limit import RateLimiterUnavailable

        raise RateLimiterUnavailable("simulated DynamoDB failure")


# --------------------------------------------------------------------------
# /chat: the cost-critical endpoint
# --------------------------------------------------------------------------

def test_chat_trips_429_and_bedrock_not_called_once_limited(rl_client, mint_token):
    """Past the window, /chat returns 429 and Bedrock is NEVER hit on that request."""
    headers = _headers(mint_token, "cost-guard")
    statuses = [
        rl_client.post("/chat/", json={"message": "hi"}, headers=headers).status_code
        for _ in range(15)
    ]
    successes = statuses.count(200)
    assert 429 in statuses, f"expected a 429 within the window, got {statuses}"
    assert successes < 15, "the limiter never tripped"
    # Bedrock is invoked ONLY on the requests that passed the limiter — the
    # tripping (429) requests must never reach the money call.
    assert rl_client.bedrock.chat.call_count == successes


def test_chat_429_carries_retry_after_header(rl_client, mint_token):
    headers = _headers(mint_token, "retry-user")
    resp = None
    for _ in range(15):
        resp = rl_client.post("/chat/", json={"message": "hi"}, headers=headers)
        if resp.status_code == 429:
            break
    assert resp is not None and resp.status_code == 429
    retry_after = resp.headers.get("Retry-After")
    assert retry_after is not None, "429 must advertise a Retry-After"
    assert int(retry_after) >= 0


def test_chat_limits_are_per_user_not_shared(rl_client, mint_token):
    """Exhausting user A's bucket must not affect a different authenticated user."""
    a = _headers(mint_token, "user-A")
    b = _headers(mint_token, "user-B")
    a_statuses = [
        rl_client.post("/chat/", json={"message": "hi"}, headers=a).status_code
        for _ in range(15)
    ]
    assert 429 in a_statuses, "user A should have been limited"
    b_resp = rl_client.post("/chat/", json={"message": "hi"}, headers=b)
    assert b_resp.status_code == 200, "user B must have an independent bucket"


def test_chat_daily_cap_is_enforced_and_configurable(rl_client, mint_token, monkeypatch):
    """A per-user daily ceiling caps total /chat cost even under the per-minute limit."""
    from merlins_collection import rate_limit

    # Raise the per-minute + global caps out of the way; pin a tiny per-user daily cap.
    monkeypatch.setattr(rate_limit.settings, "rate_limit_chat", "1000/minute")
    monkeypatch.setattr(rate_limit.settings, "rate_limit_chat_daily", "5/day")
    monkeypatch.setattr(rate_limit.settings, "rate_limit_chat_global_daily", "1000/day")
    headers = _headers(mint_token, "daily-capped")
    statuses = [
        rl_client.post("/chat/", json={"message": "hi"}, headers=headers).status_code
        for _ in range(8)
    ]
    assert statuses.count(200) == 5
    assert 429 in statuses


def test_global_daily_cap_trips_across_different_users(rl_client, mint_token, monkeypatch):
    """A global/account-wide daily ceiling caps total Bedrock spend across ALL users.

    Even though each user's own minute/day caps are far from exhausted, the
    account-wide counter trips and 429s a *different* user once the global cap is
    reached. This is the backstop for open Cognito signup.
    """
    from merlins_collection import rate_limit

    monkeypatch.setattr(rate_limit.settings, "rate_limit_chat", "1000/minute")
    monkeypatch.setattr(rate_limit.settings, "rate_limit_chat_daily", "1000/day")
    monkeypatch.setattr(rate_limit.settings, "rate_limit_chat_global_daily", "3/day")

    # Three distinct users each make one request — global counter reaches 3.
    for sub in ("alice", "bob", "carol"):
        r = rl_client.post("/chat/", json={"message": "hi"}, headers=_headers(mint_token, sub))
        assert r.status_code == 200, f"{sub} should be under the global cap still"

    # A brand-new user, well within their OWN cap, is refused by the global cap.
    r = rl_client.post("/chat/", json={"message": "hi"}, headers=_headers(mint_token, "dave"))
    assert r.status_code == 429, "the global account-wide daily cap must trip regardless of user"


def test_chat_fails_closed_when_limiter_unavailable(rl_client, mint_token):
    """If the DynamoDB limiter itself errors, /chat must NOT proceed to Bedrock."""
    from merlins_collection.main import app
    from merlins_collection.rate_limit import get_rate_limiter

    app.dependency_overrides[get_rate_limiter] = lambda: _BrokenLimiter()
    resp = rl_client.post("/chat/", json={"message": "hi"}, headers=_headers(mint_token, "unlucky"))
    assert resp.status_code == 503, "cost endpoint must fail CLOSED when the limiter can't verify"
    assert rl_client.bedrock.chat.call_count == 0, "Bedrock must never be reached on a fail-closed"


# --------------------------------------------------------------------------
# Persistence across a simulated restart (the R14 Chaos MAJOR)
# --------------------------------------------------------------------------

def test_counter_persists_across_simulated_restart(rl_limiter):
    """Counts survive a fresh limiter object (== a new process/instance).

    A brand-new DynamoRateLimiter pointed at the SAME table continues the count
    rather than resetting to zero — the fix for the R14 volatile-memory gap.
    """
    from merlins_collection.rate_limit import DynamoRateLimiter

    now = 1_000_000  # pin the window so both limiters address the same bucket
    tiers = [("user:persist#chat", 5, 60)]

    first = DynamoRateLimiter(RL_TABLE, region_name="us-east-1")
    for _ in range(5):
        assert not first.check(tiers, now=now).limited

    # Simulate a restart / a second instance: a completely fresh limiter object.
    second = DynamoRateLimiter(RL_TABLE, region_name="us-east-1")
    result = second.check(tiers, now=now)
    assert result.limited, "count must carry over from DynamoDB, not reset on restart"


# --------------------------------------------------------------------------
# Fail-loud config validation (the R14 Contrarian MAJOR-1)
# --------------------------------------------------------------------------

def test_bad_rate_limit_config_raises_at_startup():
    """A malformed limit value must CRASH startup, not silently disable the limit."""
    import importlib

    from merlins_collection import config, main

    original = config.settings.rate_limit_chat
    config.settings.rate_limit_chat = "totally not a limit"
    try:
        with pytest.raises(Exception):
            importlib.reload(main)
    finally:
        config.settings.rate_limit_chat = original
        importlib.reload(main)  # restore a valid app for the rest of the suite


def test_parse_limit_rejects_malformed_values():
    from merlins_collection.rate_limit import parse_limit

    for bad in ["", "10", "abc/minute", "10/fortnight", "0/minute", "-1/day", "10 per"]:
        with pytest.raises(ValueError):
            parse_limit(bad)


def test_parse_limit_accepts_valid_values():
    from merlins_collection.rate_limit import parse_limit

    assert parse_limit("10/minute") == (10, 60)
    assert parse_limit("200/day") == (200, 86400)
    assert parse_limit("5/second") == (5, 1)
    assert parse_limit("100/hour") == (100, 3600)


# --------------------------------------------------------------------------
# regression: a normal single request still works
# --------------------------------------------------------------------------

def test_single_chat_request_still_returns_real_reply(rl_client, mint_token):
    headers = _headers(mint_token, "normal-user")
    resp = rl_client.post(
        "/chat/", json={"message": "Do you have Charizard?"}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["reply"] == "hi"
    assert rl_client.bedrock.chat.call_count == 1


# --------------------------------------------------------------------------
# looser limits on the cheaper endpoints (fail OPEN)
# --------------------------------------------------------------------------

def test_search_endpoint_is_rate_limited(rl_client, mint_token):
    headers = _headers(mint_token, "searcher")
    statuses = [
        rl_client.get("/inventory/search", headers=headers).status_code
        for _ in range(65)
    ]
    assert 429 in statuses, "filter-mode search should enforce a (looser) limit"


def test_auth_endpoint_is_rate_limited(rl_client, mint_token):
    headers = _headers(mint_token, "auth-spammer")
    statuses = [
        rl_client.get("/auth/me", headers=headers).status_code for _ in range(35)
    ]
    assert 429 in statuses, "the /auth endpoints should enforce a limit"


def test_search_fails_open_when_limiter_unavailable(rl_client, mint_token):
    """A cheap, non-cost endpoint stays AVAILABLE if the limiter can't verify."""
    from merlins_collection.main import app
    from merlins_collection.rate_limit import get_rate_limiter

    app.dependency_overrides[get_rate_limiter] = lambda: _BrokenLimiter()
    resp = rl_client.get("/inventory/search", headers=_headers(mint_token, "searcher2"))
    assert resp.status_code == 200, "search must fail OPEN (availability) when the limiter errors"


# --------------------------------------------------------------------------
# master switch
# --------------------------------------------------------------------------

def test_disabling_rate_limiting_lets_everything_through(rl_client, mint_token, monkeypatch):
    from merlins_collection import rate_limit

    monkeypatch.setattr(rate_limit.settings, "rate_limit_enabled", False)
    headers = _headers(mint_token, "unlimited")
    statuses = [
        rl_client.post("/chat/", json={"message": "hi"}, headers=headers).status_code
        for _ in range(15)
    ]
    assert statuses.count(200) == 15, "RATE_LIMIT_ENABLED=false must disable the limiter"


# --------------------------------------------------------------------------
# Item 1 — the limiter's DynamoDB client must FAIL FAST under a brownout
# --------------------------------------------------------------------------

def test_limiter_client_has_bounded_timeouts_and_retries(dynamo_repo):
    """The boto3 client must carry a botocore Config with tight timeouts and a
    capped retry count.

    Without this, a *slow* (not dead) DynamoDB holds each blocking `UpdateItem`
    for up to boto3's ~60s default per attempt; the up-to-3 sequential hits per
    `/chat` call saturate the anyio threadpool and hang the WHOLE app, including
    the endpoints that advertise fail-open. Bounding the client makes a brownout
    degrade FAST (503 for /chat, 200 fail-open for search/auth) instead of hang.
    """
    from merlins_collection.rate_limit import DynamoRateLimiter

    limiter = DynamoRateLimiter(RL_TABLE, region_name="us-east-1")
    config = limiter._resource.meta.client.meta.config
    assert config.connect_timeout is not None and config.connect_timeout <= 2, (
        "connect_timeout must be short so a brownout fails fast"
    )
    assert config.read_timeout is not None and config.read_timeout <= 5, (
        "read_timeout must be short so a brownout fails fast"
    )
    # botocore resolves `max_attempts=N` to `total_max_attempts=N+1` (initial + N
    # retries). Whatever the spelling, the total attempt count must stay small.
    total_attempts = config.retries.get("total_max_attempts") or config.retries.get(
        "max_attempts", 99
    )
    assert config.retries is not None and total_attempts <= 3, (
        "retries must be capped so a brownout does not multiply the wall-clock hang"
    )


def test_slow_limiter_call_fails_fast_closed_for_chat(rl_client, mint_token, monkeypatch):
    """A limiter whose DynamoDB call errors (the brownout end-state) must NOT
    block /chat — it fails CLOSED promptly and never reaches Bedrock."""
    from merlins_collection.rate_limit import RateLimiterUnavailable

    def _boom(*args, **kwargs):
        raise RateLimiterUnavailable("simulated brownout")

    monkeypatch.setattr(rl_client.rate_limiter, "check", _boom)
    resp = rl_client.post("/chat/", json={"message": "hi"}, headers=_headers(mint_token, "brownout"))
    assert resp.status_code == 503
    assert rl_client.bedrock.chat.call_count == 0


def test_slow_limiter_call_fails_open_for_search(rl_client, mint_token, monkeypatch):
    """The same brownout must leave the cheap fail-open endpoints responsive."""
    from merlins_collection.rate_limit import RateLimiterUnavailable

    def _boom(*args, **kwargs):
        raise RateLimiterUnavailable("simulated brownout")

    monkeypatch.setattr(rl_client.rate_limiter, "check", _boom)
    resp = rl_client.get("/inventory/search", headers=_headers(mint_token, "brownout2"))
    assert resp.status_code == 200


def test_chat_503_carries_retry_after_header(rl_client, mint_token):
    """Item 5: the fail-closed 503 must also advertise Retry-After so clients
    back off instead of retry-storming the already-degraded table."""
    from merlins_collection.main import app
    from merlins_collection.rate_limit import get_rate_limiter

    app.dependency_overrides[get_rate_limiter] = lambda: _BrokenLimiter()
    resp = rl_client.post("/chat/", json={"message": "hi"}, headers=_headers(mint_token, "storm"))
    assert resp.status_code == 503
    assert resp.headers.get("Retry-After") is not None, "503 must advertise Retry-After"
    assert int(resp.headers["Retry-After"]) >= 0


# --------------------------------------------------------------------------
# Item 2 — the fixed-window global cap's TRUE worst case is exactly 2x
# --------------------------------------------------------------------------

def test_global_cap_worst_case_is_2x_across_utc_midnight(rl_limiter):
    """The global tier is a fixed epoch-day window, so a fresh counter is minted
    at UTC midnight. Worst case across the boundary is EXACTLY 2x the configured
    cap (never 3x): the default cap is deliberately set to half the tolerable
    daily Bedrock spend so this 2x straddle still lands inside budget.
    """
    cap = 3
    tiers = [("global#chat", cap, 86400)]
    midnight = 86400 * 20000          # an exact UTC-midnight epoch boundary
    before = midnight - 10            # last seconds of day N
    after = midnight + 10             # first seconds of day N+1

    # Day N's window absorbs exactly `cap`, then trips.
    for _ in range(cap):
        assert not rl_limiter.check(tiers, now=before).limited
    assert rl_limiter.check(tiers, now=before).limited

    # Crossing midnight mints a fresh window — another `cap` is available (the 2x).
    for _ in range(cap):
        assert not rl_limiter.check(tiers, now=after).limited
    # ...but no THIRD window is reachable in the straddle: worst case is 2x, not 3x.
    assert rl_limiter.check(tiers, now=after).limited


# --------------------------------------------------------------------------
# Item 9 — 429 copy distinguishes a per-minute trip from a multi-hour daily trip
# --------------------------------------------------------------------------

def test_limited_detail_distinguishes_minute_from_daily(rl_client, mint_token, monkeypatch):
    """A short (per-minute) trip says 'shortly'; a long (daily) trip must not,
    because its Retry-After can be hours away."""
    from merlins_collection.rate_limit import _limited_detail

    short = _limited_detail(30)
    long = _limited_detail(6 * 3600)
    assert "shortly" in short.lower()
    assert "shortly" not in long.lower()
    assert short != long
