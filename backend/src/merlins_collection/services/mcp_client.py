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

# How long a healthy runner gets to exit via the stop event before being cancelled.
_GRACEFUL_EXIT_TIMEOUT = 2.0
# How long to wait for the runner task to release the subprocess on teardown.
_TEARDOWN_TIMEOUT = 10.0


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
        call_timeout: float = 30.0,
        init_timeout: float = 15.0,
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

    def _ensure_session(self) -> _SessionState:
        state = self._state
        if state is not None:
            return state
        with self._lock:
            if self._state is None:
                # Environment is captured at spawn time so a respawn sees
                # current values, not a stale construction-time snapshot.
                env = {**os.environ, **self._env_overrides}
                self._state = _SessionState.start(
                    self._command, env, self._init_timeout
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
