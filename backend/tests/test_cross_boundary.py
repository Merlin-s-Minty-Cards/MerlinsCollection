"""Cross-boundary contract tests (Phase 18).

These tests assert that constants duplicated across the Python backend and the
TypeScript MCP server stay in sync. When either side drifts, these tests FAIL
instead of silently letting the website and Bedrock chat disagree.

Each test reads the TypeScript source file directly and extracts the relevant
constant via simple text parsing (no TS compiler needed) — the same approach
used by the tool-contract test. This is intentionally brittle: a refactor that
moves or renames the constant SHOULD break this test, because it means the
sync-point needs re-verification.
"""

import re
from pathlib import Path

from merlins_collection.models.inventory import _MARKET_FINISH_FALLBACK
from merlins_collection.services.customer_visibility import (
    CUSTOMER_VISIBLE_LOCATIONS as _CUSTOMER_VISIBLE_LOCATIONS,
)
from merlins_collection.services.dynamodb import INVENTORY_SHARD_COUNT

REPO_ROOT = Path(__file__).resolve().parents[2]
MCP_REPO = REPO_ROOT / "mcp-server" / "src" / "dynamodb-repository.ts"


def _read_mcp_source() -> str:
    return MCP_REPO.read_text(encoding="utf-8")


def test_shard_count_matches():
    """INVENTORY_SHARD_COUNT in Python must equal SHARD_COUNT in TypeScript."""
    source = _read_mcp_source()
    match = re.search(r"const\s+SHARD_COUNT\s*=\s*(\d+)", source)
    assert match is not None, "Could not find SHARD_COUNT in dynamodb-repository.ts"
    ts_shard_count = int(match.group(1))
    assert ts_shard_count == INVENTORY_SHARD_COUNT, (
        f"Shard count mismatch: Python={INVENTORY_SHARD_COUNT}, TypeScript={ts_shard_count}"
    )


def test_customer_visible_locations_match():
    """PUBLIC_LOCATIONS in TypeScript must equal _CUSTOMER_VISIBLE_LOCATIONS in Python."""
    source = _read_mcp_source()
    # Extract: const PUBLIC_LOCATIONS = new Set(["glass", "toploader"])
    match = re.search(
        r"const\s+PUBLIC_LOCATIONS\s*=\s*new\s+Set\(\[([^\]]+)\]\)",
        source,
    )
    assert match is not None, "Could not find PUBLIC_LOCATIONS in dynamodb-repository.ts"
    ts_locations = set(re.findall(r'"([^"]+)"', match.group(1)))
    assert ts_locations == _CUSTOMER_VISIBLE_LOCATIONS, (
        f"Location mismatch: Python={_CUSTOMER_VISIBLE_LOCATIONS}, TypeScript={ts_locations}"
    )


def test_finish_fallback_order_matches():
    """The finish-aware fallback chain in TypeScript must match _MARKET_FINISH_FALLBACK in Python.

    The CONCURRENCY warning in claude-progress.txt explicitly states these two
    must agree or the website and chatbot quote different prices.
    """
    source = _read_mcp_source()
    # Extract the fallbackOrder array from the marketPrice method.
    match = re.search(
        r"const\s+fallbackOrder\s*=\s*\[([^\]]+)\]",
        source,
    )
    assert match is not None, "Could not find fallbackOrder in dynamodb-repository.ts"
    # Parse the array items (skip the `finish` variable reference, keep string literals).
    ts_items = re.findall(r'"([^"]+)"', match.group(1))
    # The TypeScript array starts with the item's own finish (a variable), then
    # the canonical fallback. We compare only the string literals, which should
    # match _MARKET_FINISH_FALLBACK exactly.
    python_order = list(_MARKET_FINISH_FALLBACK)
    assert ts_items == python_order, (
        f"Finish fallback order mismatch:\n  Python: {python_order}\n  TypeScript: {ts_items}"
    )


def test_image_host_allowlists_match():
    """The frontend and backend image-host allowlists must stay in sync.

    The backend (routers/public.py) and frontend (lib/public.ts) each maintain
    an allowlist of image hosts. If they drift, the backend serves cards the
    frontend refuses to render (emptying the featured strip — Phase 16's bug).
    """
    from merlins_collection.routers.public import _ALLOWED_IMAGE_HOSTS

    frontend_public_ts = REPO_ROOT / "frontend" / "lib" / "public.ts"
    source = frontend_public_ts.read_text(encoding="utf-8")
    match = re.search(
        r"const\s+ALLOWED_IMAGE_HOSTS\s*=\s*new\s+Set\(\[([^\]]+)\]\)",
        source,
    )
    assert match is not None, "Could not find ALLOWED_IMAGE_HOSTS in frontend/lib/public.ts"
    fe_hosts = set(re.findall(r"'([^']+)'", match.group(1)))
    assert fe_hosts == _ALLOWED_IMAGE_HOSTS, (
        f"Image-host allowlist mismatch:\n  Backend: {_ALLOWED_IMAGE_HOSTS}\n  Frontend: {fe_hosts}"
    )
