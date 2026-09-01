"""RFC 0020 item 6: the admin analyst's Bedrock service gets HIGHER, real
guardrail values than the customer chat — a per-instance override on the
same `max_tool_turns`/`max_query_tool_calls_per_request` seam
`tools`/`system_prompt` already use (see `services/bedrock.py`'s
`BedrockChatService.__init__`).

Values (`admin_max_tool_turns=6`, `admin_max_query_tool_calls_per_request=14`)
come from `scripts/measure_admin_chat_latency.py`, extended with the four
RFC-0020 raw-listing tools and run live against the production table
(2026-08-30): a 14-call sequence mixing all eight admin tools measured
~15.6-16.9s of tool time across two runs (52-57% of the 30s Lambda budget),
over a home connection to us-east-1 — production, in-region, will be faster
still (same caveat CLAUDE.md already records for `list_inventory`'s shard
queries). `list_shows` was the single slowest tool measured (~2.4s median,
an N+1 `get_show_analytics` call per show) — well under the 10s per-call
`McpToolExecutor` timeout, but the reason the 14-call total isn't as cheap
as the RFC's pre-measurement "~1.0s per tool" estimate assumed.
"""

from unittest.mock import patch

from merlins_collection.dependencies import get_admin_bedrock_service, get_bedrock_service
from merlins_collection.services.bedrock import (
    _MAX_QUERY_TOOL_CALLS_PER_REQUEST,
    _MAX_TOOL_TURNS,
)


def test_the_admin_service_raises_both_ceilings_above_the_customer_defaults():
    with patch("merlins_collection.dependencies.boto3"):
        admin_service = get_admin_bedrock_service()

    assert admin_service._max_tool_turns > _MAX_TOOL_TURNS
    assert admin_service._max_query_tool_calls_per_request > _MAX_QUERY_TOOL_CALLS_PER_REQUEST


def test_the_customer_service_is_unaffected_by_the_admin_override():
    """`routers/chat.py` passes neither kwarg — the seam's whole point."""
    with patch("merlins_collection.dependencies.boto3"):
        customer_service = get_bedrock_service()

    assert customer_service._max_tool_turns == _MAX_TOOL_TURNS
    assert customer_service._max_query_tool_calls_per_request == _MAX_QUERY_TOOL_CALLS_PER_REQUEST
