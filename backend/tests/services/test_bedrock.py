from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from merlins_collection.services.bedrock import (
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

def test_chat_returns_text_on_end_turn():
    client = MagicMock()
    client.converse.return_value = _end_turn("We have 3 Charizard cards.")
    svc = _make_service(client)
    assert svc.chat("Do you have Charizard?") == "We have 3 Charizard cards."


def test_chat_sends_user_message_in_first_call():
    client = MagicMock()
    client.converse.return_value = _end_turn("Hello!")
    svc = _make_service(client)
    svc.chat("Any Pikachu?")

    call_kwargs = client.converse.call_args[1]
    messages = call_kwargs["messages"]
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

    assert result == "Found 1 Charizard at $50."
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
    assert svc.chat("Tell me about Pikachu") == "First part. Second part."


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
    assert result == "Found Mewtwo at $200."


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
