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
    """The catalog projection needed by display surfaces.

    Council r2 self-review (M5, carried from council-r1-verdict.md advisor-
    architect M5): ``set_id``, ``rarity``, ``image_large`` and ``market_price``
    were on the wire with no reader on either display surface
    (``DisplayPanel.tsx``, ``ChatPanel.tsx``) — ``market_price`` in particular
    duplicated the exact same condition-adjusted figure already carried on
    ``DisplayedCard.listed_price`` for a raw item (see ``_hydrate_item``). All
    four were dropped. ``card_id`` survives even though its only reader
    (an ``.startswith('ja:')`` JP-badge inference) was replaced by
    ``DisplayedCard.language`` — it is a reasonable general-purpose identity
    field, unlike the other four, and wasn't independently flagged.
    """

    card_id: str
    name: str
    set_name: str
    number: str
    image_small: str


class DisplayedCard(BaseModel):
    """A server-hydrated inventory item safe to render in the UI."""

    item_id: str
    # Council r2 ruling on the r1 "known consequence": narrowed from
    # Literal["raw", "graded", "sealed", "bulk"]. is_customer_visible's
    # CUSTOMER_KINDS is {"raw", "graded"} and _hydrate_item returns None
    # before ever constructing a DisplayedCard for any other kind, so
    # "sealed"/"bulk" were provably unreachable here. Narrowing makes that a
    # second, independent enforcement layer: a regression in the visibility
    # gate now fails closed (pydantic ValidationError, caught by
    # _hydrate_item's broad except) instead of silently emitting a
    # DisplayedCard the customer wire was never meant to carry.
    kind: Literal["raw", "graded"]
    card: CardSummary | None = None
    display_name: str | None = None
    # Inventory rows may honestly be unpriced. The field remains required so a
    # model/client cannot omit pricing state, while None renders as "Price N/A".
    listed_price: Decimal | None
    current_market_value: Decimal | None = None
    condition: str | None = None
    # Council r2 self-review M5: had no reader on either display surface —
    # dropped, same rationale as CardSummary's trim above.
    company: str | None = None
    grade: Decimal | None = None
    grade_label: str | None = None
    cert_number: str | None = None
    # Council r2 (advisor-architect M4 / advisor-contrarian, carried from
    # council-r1-verdict.md): the JP badge on both display surfaces used to be
    # inferred from `card.card_id.startswith('ja:')`, which is unavailable for
    # an uncatalogued item (card is None) — an uncatalogued Japanese card
    # silently lost its badge. `language` lives on the base InventoryItem
    # independent of any catalog match, so it survives exactly that case.
    # "EN"/"JP", mirroring models.inventory.Language; None only when hydration
    # itself failed upstream (never for a real customer-visible item).
    language: str | None = None
    # cert_image_url intentionally NOT a field here (RFC 0016 Council r1
    # checklist item 5): it is admin-scoped, provider-supplied, and only
    # scheme-validated (not content-validated) — see InventoryItem's own
    # field docs. It must not reach the customer-facing /chat wire.


class DisplayPanel(BaseModel):
    """Hydrated panel state; fullscreen deliberately remains client-only.

    No ``open`` field (decision 23): open/closed is inferred purely from
    whether ``cards`` is non-empty. The five panel-mutation tools
    (open/close/add/remove/reorder) were collapsed into a single
    ``set_display(item_ids)``; an empty list IS the explicit close
    primitive, so there is no longer any incremental state that could
    desynchronize from what the cards list itself says.
    """

    cards: list[DisplayedCard] = Field(default_factory=list, max_length=50)
    truncated: bool = False


class ChatResponse(BaseModel):
    """The assistant reply plus trusted inline and panel display records."""

    reply: str
    artifacts: list[DisplayedCard] = Field(default_factory=list)
    panel: DisplayPanel = Field(default_factory=DisplayPanel)
