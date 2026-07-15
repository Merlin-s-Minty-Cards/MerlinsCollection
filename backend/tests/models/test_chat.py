import pytest
from pydantic import ValidationError

from merlins_collection.models.chat import ChatRequest, ChatResponse


def test_chat_request_accepts_valid_message():
    req = ChatRequest(message="Do you have any Charizard cards?")
    assert req.message == "Do you have any Charizard cards?"


def test_chat_request_rejects_empty_message():
    with pytest.raises(ValidationError):
        ChatRequest(message="")


def test_chat_request_rejects_message_too_long():
    with pytest.raises(ValidationError):
        ChatRequest(message="x" * 4001)


def test_chat_request_accepts_message_at_max_length():
    req = ChatRequest(message="x" * 4000)
    assert len(req.message) == 4000


def test_chat_response_has_reply():
    resp = ChatResponse(reply="We have 3 Charizard cards in stock.")
    assert resp.reply == "We have 3 Charizard cards in stock."


def test_chat_response_accepts_empty_reply():
    resp = ChatResponse(reply="")
    assert resp.reply == ""
