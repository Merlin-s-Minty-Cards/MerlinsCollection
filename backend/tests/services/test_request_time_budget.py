"""The 30s Lambda budget must actually bound one chat request (RFC 0018, 8b.3).

RFC-0018 never mentions the Lambda timeout, but it is the binding constraint on
the whole feature: `infra/lib/backend-stack.ts` gives the backend function 30
seconds, and `services/bedrock.py` records that RFC-0016's council already cut
`_MAX_TOOL_TURNS` from 12 to 5 specifically to fit inside it. Roadmap item 8b.3
asked for a measurement before trusting four new analyst tools in production.

**The measurement said the tools are cheap** (`scripts/measure_admin_chat_latency.py`,
2026-08-27: no tool on either server exceeds 1.0s, and the worst five-call
sequence the turn ceiling permits is 3.6s over a home connection to us-east-1).
What it exposed instead is that the two guards meant to bound a request could
not do it:

1. `McpToolExecutor`'s default `call_timeout` was **30.0s — the entire Lambda
   budget**. A guard that can only fire at the exact moment there is no time
   left to use its result is not a guard.
2. Query-tool invocations per request were **unbounded**. `_MAX_TOOL_TURNS`
   bounds round trips to the model, not tool calls: one assistant turn may emit
   any number of `toolUse` blocks and every one of them is executed. The
   display tools already have a per-request ceiling for exactly this reason
   (Council item 11); the MCP query tools did not.

These tests pin both, plus the relationship to the CDK value they are derived
from — so raising the Lambda timeout in `infra/` without revisiting them goes
red instead of silently leaving the guards mis-sized.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import MagicMock

from merlins_collection.services.bedrock import _MAX_QUERY_TOOL_CALLS_PER_REQUEST
from merlins_collection.services.mcp_client import (
    LAMBDA_REQUEST_BUDGET_SECONDS,
    McpToolExecutor,
)

BACKEND_STACK = Path(__file__).resolve().parents[3] / "infra" / "lib" / "backend-stack.ts"


def test_the_recorded_lambda_budget_matches_the_cdk_stack():
    """The constant these guards are sized against must be the deployed one.

    Same cross-boundary pinning as `test_cross_boundary.py` does for the
    TypeScript MCP server: a number duplicated across two languages drifts
    unless a test reads both. Raising `timeout` in CDK without re-sizing the
    guards below would leave them correct-looking and wrong.
    """
    source = BACKEND_STACK.read_text(encoding="utf-8")
    match = re.search(r"timeout:\s*cdk\.Duration\.seconds\((\d+)\)", source)
    assert match is not None, f"Could not find the Lambda timeout in {BACKEND_STACK}"
    assert float(match.group(1)) == LAMBDA_REQUEST_BUDGET_SECONDS


def test_a_hung_tool_call_gives_up_with_time_left_to_report_it():
    """The per-call timeout must leave room for a final model turn.

    Its whole purpose is to turn one wedged tool into an error string the model
    can narrate around instead of a dead request. At 30.0s it returned that
    string at precisely the moment the Lambda was being killed, so the error
    path had never once been reachable in production.

    Half the budget is the loosest bound that still guarantees a final Bedrock
    turn can run; the measured worst case for any real tool is under 1.0s, so
    this is not tight.
    """
    executor = McpToolExecutor(["/nonexistent"])
    assert executor._call_timeout <= LAMBDA_REQUEST_BUDGET_SECONDS / 2


def test_query_tool_calls_are_bounded_per_request():
    """A request cannot drive unbounded tool I/O, however many blocks a turn emits.

    Mirrors `_MAX_HYDRATION_BLOCKS_PER_REQUEST`, which bounds the display tools
    for the same reason. Without this, `_MAX_TOOL_TURNS = 5` bounds only how
    many times the model is consulted — a single turn emitting forty `toolUse`
    blocks runs forty full inventory fan-outs.
    """
    assert _MAX_QUERY_TOOL_CALLS_PER_REQUEST > 0
    # Comfortably above the five-call sequence a real analyst question was
    # measured taking, so the ceiling never fires on legitimate work.
    assert _MAX_QUERY_TOOL_CALLS_PER_REQUEST >= 10


def _tool_use_turn(count: int) -> dict:
    """One assistant turn emitting `count` query-tool blocks.

    This is the shape `_MAX_TOOL_TURNS` does not bound: it counts assistant
    messages, and a single message may carry any number of `toolUse` blocks.
    """
    return {
        "output": {
            "message": {
                "role": "assistant",
                "content": [
                    {"toolUse": {"toolUseId": f"t{i}",
                                 "name": "search_inventory",
                                 "input": {}}}
                    for i in range(count)
                ],
            }
        },
        "stopReason": "tool_use",
    }


def test_one_turn_cannot_run_unbounded_tool_calls():
    """Forty `toolUse` blocks in one turn must not run forty inventory walks.

    Each admin tool call walks the whole inventory across ten shard partitions,
    so this is real I/O and real seconds, not a theoretical bound. The excess
    must come back as a message the model can read — the same shape the display
    ceiling already uses — rather than a raise, so a chatty model degrades into
    a partial answer instead of a 500.
    """
    executor = MagicMock(return_value='{"results": []}')
    client = MagicMock()
    client.converse.side_effect = [
        _tool_use_turn(40),
        {"output": {"message": {"role": "assistant",
                                "content": [{"text": "done"}]}},
         "stopReason": "end_turn"},
    ]

    service = __import__(
        "merlins_collection.services.bedrock", fromlist=["BedrockChatService"]
    ).BedrockChatService(
        client=client, model_id="test-model", tool_executor=executor, repo=None
    )
    service.chat("how much profit last month?")

    assert executor.call_count <= _MAX_QUERY_TOOL_CALLS_PER_REQUEST, (
        f"ran {executor.call_count} tool calls in one turn"
    )


def test_the_refused_calls_tell_the_model_why():
    """A silently-dropped tool result is how a model states a figure it never got.

    The blocks past the ceiling still need a `toolResult` — Bedrock requires one
    per `toolUse` id — and its content must say the work was refused. An empty
    result reads as "the tool found nothing", which is a confident wrong answer
    on a money question.
    """
    executor = MagicMock(return_value='{"results": []}')
    client = MagicMock()
    client.converse.side_effect = [
        _tool_use_turn(40),
        {"output": {"message": {"role": "assistant",
                                "content": [{"text": "done"}]}},
         "stopReason": "end_turn"},
    ]
    service = __import__(
        "merlins_collection.services.bedrock", fromlist=["BedrockChatService"]
    ).BedrockChatService(
        client=client, model_id="test-model", tool_executor=executor, repo=None
    )
    service.chat("how much profit last month?")

    # `messages` is mutated in place across turns, so every recorded call holds
    # the SAME list object — index into the final state, not into a call.
    messages = client.converse.call_args_list[-1].kwargs["messages"]
    results_message = next(
        m for m in messages
        if m.get("role") == "user"
        and any("toolResult" in block for block in m.get("content", []))
    )
    texts = [
        block["toolResult"]["content"][0]["text"]
        for block in results_message["content"]
    ]
    assert len(texts) == 40, "every toolUse id must get a toolResult back"
    refusals = [t for t in texts if "limit" in json.loads(t).get("error", "").lower()]
    assert len(refusals) == 40 - _MAX_QUERY_TOOL_CALLS_PER_REQUEST
