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

import json
import re
from decimal import Decimal
from pathlib import Path

from merlins_collection.models.inventory import _MARKET_FINISH_FALLBACK
from merlins_collection.services.condition_pricing import (
    _TIER_MULTIPLIERS,
    _TIER_ORDER,
)
from merlins_collection.services.customer_visibility import (
    CUSTOMER_VISIBLE_LOCATIONS as _CUSTOMER_VISIBLE_LOCATIONS,
)
from merlins_collection.services.dynamodb import INVENTORY_SHARD_COUNT

REPO_ROOT = Path(__file__).resolve().parents[2]
MCP_REPO = REPO_ROOT / "mcp-server" / "src" / "dynamodb-repository.ts"
MCP_CONDITION_PRICING = REPO_ROOT / "mcp-server" / "src" / "condition-pricing.ts"
ACQUISITION_RATIO_CASES = (
    REPO_ROOT / "shared" / "test-fixtures" / "acquisition-ratio-cases.json"
)
CUSTOMER_VISIBILITY_CASES = (
    REPO_ROOT / "shared" / "test-fixtures" / "customer-visibility-cases.json"
)


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

    These two must agree or the website and chatbot quote different prices for
    the same card. ``_MARKET_FINISH_FALLBACK`` in ``models/inventory.py`` is the
    canonical order and carries the full rule.
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


# ---- condition multipliers: the seam that CLAIMED to be pinned and was not ----
#
# `mcp-server/src/condition-pricing.ts` has said since it was written that the
# multipliers "are pinned on both sides by tests so a silent divergence fails
# loudly rather than mispricing stock". That was FALSE. Until 2026-08-27 this
# file pinned four things — shard count, customer-visible locations, the finish
# fallback order, and the image-host allowlist — and the multiplier table was
# not among them. Each side had only its OWN test with independently hardcoded
# expectations (`test_condition_pricing.py`, `dynamodb-repository.test.ts`), so
# re-tuning the Python table and its own test went green with TypeScript stale.
#
# This is the money path CLAUDE.md measured at -18.5% of customer-visible value
# (a DMG card was being shown at ~6.7x what the business valued it at), and the
# two halves of /inventory — filter mode and chat mode — read from these two
# separate tables. A divergence prices the same card two different ways
# depending on which half the customer is looking at, which is exactly what the
# docstring promised could not happen.


def _read_mcp_condition_pricing() -> str:
    return MCP_CONDITION_PRICING.read_text(encoding="utf-8")


def _parse_ts_multipliers(source: str) -> dict[str, str]:
    """Extract the TIER_MULTIPLIERS object literal as {tier: literal-text}."""
    block = re.search(
        r"const\s+TIER_MULTIPLIERS\s*:[^=]*=\s*\{(.*?)\}", source, re.S
    )
    assert block is not None, "Could not find TIER_MULTIPLIERS in condition-pricing.ts"
    return dict(re.findall(r"(\w+)\s*:\s*([\d.]+)", block.group(1)))


def test_condition_multipliers_match():
    """Every tier multiplier must be identical in Python and TypeScript."""
    ts = _parse_ts_multipliers(_read_mcp_condition_pricing())
    py = {tier.value: value for tier, value in _TIER_MULTIPLIERS.items()}

    assert set(ts) == set(py), (
        f"Tier sets differ: TypeScript={sorted(ts)}, Python={sorted(py)}"
    )
    for tier, py_value in py.items():
        assert Decimal(ts[tier]) == py_value, (
            f"Multiplier mismatch for {tier}: Python={py_value}, TypeScript={ts[tier]}"
        )


def test_condition_tier_order_matches():
    """The best-to-worst order drives every `+`/`-` midpoint, so it must match too.

    A reordered list does not change any single multiplier but silently changes
    which neighbouring tier `LP+` averages with — a divergence that the
    multiplier test above cannot see.
    """
    source = _read_mcp_condition_pricing()
    match = re.search(r"const\s+TIER_ORDER\s*=\s*\[(.*?)\]", source, re.S)
    assert match is not None, "Could not find TIER_ORDER in condition-pricing.ts"
    ts_order = re.findall(r'"(\w+)"', match.group(1))
    py_order = [tier.value for tier in _TIER_ORDER]
    assert ts_order == py_order, (
        f"Tier order mismatch: Python={py_order}, TypeScript={ts_order}"
    )


