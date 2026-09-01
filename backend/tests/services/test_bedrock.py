from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from merlins_collection.services.bedrock import (
    _ADMIN_SYSTEM_PROMPT,
    _SYSTEM_PROMPT,
    BedrockChatService,
    BedrockContentFilteredError,
    BedrockLoopError,
    BedrockServiceError,
    BedrockThrottledError,
)

# ---- response builders ----

def _end_turn(text: str) -> dict:
    return {
        "output": {
            "message": {
                "role": "assistant",
                "content": [{"text": text}],
            }
        },
        "stopReason": "end_turn",
    }


def _tool_use(tool_name: str, tool_id: str, input_: dict, *, prefix: str = "") -> dict:
    content = []
    if prefix:
        content.append({"text": prefix})
    content.append({"toolUse": {"toolUseId": tool_id, "name": tool_name, "input": input_}})
    return {
        "output": {
            "message": {
                "role": "assistant",
                "content": content,
            }
        },
        "stopReason": "tool_use",
    }


def _client_error(code: str) -> ClientError:
    return ClientError(
        {"Error": {"Code": code, "Message": "test error"}},
        "Converse",
    )


def _make_service(client, tool_executor=None) -> BedrockChatService:
    if tool_executor is None:
        tool_executor = MagicMock(return_value='{"results": []}')
    return BedrockChatService(
        client=client,
        model_id="anthropic.claude-3-5-sonnet-20241022-v2:0",
        tool_executor=tool_executor,
    )


# ---- tests ----

def test_system_prompt_forbids_naming_a_card_without_displaying_it():
    # Owner report, 2026-08-25: a customer asked about a specific card and
    # the model just named it in prose instead of calling display_card/
    # set_display -- the same "name alone never identifies a card" rule
    # CLAUDE.md states for admin card-picker UIs, but for the model's own
    # reply behavior, which the prompt didn't say explicitly enough for the
    # model to follow reliably even though it already told the model not to
    # write prices/conditions/set numbers in prose.
    lowered = _SYSTEM_PROMPT.lower()
    assert "name alone" in lowered
    assert "never" in lowered and "name" in lowered


def test_admin_system_prompt_tells_the_model_all_time_needs_no_dates():
    # Owner report 2026-08-28: asked for "All time", the analyst asked back
    # for exact start/end dates instead of computing the full history itself.
    lowered = _ADMIN_SYSTEM_PROMPT.lower()
    assert "all time" in lowered
    assert "omit" in lowered


def test_admin_system_prompt_tells_the_model_to_surface_a_defaulted_period():
    # Adversarial review, 2026-08-28: "all time" is bounded (see
    # `_ALL_TIME_LOOKBACK_YEARS`), so a model that omits dates and then reports
    # the figure as if it covered literally everything is confidently wrong
    # once the ledger outgrows that window. `get_profit_summary`'s response
    # already reports the real dates it used (`period.start`/`period.end`);
    # the prompt has to tell the model that signal exists and to use it.
    lowered = _ADMIN_SYSTEM_PROMPT.lower()
    assert "period" in lowered


# ---- RFC 0020 item 7: librarian framing, tool-selection, math-trust ----


def test_admin_system_prompt_encourages_broad_research_rather_than_giving_up():
    # RFC 0020 Feature Goal: "like it is a librarian in a library... use its
    # own logic to gather information as if it were doing research itself".
    # Before this, the model treated "no single tool matches this exact
    # question" as unanswerable rather than researching across tools.
    lowered = _ADMIN_SYSTEM_PROMPT.lower()
    assert "librarian" in lowered
    assert "research" in lowered or "cross-reference" in lowered or "look things up" in lowered


def test_admin_system_prompt_prefers_a_narrow_tool_when_one_directly_answers():
    # RFC 0020 System prompt changes #2: a preference order, not a hard rule
    # — get_profit_summary/find_aging_stock/get_consignor_position/
    # find_pricing_outliers already did the correct computation, so reaching
    # for a raw list_* tool and re-deriving it is strictly more work for the
    # same answer.
    lowered = _ADMIN_SYSTEM_PROMPT.lower()
    assert "get_profit_summary" in lowered
    assert "prefer" in lowered


