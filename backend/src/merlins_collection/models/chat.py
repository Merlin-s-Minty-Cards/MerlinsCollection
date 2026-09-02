"""Request/response models for the ``/chat`` (AI chat mode) endpoint."""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ChatTurn(BaseModel):
    """One prior turn of the conversation, replayed for follow-up context."""

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    """A user chat message, its conversation, and the client's current panel.

    RFC 0017: the transcript is now SERVER-owned. ``conversation_id`` selects
    the thread; omitting it starts a new one implicitly (owner decision — "New
    chat" stays a zero-latency client-side reset, and a thread opened but never
    used never exists to occupy one of the 50 slots).

    Only item IDs may round-trip from the client. Display data is always
    rebuilt from the inventory repository during the Bedrock tool loop.
    """

    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = Field(default=None, max_length=64)
    panel_item_ids: list[str] = Field(default_factory=list, max_length=50)
    # DEPRECATED and IGNORED (RFC 0017). Kept for exactly one release so a
    # CloudFront-cached old client bundle gets a working chat instead of a 422
    # -- the client bundle is baked at build time and cannot be updated in
    # lockstep with this API. Nothing reads it: the server loads the real
    # transcript from storage, which is also what stops a client forging
    # assistant turns to put words in the model's mouth. Remove the field once
    # the deployed bundle is known to have rolled over.
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _validate_request_context(self) -> "ChatRequest":
        """Bound round-tripped item IDs.

        The user/assistant alternation checks that used to live here are gone
        with client-sent history: the server now guarantees a well-formed
        replay window by construction (services/conversations.replay_turns).
        """
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
    # RFC 0017. Always present, including for a thread this request just
    # created implicitly -- it is how the client learns which thread it is in
    # without a second round trip.
    conversation_id: str = ""
    title: str = ""


# ---- RFC 0017: conversation history ----

#: Upper bound on a title, whether derived or user-supplied. Matches
#: display_name_override's precedent for an admin-typed string.
MAX_TITLE_LENGTH = 200

#: The two chat surfaces (RFC 0018). A thread belongs to exactly one.
#:
#: These live here, in a leaf module, so both ``services/conversations.py`` and
#: ``services/dynamodb.py`` can import them without a cycle — the TTL branch is
#: in the repository while the scoping predicate is in the service, and neither
#: should be spelling a bare "admin" string of its own.
CUSTOMER_SURFACE = "customer"
ADMIN_SURFACE = "admin"


def surface_of(row: dict) -> str:
    """The surface a stored conversation row belongs to.

    **The default is a FACT, not a guess.** Nothing is backfilled: every row
    written before RFC 0018 is a customer thread, because ``/admin/chat/`` did
    not exist to write any other kind. Same precedent as ``Transaction.batch_id``
    — optional, defaulted, no migration, one code path with no legacy branch.
    """
    return str(row.get("surface") or CUSTOMER_SURFACE)


def in_surface(row: dict, surface: str) -> bool:
    """THE scoping predicate. Every reader that cares about a surface calls this.

    RFC 0018's own risk table flags "`surface` filter forgotten in one reader"
    and names the list and the count. It missed the third and worst one:
    ``prune_to_cap`` DELETES rows, so an unscoped prune silently evicts the
    two-year admin threads Open Question 3 promises to keep. There is one
    definition, it lives here, and list/count/prune/clear-all/get all call it —
    the same shape as ``services/triage.in_triage_scope``, and for the same
    reason: two spellings of a scope is how a queue and its badge start
    disagreeing.
    """
    return surface_of(row) == surface


class ConversationSummary(BaseModel):
    """One row of the history list. Carries no message content."""

    conversation_id: str
    title: str
    created_at: datetime
    updated_at: datetime
    # ADVISORY ONLY. DynamoDB TTL deletion is best-effort (typically within 48h
    # of expiry), so after a message row is reaped this can read higher than
    # the number of rows that still exist. Nothing computes from it.
    message_count: int = 0


class ConversationMessage(BaseModel):
    """One stored turn, with its inline cards hydrated LIVE at fetch time.

    ``artifacts`` is never deserialized from storage -- only the item IDs are
    stored, and they are re-hydrated on read. Storing the card records instead
    would re-serve a months-old price in a tile that looks identical to a
    current one, which is the exact failure RFC 0016's "IDs only" rule exists
    to prevent.
    """

    seq: int
    role: Literal["user", "assistant"]
    content: str
    artifacts: list[DisplayedCard] = Field(default_factory=list)
    created_at: datetime


class ConversationDetail(BaseModel):
    """A resumed thread: transcript plus its live-hydrated panel."""

    conversation_id: str
    title: str
    created_at: datetime
    updated_at: datetime
    messages: list[ConversationMessage] = Field(default_factory=list)
    # True when older turns exist but were not returned -- the transcript is
    # capped so one response cannot exceed the Lambda Function URL's 6 MB
    # buffered-response limit.
    truncated: bool = False
    panel: DisplayPanel = Field(default_factory=DisplayPanel)


class ConversationList(BaseModel):
    conversations: list[ConversationSummary] = Field(default_factory=list)


class ConversationRenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=MAX_TITLE_LENGTH)
