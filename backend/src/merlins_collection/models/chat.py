"""Request/response models for the ``/chat`` (AI chat mode) endpoint."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ChatTurn(BaseModel):
    """One prior turn of the conversation, replayed for follow-up context."""

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    """A user chat message plus optional prior turns.

    ``message`` is bounded to 1–4000 chars to reject empty / abusive input;
    ``history`` is capped so a client can't ship an unbounded Bedrock context.
    """

    message: str = Field(min_length=1, max_length=4000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _history_must_be_completed_exchanges(self) -> "ChatRequest":
        """Enforce what Bedrock Converse requires: strict user/assistant
        alternation, starting with a user turn — and ending with an assistant
        turn, since the new ``message`` is appended as the next user turn.
        Rejecting here yields a clear 422 instead of an opaque 502 upstream.
        """
        for i, turn in enumerate(self.history):
            expected = "user" if i % 2 == 0 else "assistant"
            if turn.role != expected:
                raise ValueError(
                    "history must alternate user/assistant turns, starting with user"
                )
        if len(self.history) % 2 != 0:
            raise ValueError(
                "history must end with an assistant turn (completed exchanges only)"
            )
        return self


class ChatResponse(BaseModel):
    """The assistant's text reply."""

    reply: str