def test_admin_system_prompt_forbids_summing_raw_transaction_rows_for_profit():
    # RFC 0020 System prompt changes #3, THE math-trust boundary: trade cash
    # legs double-count and voided rows must be excluded — get_profit_summary
    # already does both correctly; a raw sum over list_transactions rows must
    # not become the model's own profit/revenue arithmetic.
    lowered = _ADMIN_SYSTEM_PROMPT.lower()
    assert "list_transactions" in lowered
    assert "never sum" in lowered or "do not sum" in lowered
    assert "is_countable" in lowered


def test_chat_returns_text_on_end_turn():
    client = MagicMock()
    client.converse.return_value = _end_turn("We have 3 Charizard cards.")
    svc = _make_service(client)
    assert svc.chat("Do you have Charizard?")["reply"] == "We have 3 Charizard cards."


def test_chat_sends_user_message_in_first_call():
    client = MagicMock()
    client.converse.return_value = _end_turn("Hello!")
    svc = _make_service(client)
    svc.chat("Any Pikachu?")

    call_kwargs = client.converse.call_args[1]
    messages = call_kwargs["messages"]
    assert messages[0]["role"] == "user"
    assert messages[0]["content"][0]["text"] == "Any Pikachu?"


def test_chat_threads_history_before_the_new_message():
    """Prior turns are sent to Converse ahead of the new user message, in order."""
    from merlins_collection.models.chat import ChatTurn

    client = MagicMock()
    client.converse.return_value = _end_turn("The LP copy at $85.")
    svc = _make_service(client)

    svc.chat(
        "Which are under $100?",
        [
            ChatTurn(role="user", content="What Charizards do you have?"),
            ChatTurn(role="assistant", content="3 in stock."),
        ],
    )

    messages = client.converse.call_args[1]["messages"]
    assert [m["role"] for m in messages[:3]] == ["user", "assistant", "user"]
    assert messages[0]["content"][0]["text"] == "What Charizards do you have?"
    assert messages[1]["content"][0]["text"] == "3 in stock."
    assert messages[2]["content"][0]["text"] == "Which are under $100?"


def test_chat_without_history_starts_with_the_new_message():
    """No history means nothing precedes the new user message.

    (The service mutates the messages list in place, so only the head of the
    list is a reliable assertion target — see test_chat_appends_tool_result...)
    """
    client = MagicMock()
    client.converse.return_value = _end_turn("Hello!")
    svc = _make_service(client)
    svc.chat("Any Pikachu?")

    messages = client.converse.call_args[1]["messages"]
    assert messages[0]["role"] == "user"
    assert messages[0]["content"][0]["text"] == "Any Pikachu?"


def test_chat_calls_tool_and_continues_on_tool_use():
    client = MagicMock()
    tool_executor = MagicMock(return_value='[{"name": "Charizard", "price": 50}]')
    client.converse.side_effect = [
        _tool_use("search_inventory", "tid-1", {"name": "Charizard"}),
        _end_turn("Found 1 Charizard at $50."),
    ]
    svc = _make_service(client, tool_executor)

    result = svc.chat("Do you have Charizard?")

    assert result["reply"] == "Found 1 Charizard at $50."
    assert client.converse.call_count == 2
    tool_executor.assert_called_once_with("search_inventory", {"name": "Charizard"})


def test_chat_appends_tool_result_before_second_call():
    """The second converse call must include the tool result in the messages list."""
    client = MagicMock()
    tool_executor = MagicMock(return_value="some result")
    client.converse.side_effect = [
        _tool_use("get_inventory_summary", "tid-2", {}),
        _end_turn("Summary done."),
    ]
    svc = _make_service(client, tool_executor)
    svc.chat("Summarize inventory")

    # messages list is mutated in-place; by the time we inspect it, a 4th entry
    # (the end_turn assistant reply) has been appended — so check index 2 directly.
    second_call_messages = client.converse.call_args_list[1][1]["messages"]
    tool_result_message = second_call_messages[2]  # [user, asst-tooluse, user-toolresult, ...]
    assert tool_result_message["role"] == "user"
    tool_result_block = tool_result_message["content"][0]["toolResult"]
    assert tool_result_block["toolUseId"] == "tid-2"
    assert tool_result_block["content"][0]["text"] == "some result"