# ---- acquisition_ratio (RFC 0024 T1): a shared-fixture pin, not a source parse ----
#
# `acquisition_ratio` / `acquisitionRatio` is a computed function, not a
# literal constant table, so the regex-over-TS-source trick the rest of this
# file uses cannot pin it — there is no literal answer sitting in the source
# for a regex to extract. Instead both languages' test suites load ONE shared
# oracle (`shared/test-fixtures/acquisition-ratio-cases.json`) and assert
# their own implementation against it independently. If both suites pass, the
# two implementations agree by transitivity through the shared fixture — the
# same guarantee this file's other tests give directly, without requiring a
# Node subprocess inside a pytest run (this module's own docstring commits to
# "no TS compiler needed").
#
# frontend/lib/__tests__/acquisition.test.ts is the other half of this pin.


def _load_acquisition_ratio_cases() -> list[dict]:
    return json.loads(ACQUISITION_RATIO_CASES.read_text(encoding="utf-8"))["cases"]


def test_acquisition_ratio_matches_shared_cases():
    """Python's acquisition_ratio agrees with the shared cross-boundary fixture.

    The TypeScript mirror (acquisitionRatio) is pinned against the identical
    file in frontend/lib/__tests__/acquisition.test.ts.
    """
    from merlins_collection.services.acquisition import acquisition_ratio

    cases = _load_acquisition_ratio_cases()
    assert len(cases) >= 7, "The shared fixture lost cases — restore it, don't trim this assertion"

    for case in cases:
        market = Decimal(case["market"]) if case["market"] is not None else None
        cost = Decimal(case["cost"]) if case["cost"] is not None else None
        expected = Decimal(case["expected"]) if case["expected"] is not None else None

        actual = acquisition_ratio(market, cost)
        assert actual == expected, (
            f"case {case['name']!r}: market={case['market']}, cost={case['cost']} "
            f"-> Python gave {actual}, fixture expects {expected}"
        )


# ---- RFC 0025 T2/T3 — the sticker-price visibility rule, pinned on both sides ----
#
# `is_customer_visible` (services/customer_visibility.py) and its TypeScript
# mirror `isPublicInventory` (mcp-server/src/dynamodb-repository.ts) are a
# SECURITY boundary — CLAUDE.md's standing warning about this MCP file is that
# it has claimed cross-language parity before that no test ever actually
# checked. This is that test: a shared case table, asserted independently by
# each language against a plain SimpleNamespace-shaped row so no full
# InventoryItem construction is required for a predicate that only ever reads
# five attributes.
#
# mcp-server/src/__tests__/customer-visibility-cases.test.ts is the other half.


def _load_customer_visibility_cases() -> list[dict]:
    return json.loads(CUSTOMER_VISIBILITY_CASES.read_text(encoding="utf-8"))["cases"]


def test_customer_visibility_matches_shared_cases():
    """Python's is_customer_visible agrees with the shared cross-boundary fixture."""
    from types import SimpleNamespace

    from merlins_collection.models.inventory import ItemStatus
    from merlins_collection.services.customer_visibility import is_customer_visible

    cases = _load_customer_visibility_cases()
    assert len(cases) >= 8, "The shared fixture lost cases — restore it, don't trim this assertion"

    for case in cases:
        row = SimpleNamespace(
            status=ItemStatus(case["status"]),
            kind=case["kind"],
            location=case["location"],
            factory_sealed=case["factory_sealed"],
            sticker_price=(
                Decimal(case["sticker_price"]) if case["sticker_price"] is not None else None
            ),
        )
        actual = is_customer_visible(row)
        assert actual == case["expected"], (
            f"case {case['name']!r}: Python gave {actual}, fixture expects {case['expected']}"
        )
