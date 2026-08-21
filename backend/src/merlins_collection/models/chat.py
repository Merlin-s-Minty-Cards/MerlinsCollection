"""Request/response models for the ``/chat`` (AI chat mode) endpoint."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ChatTurn(BaseModel):
    """One prior turn of the conversation, replayed for follow-up context."""

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    """A user chat message plus optional prior turns and panel item IDs.

    Only item IDs may round-trip from the client. Display data is always rebuilt
    from the inventory repository during the Bedrock tool loop.
    """

    message: str = Field(min_length=1, max_length=4000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)
    panel_item_ids: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def _validate_request_context(self) -> "ChatRequest":
        """Validate Bedrock history ordering and bound round-tripped item IDs."""
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
        for item_id in self.panel_item_ids:
            if len(item_id) > 100:
                raise ValueError("panel_item_ids contains an item ID over 100 characters")
        return self


class CardSummary(BaseModel):
    """The catalog projection needed by display surfaces."""

    card_id: str
    name: str
    set_id: str
    set_name: str
    number: str
    rarity: str | None = None
    image_small: str
    image_large: str
    market_price: Decimal | None = None


class DisplayedCard(BaseModel):
    """A server-hydrated inventory item safe to render in the UI."""

    item_id: str
    kind: Literal["raw", "graded", "sealed", "bulk"]
    card: CardSummary | None = None
    display_name: str | None = None
    # Inventory rows may honestly be unpriced. The field remains required so a
    # model/client cannot omit pricing state, while None renders as "Price N/A".
    listed_price: Decimal | None
    current_market_value: Decimal | None = None
    condition: str | None = None
    finish: str | None = None
    company: str | None = None
    grade: Decimal | None = None
    grade_label: str | None = None
    cert_number: str | None = None
    cert_image_url: str | None = None


class DisplayPanel(BaseModel):
    """Hydrated panel state; fullscreen deliberately remains client-only."""

    open: bool | None = None
    cards: list[DisplayedCard] = Field(default_factory=list, max_length=50)
    truncated: bool = False


class ChatResponse(BaseModel):
    """The assistant reply plus trusted inline and panel display records."""

    reply: str
    artifacts: list[DisplayedCard] = Field(default_factory=list)
    panel: DisplayPanel = Field(default_factory=DisplayPanel)