def test_chat_concatenates_multiple_text_blocks():
    client = MagicMock()
    client.converse.return_value = {
        "output": {
            "message": {
                "role": "assistant",
                "content": [
                    {"text": "First part. "},
                    {"text": "Second part."},
                ],
            }
        },
        "stopReason": "end_turn",
    }
    svc = _make_service(client)
    assert svc.chat("Tell me about Pikachu")["reply"] == "First part. Second part."


def test_chat_raises_loop_error_when_tool_turns_exceed_limit():
    client = MagicMock()
    # Always return tool_use — the service must stop and raise after the limit
    client.converse.return_value = _tool_use("search_inventory", "tid-loop", {"name": "x"})
    svc = _make_service(client)

    with pytest.raises(BedrockLoopError):
        svc.chat("Keep searching forever")


def test_chat_raises_throttled_error_on_throttling_exception():
    client = MagicMock()
    client.converse.side_effect = _client_error("ThrottlingException")
    svc = _make_service(client)

    with pytest.raises(BedrockThrottledError):
        svc.chat("Are you there?")


def test_chat_raises_service_error_on_model_error():
    client = MagicMock()
    client.converse.side_effect = _client_error("ModelErrorException")
    svc = _make_service(client)

    with pytest.raises(BedrockServiceError):
        svc.chat("Are you there?")


def test_chat_raises_content_filtered_error_on_guardrail():
    client = MagicMock()
    client.converse.return_value = {
        "output": {
            "message": {"role": "assistant", "content": []}
        },
        "stopReason": "content_filtered",
    }
    svc = _make_service(client)

    with pytest.raises(BedrockContentFilteredError):
        svc.chat("Some flagged message")


def test_chat_raises_on_unknown_stop_reason():
    client = MagicMock()
    client.converse.return_value = {
        "output": {
            "message": {"role": "assistant", "content": []}
        },
        "stopReason": "guardrail_intervened",
    }
    svc = _make_service(client)

    with pytest.raises(BedrockServiceError):
        svc.chat("Some message")


def test_chat_includes_end_turn_text_after_tool_use():
    """Text in the end_turn response after tool use is returned correctly."""
    client = MagicMock()
    client.converse.side_effect = [
        _tool_use("search_inventory", "tid-3", {"name": "Mewtwo"}, prefix="Searching now..."),
        _end_turn("Found Mewtwo at $200."),
    ]
    svc = _make_service(client)
    result = svc.chat("Any Mewtwo?")
    assert result["reply"] == "Found Mewtwo at $200."


def test_chat_raises_service_error_when_tool_use_has_no_tool_blocks():
    """tool_use stop reason with no toolUse content blocks must not loop silently."""
    client = MagicMock()
    client.converse.return_value = {
        "output": {
            "message": {
                "role": "assistant",
                "content": [{"text": "Let me check..."}],  # no toolUse block
            }
        },
        "stopReason": "tool_use",
    }
    svc = _make_service(client)

    with pytest.raises(BedrockServiceError):
        svc.chat("Search for Pikachu")


# ---- RFC 0018 item 2: the advertised tool set and prompt are CONSTRUCTOR state ----
#
# Both were module constants baked into `chat()`, so every caller got the
# customer contract whether it wanted it or not. The admin analyst chat needs a
# different tool set AND a different prompt — the customer prompt is entirely
# about the display panel and ends with "Do not answer questions unrelated to
# Pokemon cards or this business", which is wrong for a margin question.
#
# The defaults are unchanged, so every other test in this file still pins the
# customer behaviour; these two prove the seam exists.

