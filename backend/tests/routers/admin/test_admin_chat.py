"""`/admin/chat` — the read-only admin analyst chat (RFC 0018).

The tests that matter here are the ISOLATION ones. The happy path is the
customer router's, already covered; what is new and load-bearing is that the two
surfaces cannot reach each other's threads, that a non-admin cannot reach this
route at all, and that the customer chat is never handed an admin tool.
"""

from unittest.mock import MagicMock

import pytest

from merlins_collection.models.chat import ADMIN_SURFACE, CUSTOMER_SURFACE


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _stub_admin_bedrock(app, reply="Portland netted $1,330."):
    from merlins_collection.dependencies import get_admin_bedrock_service

    svc = MagicMock()
    svc.chat.return_value = {
        "reply": reply,
        "artifacts": [],
        "panel": {"cards": [], "truncated": False},
    }
    app.dependency_overrides[get_admin_bedrock_service] = lambda: svc
    return svc


@pytest.fixture
def admin_chat(admin_client):
    """Admin client + a stubbed Bedrock + a REAL limiter table.

    `/admin/chat/` carries `rate_limit_admin_chat`, which fails CLOSED (503)
    when it cannot verify usage — Bedrock costs money per call. So the limiter
    table has to exist even though these volumes never trip it. Without it every
    test here 503s, which is the limiter working correctly and the fixture being
    incomplete.
    """
    from merlins_collection.main import app
    from merlins_collection.rate_limit import DynamoRateLimiter, get_rate_limiter

    client, repo, token = admin_client
    limiter = DynamoRateLimiter("merlins-rate-limits-test", region_name="us-east-1")
    limiter.create_table()
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    svc = _stub_admin_bedrock(app)
    return client, repo, token, svc


def test_the_admin_chat_route_fails_CLOSED_when_the_limiter_is_unavailable(
    admin_client,
):
    """Bedrock costs money, so an unverifiable limit must not mean "proceed".

    Observed for real while writing this file: with no limiter table the route
    503s rather than calling the model. Pinned deliberately, because the
    conversation ROUTES beside it use `rate_limit_search` and fail OPEN — the
    two behaviours are easy to swap by accident.
    """
    from merlins_collection.main import app
    from merlins_collection.rate_limit import DynamoRateLimiter, get_rate_limiter

    client, _repo, token = admin_client
    _stub_admin_bedrock(app)
    missing = DynamoRateLimiter("no-such-limiter-table", region_name="us-east-1")
    app.dependency_overrides[get_rate_limiter] = lambda: missing

    resp = client.post("/admin/chat/", json={"message": "margin?"},
                       headers=_auth(token))
    assert resp.status_code == 503


# ---- the route gate ----

def test_a_non_admin_gets_403_not_404(admin_client, mint_token):
    """403 on the ROUTE, deliberately unlike the 404 on a thread id.

    A 404 on a thread id hides whether that id exists. A 403 here hides
    nothing, because the route's existence is not a secret — and an admin who
    has lost their group membership needs to be told that, not shown an empty
    room.
    """
    client, _repo, _token = admin_client
    plain = mint_token(claims={"cognito:groups": []})
    resp = client.post("/admin/chat/", json={"message": "margin?"},
                       headers=_auth(plain))
    assert resp.status_code == 403


def test_an_unauthenticated_caller_gets_401(admin_client):
    client, _repo, _token = admin_client
    assert client.post("/admin/chat/", json={"message": "hi"}).status_code == 401


# ---- surface isolation ----

def test_an_admin_thread_does_not_appear_in_the_customer_history(admin_chat):
    client, repo, token, _svc = admin_chat
    conv_id = client.post("/admin/chat/", json={"message": "what did I net?"},
                          headers=_auth(token)).json()["conversation_id"]

    from merlins_collection.services import conversations as convo

    admin_ids = {c.conversation_id
                 for c in convo.list_summaries(repo, "user-123", ADMIN_SURFACE)}
    customer_ids = {c.conversation_id
                    for c in convo.list_summaries(repo, "user-123", CUSTOMER_SURFACE)}
    assert conv_id in admin_ids
    assert conv_id not in customer_ids


def test_a_customer_thread_id_is_a_404_on_the_admin_route(admin_chat):
    """Cost basis must never be appended to a thread the customer surface renders."""
    client, repo, token, _svc = admin_chat
    from merlins_collection.services import conversations as convo

    customer = convo.start_conversation(repo, "user-123", "what holos?", CUSTOMER_SURFACE)
    repo.put_conversation(customer)

    resp = client.post(
        "/admin/chat/",
        json={"message": "margin?", "conversation_id": customer["conv_id"]},
        headers=_auth(token),
    )
    assert resp.status_code == 404


def test_clearing_admin_history_leaves_customer_threads_alone(admin_chat):
    client, repo, token, _svc = admin_chat
    from merlins_collection.services import conversations as convo

    customer = convo.start_conversation(repo, "user-123", "keep me", CUSTOMER_SURFACE)
    repo.put_conversation(customer)
    client.post("/admin/chat/", json={"message": "aging stock?"}, headers=_auth(token))

    assert client.delete("/admin/chat/conversations",
                         headers=_auth(token)).status_code == 204
    assert convo.list_summaries(repo, "user-123", ADMIN_SURFACE) == []
    assert len(convo.list_summaries(repo, "user-123", CUSTOMER_SURFACE)) == 1


def test_an_admin_thread_is_kept_for_two_years_not_six_months(admin_chat):
    """Open Question 3, end to end through the real route."""
    client, repo, token, _svc = admin_chat
    conv_id = client.post("/admin/chat/", json={"message": "margin?"},
                          headers=_auth(token)).json()["conversation_id"]

    row = next(r for r in repo.list_conversations("user-123")
               if r["conv_id"] == conv_id)
    assert row["surface"] == ADMIN_SURFACE

    from datetime import datetime, timezone
    kept_days = (int(row["ttl"]) - datetime.now(timezone.utc).timestamp()) / 86400
    assert 720 < kept_days <= 731, f"admin thread kept {kept_days:.0f} days, expected ~730"


# ---- the tool surfaces must not overlap ----

def test_the_admin_service_advertises_admin_tools_and_the_customer_one_does_not():
    """Two layers, neither of them a runtime boolean.

    The customer model is never TOLD about an admin tool, and behind that the
    customer executor is wired to a server that does not implement one. This
    pins the first layer, which is the one a refactor could quietly invert.
    """
    from merlins_collection.services.bedrock import _TOOLS, _admin_tool_schemas

    admin_names = {t["toolSpec"]["name"] for t in _admin_tool_schemas()}
    customer_names = {t["toolSpec"]["name"] for t in _TOOLS}

    assert "get_profit_summary" in admin_names
    assert "get_profit_summary" not in customer_names
    assert "get_consignor_position" not in customer_names
    assert "find_pricing_outliers" not in customer_names
    # The display tools are shared on purpose — they hydrate cards for the panel
    # and execute in the backend, not on either MCP server.
    assert {"display_card", "set_display"} <= admin_names & customer_names


def test_the_admin_service_hydrates_with_the_admin_visibility_scope():
    """Otherwise an aging-stock answer silently drops the rows it is about."""
    from merlins_collection.dependencies import get_admin_bedrock_service
    from merlins_collection.services.bedrock import ADMIN_VISIBILITY

    svc = get_admin_bedrock_service()
    assert svc._visible is ADMIN_VISIBILITY
