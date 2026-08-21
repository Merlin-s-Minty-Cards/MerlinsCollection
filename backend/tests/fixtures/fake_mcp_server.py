"""A minimal MCP stdio server used as the real-protocol test boundary for
``McpToolExecutor``. Spawned as a subprocess by tests/services/test_mcp_client.py;
speaks genuine MCP over stdio, no node or AWS required.

Tools deliberately cover the executor's failure matrix: normal result, tool-level
error (isError), slow call (timeout), and hard process crash.
"""

import os
import time

try:
    from mcp.server.fastmcp import FastMCP
except ModuleNotFoundError:  # mcp v2 renamed the module
    from mcp.server.mcpserver import MCPServer as FastMCP

server = FastMCP("fake-inventory")


@server.tool()
def echo(text: str = "") -> str:
    """Echo the input back, tagged with this process's pid."""
    return f"echo:{text}:pid:{os.getpid()}"


@server.tool()
def boom() -> str:
    """Always fails — exercises tool-level (isError) results."""
    raise RuntimeError("tool exploded")


@server.tool()
def slow(seconds: float) -> str:
    """Sleep, then answer — exercises call timeouts."""
    time.sleep(seconds)
    return "finally done"


@server.tool()
def crash() -> str:
    """Kill the server process mid-call — exercises respawn-after-crash."""
    os._exit(1)


@server.tool()
def env_probe(name: str) -> str:
    """Report an environment variable — exercises env inheritance (AWS creds)."""
    return os.environ.get(name, "<missing>")


if __name__ == "__main__":
    server.run()
