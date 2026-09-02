"""The admin MCP server must actually SPAWN and speak MCP (RFC 0018 item 4/5).

Every other test in this area imports `build_server` in-process, which proves
the tools are registered but not that the decision behind them works. The claim
being made is specific: `McpToolExecutor` can spawn
`python -m merlins_collection.mcp_admin` — the SAME transport class, a
different binary — and hold a session with it. If that is wrong, it is wrong in
production and nowhere else.

Deliberately does NOT call a tool. The subprocess is a real OS process outside
this test's moto mock, so a tool call would reach real DynamoDB. The handshake
and the tool listing touch no table (the repository is constructed lazily and
boto3 opens no socket until a request), so this stays hermetic while still
proving the part that could break.
"""

import shutil
import sys

import pytest

from merlins_collection.services.mcp_client import McpToolExecutor


@pytest.fixture
def admin_executor():
    executor = McpToolExecutor(
        [sys.executable, "-m", "merlins_collection.mcp_admin"],
        env={"AWS_REGION": "us-east-1", "DYNAMODB_TABLE_NAME": "merlins-cards-test",
             # No real credentials are used — nothing here reaches the table —
             # but boto3 must not stall probing the instance metadata service.
             "AWS_ACCESS_KEY_ID": "testing", "AWS_SECRET_ACCESS_KEY": "testing",
             "AWS_EC2_METADATA_DISABLED": "true"},
        init_timeout=60.0,
    )
    yield executor
    executor.close()


@pytest.mark.skipif(shutil.which(sys.executable) is None, reason="no interpreter")
def test_the_admin_server_spawns_and_completes_an_mcp_handshake(admin_executor):
    """A different binary on the same transport — decision 6's isolation, working.

    `_ensure_session()` performs the real stdio spawn plus the MCP initialize
    handshake. A failure here means the module is not importable in a fresh
    interpreter, the entry point is wrong, or the server never connects — all
    of which would otherwise surface only as a 503 in production.
    """
    state = admin_executor._ensure_session()
    assert state is not None


def test_calling_an_unknown_tool_degrades_instead_of_crashing(admin_executor):
    """The transport's contract: a failure is text the model can react to.

    Same behaviour the customer executor already has. Asserted here because the
    admin loop must not turn a typo'd tool name into a 500 on a money question.
    """
    result = admin_executor("no_such_tool", {})
    assert isinstance(result, str)
    assert "error" in result.lower() or "unknown" in result.lower()


# ---- the two executors must stay two ----

def test_the_admin_and_customer_executors_are_different_processes():
    """Decision 6's isolation, asserted at the wiring rather than assumed.

    Both are `lru_cache` singletons of the same class, so the ONLY thing making
    them different servers is the command each is built with. If that ever
    collapses to one command, the customer chat is being served admin tools and
    nothing else in the system would notice.
    """
    from merlins_collection.dependencies import (
        get_admin_mcp_executor,
        get_mcp_executor,
    )

    admin = get_admin_mcp_executor()
    customer = get_mcp_executor()
    try:
        assert admin is not customer
        assert admin._command != customer._command
        assert "mcp_admin" in " ".join(admin._command)
        assert "mcp_admin" not in " ".join(customer._command)
    finally:
        get_admin_mcp_executor.cache_clear()
        get_mcp_executor.cache_clear()


def test_shutting_down_never_spawns_a_process_that_was_never_used():
    """Both executors are lazy; a deployment nobody asks an analyst question of
    must not pay for a second subprocess at boot — or at shutdown."""
    from merlins_collection.dependencies import (
        get_admin_mcp_executor,
        shutdown_admin_mcp_executor,
    )

    get_admin_mcp_executor.cache_clear()
    shutdown_admin_mcp_executor()  # must not raise, must not construct
    assert get_admin_mcp_executor.cache_info().currsize == 0
