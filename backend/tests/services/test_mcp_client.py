"""McpToolExecutor: the sync bridge between BedrockChatService's tool_executor
callable and the MCP server subprocess (spawned over stdio).

The boundary here is real: tests spawn tests/fixtures/fake_mcp_server.py — an
actual MCP stdio server — as a subprocess. Only the server implementation is
fake; the transport, protocol, and process lifecycle are production-real.

Contract under test:
- __call__(tool_name, tool_input) -> str, safe to call from many threads
- tool-level errors (isError results) come back as text — data for the model
- transport-level failures (spawn failure, crash, timeout) return a JSON string
  with an "error" key instead of raising, so one bad call never 500s the chat
- the subprocess is shared across calls, respawned after a crash, and torn down
  by close()
"""

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from merlins_collection.services.mcp_client import McpToolExecutor

FAKE_SERVER = Path(__file__).resolve().parents[1] / "fixtures" / "fake_mcp_server.py"
CMD = [sys.executable, str(FAKE_SERVER)]


@pytest.fixture
def executor():
    ex = McpToolExecutor(CMD, call_timeout=15.0)
    yield ex
    ex.close()


def _pid(out: str) -> str:
    assert ":pid:" in out, f"unexpected echo output: {out!r}"
    return out.rsplit(":pid:", 1)[1]


def test_executor_returns_tool_result_text(executor):
    out = executor("echo", {"text": "hello"})
    assert out.startswith("echo:hello:pid:")


def test_executor_returns_tool_error_as_text_without_raising(executor):
    out = executor("boom", {})
    assert "tool exploded" in out


def test_executor_surfaces_unknown_tool_as_error_text(executor):
    out = executor("no_such_tool", {})
    assert "no_such_tool" in out
    assert "error" in out.lower() or "unknown" in out.lower()


def test_executor_reuses_one_subprocess_across_calls(executor):
    first = _pid(executor("echo", {"text": "a"}))
    second = _pid(executor("echo", {"text": "b"}))
    assert first == second


def test_executor_concurrent_calls_share_one_subprocess(executor):
    with ThreadPoolExecutor(max_workers=6) as pool:
        outs = list(pool.map(lambda i: executor("echo", {"text": str(i)}), range(6)))
    pids = {_pid(o) for o in outs}
    assert len(pids) == 1


def test_executor_times_out_and_returns_error_json():
    ex = McpToolExecutor(CMD, call_timeout=2.0)
    try:
        out = ex("slow", {"seconds": 30})
        parsed = json.loads(out)
        assert "error" in parsed
        assert "timed out" in parsed["error"].lower()
    finally:
        ex.close()


def test_executor_recovers_after_server_crash(executor):
    first = _pid(executor("echo", {"text": "before"}))

    crash_out = executor("crash", {})
    assert "error" in json.loads(crash_out)

    after = executor("echo", {"text": "after"})
    assert after.startswith("echo:after:pid:")
    assert _pid(after) != first


def test_executor_returns_error_json_when_server_cannot_start():
    ex = McpToolExecutor(
        [sys.executable, str(FAKE_SERVER.parent / "does_not_exist.py")],
        call_timeout=10.0,
    )
    try:
        out = ex("echo", {"text": "x"})
        assert "error" in json.loads(out)
    finally:
        ex.close()


def test_executor_env_overrides_take_precedence_over_parent_env(monkeypatch):
    """Explicit env entries (backend settings) must beat inherited os.environ ones.

    The backend reads config from .env via pydantic-settings, which does NOT
    export to os.environ — so settings like DYNAMODB_TABLE_NAME must be passed
    to the subprocess explicitly or the MCP server falls back to its defaults.
    """
    monkeypatch.setenv("MERLINS_MCP_ENV_PROBE", "from-parent")
    ex = McpToolExecutor(
        CMD, call_timeout=15.0, env={"MERLINS_MCP_ENV_PROBE": "from-settings"}
    )
    try:
        out = ex("env_probe", {"name": "MERLINS_MCP_ENV_PROBE"})
        assert out == "from-settings"
    finally:
        ex.close()


def test_executor_unresponsive_server_fails_fast_without_hanging():
    """A server that never completes the handshake must not wedge the caller.

    The runner task has to be cancelled on teardown — otherwise the failure
    path waits out the full teardown timeout and leaks the child process.
    """
    import time

    ex = McpToolExecutor(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        call_timeout=2.0,
        init_timeout=2.0,
    )
    started = time.monotonic()
    try:
        out = ex("echo", {"text": "x"})
        assert "error" in json.loads(out)
    finally:
        ex.close()
    # init timeout (2s) plus prompt cancellation — not 12+s of teardown stalls.
    assert time.monotonic() - started < 8


def test_executor_subprocess_inherits_parent_environment(executor, monkeypatch):
    """AWS credentials/region env vars must reach the MCP server subprocess.

    (The mcp SDK's default is a *restricted* environment that would strip
    AWS_ACCESS_KEY_ID etc., silently breaking DynamoDB access in the tools.)
    """
    monkeypatch.setenv("MERLINS_MCP_ENV_PROBE", "reached-the-subprocess")
    out = executor("env_probe", {"name": "MERLINS_MCP_ENV_PROBE"})
    assert out == "reached-the-subprocess"


def test_executor_close_is_idempotent_and_allows_restart(executor):
    first = _pid(executor("echo", {"text": "a"}))
    executor.close()
    executor.close()  # second close must be a no-op, not an error

    out = executor("echo", {"text": "b"})
    assert out.startswith("echo:b:pid:")
    assert _pid(out) != first