def test_the_service_advertises_the_tool_schemas_it_was_constructed_with():
    client = MagicMock()
    client.converse.return_value = _end_turn("ok")
    only_tool = [{"toolSpec": {
        "name": "get_profit_summary",
        "description": "Margin by period.",
        "inputSchema": {"json": {"type": "object", "properties": {}}},
    }}]

    service = BedrockChatService(
        client=client, model_id="m", tool_executor=MagicMock(), tools=only_tool
    )
    service.chat("what did I net at Portland?")

    advertised = client.converse.call_args.kwargs["toolConfig"]["tools"]
    assert advertised == only_tool
    names = [t["toolSpec"]["name"] for t in advertised]
    assert "search_inventory" not in names, (
        "a service given admin schemas must not still advertise the customer set"
    )


def test_the_service_uses_the_system_prompt_it_was_constructed_with():
    client = MagicMock()
    client.converse.return_value = _end_turn("ok")

    service = BedrockChatService(
        client=client, model_id="m", tool_executor=MagicMock(),
        system_prompt="You are a read-only analyst.",
    )
    service.chat("margin?")

    assert client.converse.call_args.kwargs["system"] == [
        {"text": "You are a read-only analyst."}
    ]


def test_the_defaults_are_still_the_customer_contract():
    """The seam must not change what an unparameterised caller gets.

    `routers/chat.py` constructs this service without either argument, so a
    changed default is a silent change to the customer chat.
    """
    from merlins_collection.services.bedrock import _TOOLS

    client = MagicMock()
    client.converse.return_value = _end_turn("ok")
    _make_service(client).chat("hi")

    assert client.converse.call_args.kwargs["toolConfig"]["tools"] == _TOOLS


# ---- RFC 0020 item 6: max_tool_turns / max_query_tool_calls_per_request ----
#
# `_MAX_TOOL_TURNS`/`_MAX_QUERY_TOOL_CALLS_PER_REQUEST` used to be module
# constants read directly inside `chat()`, shared by every instance — so
# raising them for the librarian tools' benefit would have silently widened
# the customer surface too (adversarial review of RFC 0020's first draft).
# They are now CONSTRUCTOR state, same seam `tools`/`system_prompt` already
# use, defaulting to the same module constants so `routers/chat.py` (which
# passes neither) is unaffected.


def _multi_tool_use_turn(count: int) -> dict:
    return {
        "output": {
            "message": {
                "role": "assistant",
                "content": [
                    {"toolUse": {"toolUseId": f"t{i}", "name": "search_inventory",
                                 "input": {}}}
                    for i in range(count)
                ],
            }
        },
        "stopReason": "tool_use",
    }


def test_max_tool_turns_is_a_constructor_override():
    client = MagicMock()
    client.converse.return_value = _tool_use("search_inventory", "tid", {})
    service = BedrockChatService(
        client=client, model_id="m", tool_executor=MagicMock(return_value="{}"),
        max_tool_turns=1,
    )

    with pytest.raises(BedrockLoopError):
        service.chat("keep searching forever")

    # One allowed turn, then the loop must raise on the second — not the
    # module default of 5.
    assert client.converse.call_count == 2


def test_max_query_tool_calls_per_request_is_a_constructor_override():
    executor = MagicMock(return_value='{"results": []}')
    client = MagicMock()
    client.converse.side_effect = [_multi_tool_use_turn(5), _end_turn("done")]
    service = BedrockChatService(
        client=client, model_id="m", tool_executor=executor,
        max_query_tool_calls_per_request=2,
    )

    service.chat("how much profit last month?")

    assert executor.call_count == 2, (
        "a per-instance override of 2 must cap tool execution at 2, not the "
        "module default of 10"
    )


def test_the_default_guardrails_are_still_the_customer_values():
    """An unparameterised caller (`routers/chat.py`) must see no change."""
    from merlins_collection.services.bedrock import (
        _MAX_QUERY_TOOL_CALLS_PER_REQUEST,
        _MAX_TOOL_TURNS,
    )

    client = MagicMock()
    client.converse.return_value = _tool_use("search_inventory", "tid", {})
    service = _make_service(client)

    assert service._max_tool_turns == _MAX_TOOL_TURNS
    assert service._max_query_tool_calls_per_request == _MAX_QUERY_TOOL_CALLS_PER_REQUEST
