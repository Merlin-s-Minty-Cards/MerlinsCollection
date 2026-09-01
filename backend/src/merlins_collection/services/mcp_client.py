"""MCP server client: bridges BedrockChatService's sync ``tool_executor``
callable to an MCP server subprocess speaking stdio.

Design constraints this class exists to satisfy:

- ``BedrockChatService.chat`` runs synchronously in FastAPI's threadpool, but
  the ``mcp`` SDK is async. A dedicated background thread runs an asyncio loop;
  calls hop onto it via ``run_coroutine_threadsafe``.
- anyio context managers must enter and exit in the same task, so one
  long-lived "runner" task owns the subprocess + session and holds them open
  until a stop event fires.
- One subprocess is shared by all calls (``ClientSession`` multiplexes by
  request id); a lock makes lazy startup race-free.
- Failures must degrade, never break chat: tool-level errors (``isError``
  results) are returned as text for the model to react to, while transport
  failures (spawn failure, crash, timeout) tear the session down — so the next
  call respawns — and return a JSON ``{"error": ...}`` string.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import threading
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeoutError

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)

#: Environment variables an MCP subprocess is allowed to inherit from this
#: process. An ALLOWLIST, not a filter-list, so a secret added to the backend
#: later is excluded by default rather than by remembering to exclude it.
#:
#: Why this is not `{**os.environ}` (which it was until 2026-08-27): under
#: Lambda that dict carries `ADMIN_API_KEY` and the task role's session
#: credentials for a role holding PutItem/DeleteItem/TransactWriteItems/Scan.
#: The customer MCP server was therefore holding a full-write admin credential,
#: which makes RFC 0018 decision 6's process boundary tool-SURFACE isolation
#: only — it confers no privilege isolation at all. Both servers need exactly
#: the AWS credential chain and enough of a shell to start; nothing else.
_ENV_ALLOWLIST = frozenset({
    # AWS credential chain + region resolution.
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_REGION",
    "AWS_DEFAULT_REGION",
    "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
    "AWS_CONTAINER_CREDENTIALS_FULL_URI",
    "AWS_CONTAINER_AUTHORIZATION_TOKEN",
    "AWS_WEB_IDENTITY_TOKEN_FILE",
    "AWS_ROLE_ARN",
    "AWS_ROLE_SESSION_NAME",
    "AWS_EC2_METADATA_DISABLED",
    "AWS_STS_REGIONAL_ENDPOINTS",
    # Enough environment to start an interpreter or a node binary at all.
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "TMPDIR",
    "PYTHONPATH",
    "PYTHONHOME",
    "NODE_PATH",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE",
})

# How long a healthy runner gets to exit via the stop event before being cancelled.
_GRACEFUL_EXIT_TIMEOUT = 2.0
# How long to wait for the runner task to release the subprocess on teardown.
_TEARDOWN_TIMEOUT = 10.0


#: The backend Lambda's own timeout, mirrored from
#: ``infra/lib/backend-stack.ts``. Every guard below is sized against it, and
#: ``test_request_time_budget.py`` reads the CDK source to keep the two equal —
#: raising one without the other leaves these looking correct and being wrong.
LAMBDA_REQUEST_BUDGET_SECONDS = 30.0

#: Ceiling on ONE tool call. Its job is to turn a single wedged tool into an
#: error string the model can narrate around, which requires that it fire with
#: enough of the request left for a final Bedrock turn to run. It was 30.0 —
#: the entire budget — so that error path had never once been reachable in
#: production: the Lambda died at the same instant the guard gave up.
#:
#: Measured 2026-08-27 (``scripts/measure_admin_chat_latency.py``, against the
#: live table over a home connection to us-east-1, which is pessimistic — the
#: DynamoDB legs are ten sequential round trips that cost ~5ms each in-region
#: and ~85ms here): **no tool on either server exceeds 1.0s.** The slowest is
#: ``get_profit_summary`` over a full year at 0.97s. Ten seconds is therefore
#: ~10x the worst real case, not a tight bound.
#:
#: **This bounds one anomaly, not N.** Nothing here caps the sum across a
#: request; ``bedrock._MAX_QUERY_TOOL_CALLS_PER_REQUEST`` bounds the count and
#: the Lambda timeout remains the backstop for the aggregate. Said plainly
#: because a guard whose reach is overstated is how the next person stops
#: looking.
DEFAULT_CALL_TIMEOUT_SECONDS = LAMBDA_REQUEST_BUDGET_SECONDS / 3

#: Ceiling on spawn + MCP handshake. Deliberately NOT lowered alongside the
#: call timeout: the measurement above puts a warm local spawn at 1.7s, but a
#: Lambda cold start runs a fresh Python interpreter importing boto3, mcp and
#: merlins_collection off a cold container filesystem, and that is a quantity
#: no measurement taken on this machine can stand in for. Tightening a bound
#: against a number you cannot measure is the guess this whole item exists to
#: remove.
DEFAULT_INIT_TIMEOUT_SECONDS = 15.0


class McpToolExecutor:
    """Callable ``(tool_name, tool_input) -> str`` backed by an MCP subprocess.

    Thread-safe; the subprocess is spawned lazily on first call and respawned
    after a crash. ``close()`` tears everything down (and a later call starts
    fresh).
    """

    def __init__(
        self,
        command: list[str],
        *,
        call_timeout: float = DEFAULT_CALL_TIMEOUT_SECONDS,
        init_timeout: float = DEFAULT_INIT_TIMEOUT_SECONDS,
        env: dict[str, str] | None = None,
    ) -> None:
        self._command = list(command)
        self._call_timeout = call_timeout
        self._init_timeout = init_timeout
        # Settings-derived entries beat inherited ones: pydantic-settings reads
        # .env without exporting to os.environ, so config the server needs
        # (table name, region) must be passed explicitly.
        self._env_overrides = dict(env or {})
        self._lock = threading.Lock()
        self._state: _SessionState | None = None

    def __call__(self, tool_name: str, tool_input: dict) -> str:
        try:
            state = self._ensure_session()
        except Exception as exc:
            logger.warning("MCP server unavailable (%s): %s", self._command, exc)
            return _error_json(f"MCP server unavailable: {exc}")

        try:
            future = asyncio.run_coroutine_threadsafe(
                state.session.call_tool(tool_name, tool_input), state.loop
            )
            result = future.result(timeout=self._call_timeout)
        except FutureTimeoutError:
            future.cancel()
            logger.warning("MCP tool call %r timed out after %ss", tool_name, self._call_timeout)
            self._teardown(state)
            return _error_json(
                f"MCP tool call '{tool_name}' timed out after {self._call_timeout} seconds"
            )
        except Exception as exc:
            logger.warning("MCP tool call %r failed: %s", tool_name, exc)
            self._teardown(state)
            return _error_json(f"MCP tool call '{tool_name}' failed: {exc}")

        # isError results are still data — the model can read the message and
        # recover (e.g. "Card not found"). Only transport failures tear down.
        texts = [
            block.text
            for block in result.content
            if getattr(block, "text", None) is not None
        ]
        if texts:
            return "\n".join(texts)
        return _error_json(f"MCP tool '{tool_name}' returned no text content")

    def close(self) -> None:
        """Stop the session, kill the subprocess, and join the loop thread."""
        self._teardown(None)

    # ---- session lifecycle ----

    def _child_env(self) -> dict[str, str]:
        """The environment handed to the subprocess: allowlist + explicit config.

        Built at spawn time rather than at construction so a respawn sees
        current values (rotated credentials, a refreshed session token) instead
        of a stale snapshot. Overrides always win and always arrive, because
        pydantic-settings reads `.env` without exporting to `os.environ` — the
        table name and region genuinely are not in the parent's environment.
        """
        inherited = {
            key: value
            for key, value in os.environ.items()
            if key in _ENV_ALLOWLIST
        }
        return {**inherited, **self._env_overrides}

    def _ensure_session(self) -> _SessionState:
        state = self._state
        if state is not None:
            return state
        with self._lock:
            if self._state is None:
                self._state = _SessionState.start(
                    self._command, self._child_env(), self._init_timeout
                )
            return self._state

    def _teardown(self, expected: _SessionState | None) -> None:
        """Retire a session. With ``expected`` set, only if it is still the
        current one — so a thread reacting to an old session's failure can't
        kill the fresh session another thread just respawned."""
        with self._lock:
            state = self._state
            if expected is not None and state is not expected:
                return
            self._state = None
        if state is not None:
            state.stop()


class _SessionState:
    """A running loop thread + MCP session; created whole or not at all."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        thread: threading.Thread,
        session: ClientSession,
        stop_event: asyncio.Event,
        runner: Future,
    ) -> None:
        self.loop = loop
        self.thread = thread
        self.session = session
        self._stop_event = stop_event
        self._runner = runner

    @classmethod
    def start(
        cls, command: list[str], env: dict[str, str], init_timeout: float
    ) -> _SessionState:
        # Explicit Proactor loop on Windows: asyncio subprocesses need it, and
        # a host (e.g. uvicorn) may have switched the global policy to Selector.
        if sys.platform == "win32":
            loop: asyncio.AbstractEventLoop = asyncio.ProactorEventLoop()
        else:
            loop = asyncio.new_event_loop()
        thread = threading.Thread(
            target=loop.run_forever, name="mcp-tool-executor", daemon=True
        )
        thread.start()

        ready: Future = Future()
        stop_event = asyncio.Event()

        async def _runner() -> None:
            try:
                # `env` is the full parent environment plus explicit overrides
                # (the SDK's default is a restricted set that would strip AWS
                # credentials/region from the server).
                params = StdioServerParameters(
                    command=command[0], args=command[1:], env=env
                )
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        ready.set_result(session)
                        await stop_event.wait()
            except BaseException as exc:  # noqa: BLE001 — surfaced via `ready`
                if not ready.done():
                    ready.set_exception(exc)

        runner = asyncio.run_coroutine_threadsafe(_runner(), loop)
        try:
            session = ready.result(timeout=init_timeout)
        except BaseException:
            cls._stop_loop(loop, thread, stop_event, runner)
            raise
        return cls(loop, thread, session, stop_event, runner)

    def stop(self) -> None:
        self._stop_loop(self.loop, self.thread, self._stop_event, self._runner)

    @staticmethod
    def _stop_loop(
        loop: asyncio.AbstractEventLoop,
        thread: threading.Thread,
        stop_event: asyncio.Event,
        runner: Future,
    ) -> None:
        if not loop.is_closed():
            try:
                loop.call_soon_threadsafe(stop_event.set)
            except RuntimeError:
                pass  # loop shut down between the check and the call
        try:
            # Let the runner exit its context managers — that's what actually
            # terminates the subprocess.
            runner.result(timeout=_GRACEFUL_EXIT_TIMEOUT)
        except FutureTimeoutError:
            # Runner is stuck before `await stop_event.wait()` (e.g. a hung
            # handshake). Cancel it so the context managers unwind and the
            # child process is killed rather than leaked.
            runner.cancel()
            try:
                runner.result(timeout=_TEARDOWN_TIMEOUT)
            except Exception:
                logger.warning("MCP runner did not exit after cancellation")
        except Exception:
            logger.debug("MCP runner did not exit cleanly", exc_info=True)
        if not loop.is_closed():
            try:
                loop.call_soon_threadsafe(loop.stop)
            except RuntimeError:
                pass
        thread.join(timeout=_TEARDOWN_TIMEOUT)
        if not thread.is_alive() and not loop.is_closed():
            loop.close()


def _error_json(message: str) -> str:
    return json.dumps({"error": message})
