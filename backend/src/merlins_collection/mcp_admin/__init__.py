"""The admin analyst MCP server (RFC 0018).

**A separate PROCESS, deliberately — but a Python one.** Owner decision 6 is
that the admin tools live in their own MCP server so the customer chat cannot
name a tool that reads cost basis: "a process that never loaded the tool cannot
leak it". That decision says *separate server process*; it does not say
TypeScript, and RFC 0018's `mcp-server-admin/` (its own npm workspace, its own
Docker stage) was the RFC's assumption rather than something the owner chose.

Python wins here because of the money. RFC 0018's own top risk mitigation is
that every figure routes through the helpers the admin pages already use —
`services.ledger.is_countable`, `services.condition_pricing` — and those are
Python. A TypeScript server reading DynamoDB directly (the way `mcp-server/`
does) would have to re-implement profit aggregation in IEEE-754 doubles: a
parity test can pin a *value*, but it cannot pin a *call graph*, and
`services/ledger.py` enumerates its readers exhaustively precisely because the
failure mode is a reader that forgets to call it.

So this process imports those helpers directly, and `McpToolExecutor` spawns it
with `["python", "-m", "merlins_collection.mcp_admin"]` — a different binary,
which keeps decision 6's isolation the loud kind (which process starts) rather
than the quiet kind (a dependency-injection line).
"""

from merlins_collection.mcp_admin.server import build_server

__all__ = ["build_server"]
