"""Conversation-history logic for the ``/chat`` surface (RFC 0017).

Lives beside the router rather than inside ``BedrockChatService`` because none
of it involves a model: title derivation, the 50-thread cap, replay-window
assembly and transcript hydration are all pure operations over stored rows, and
they need to be testable without a Bedrock client. Same placement rationale as
``services/ledger.py``.

Every function here takes the caller's Cognito ``sub`` and refuses to work on a
thread that ``sub`` does not own -- ownership is not the router's job to
remember.
"""

from __future__ import annotations

from datetime import datetime, timezone

from botocore.exceptions import ClientError

from merlins_collection.models.chat import (
    CUSTOMER_SURFACE,
    MAX_TITLE_LENGTH,
    ChatTurn,
    ConversationDetail,
    ConversationMessage,
    ConversationSummary,
    DisplayPanel,
    in_surface,
    surface_of,
)
from merlins_collection.models.inventory import new_ulid

__all__ = ["in_surface", "surface_of"]  # re-exported: readers scope through here

#: Per-user, PER-SURFACE conversation cap (decision 8; per-surface from RFC
#: 0018). Shared across surfaces it would make 50 customer chats evict the
#: admin analyst threads Open Question 3 promises to keep for two years.
MAX_CONVERSATIONS = 50

#: Characters of the opening message used as a free title (decision 9).
TITLE_SOURCE_CHARS = 50

#: Completed exchanges replayed to Bedrock. Every replayed turn is re-billed as
#: input tokens on every subsequent message, so this is a cost ceiling, not a
#: capability limit -- the full thread stays stored and readable either way.
MAX_REPLAY_TURNS = 20

#: Transcript rows returned by a fetch. The backend runs behind a Lambda
#: Function URL in BUFFERED invoke mode, which caps a response at 6 MB; a
#: six-month thread of 4,000-character messages can pass that.
MAX_TRANSCRIPT_MESSAGES = 200

#: Distinct items hydrated per fetch, across the transcript AND the panel.
#: Without this a 200-message thread whose assistant turns each showed five
#: cards would issue ~1,000 hydrations for one click on a history row.
MAX_HYDRATED_ITEMS = 100

_FALLBACK_TITLE = "New conversation"


def now_iso() -> str:
    """UTC now, ISO 8601. One definition so stored timestamps sort correctly."""
    return datetime.now(timezone.utc).isoformat()


def derive_title(message: str) -> str:
    """A free title: the opening message's first ~50 characters.

    Decision 9 -- deliberately NOT a Bedrock summarization call, which would
    double the model calls on the first message of every thread, on a route
    that already fails closed on cost.
    """
    collapsed = " ".join((message or "").split())
    if not collapsed:
        return _FALLBACK_TITLE
    if len(collapsed) <= TITLE_SOURCE_CHARS:
        return collapsed
    return collapsed[:TITLE_SOURCE_CHARS] + "…"


def replay_turns(rows: list[dict]) -> list[ChatTurn]:
    """The bounded, well-formed history window handed to Bedrock.

    Two guards, and NEITHER IS DEAD CODE -- the reason is TTL, not partial
    writes. Messages are written in user/assistant pairs inside one
    transaction, so alternation holds at write time; but message rows expire
    INDIVIDUALLY on their own six-month clocks, so a thread older than the
    retention window loses its earliest rows one at a time. The moment a
    ``user`` row is reaped a beat before its ``assistant`` partner, the window
    genuinely begins with an assistant turn and Bedrock rejects the request.
    """
    turns = [
        ChatTurn(role=row["role"], content=str(row.get("content", ""))[:4000])
        for row in rows
        if row.get("role") in ("user", "assistant") and str(row.get("content", ""))
    ]
    # Bedrock requires the first turn to be `user`.
    while turns and turns[0].role != "user":
        turns.pop(0)
    # History is completed exchanges only.
    while turns and turns[-1].role != "assistant":
        turns.pop()
    return turns[-(MAX_REPLAY_TURNS * 2):]


def _summary(row: dict) -> ConversationSummary:
    return ConversationSummary(
        conversation_id=row["conv_id"],
        title=row.get("title") or _FALLBACK_TITLE,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        message_count=int(row.get("message_count", 0) or 0),
    )


def owned_rows(repo, sub: str, surface: str) -> list[dict]:
    """Every row ``sub`` owns ON ONE SURFACE, most recently used first.

    THE one scoped read. `list_summaries`, `prune_to_cap`, `clear_all` and
    `get_owned` all go through it, so the list, the count and the pruner cannot
    disagree about what is in scope -- the failure RFC 0018's risk table
    predicts and its own design walked into.
    """
    return [row for row in repo.list_conversations(sub) if in_surface(row, surface)]


def list_summaries(
    repo, sub: str, surface: str = CUSTOMER_SURFACE
) -> list[ConversationSummary]:
    """The history list: at most 50 rows, most recently used first."""
    return [_summary(row) for row in owned_rows(repo, sub, surface)]


def get_owned(repo, sub: str, conv_id: str, surface: str = CUSTOMER_SURFACE) -> dict | None:
    """One thread the caller owns ON THIS SURFACE, or ``None``.

    The surface check is not cosmetic: without it ``POST /admin/chat/`` accepts
    a customer ``conversation_id`` and appends cost basis and margins to a
    thread that ``GET /chat/conversations/{id}`` renders on the CUSTOMER
    surface. ``None`` (never a raise) is what lets the router answer 404 rather
    than 403, so a wrong-surface id is indistinguishable from a missing one.
    """
    for row in owned_rows(repo, sub, surface):
        if row.get("conv_id") == conv_id:
            return row
    return None


def prune_to_cap(repo, sub: str, surface: str = CUSTOMER_SURFACE) -> None:
    """Enforce the 50-thread cap before a new thread is written.

    Prunes the LEAST RECENTLY USED, not the oldest-created. A thread started in
    January and still used today outranks one started yesterday and abandoned.
    This also keeps pruning legible: the thread that disappears is always the
    one at the bottom of the history list, because the list sorts on the same
    field.

    SCOPED TO ONE SURFACE, and that is the whole point of this signature.
    Before RFC 0018 this read every row the sub owned and deleted everything
    past the 50th. The owner is an admin who also uses the customer chat, so a
    July margin analysis -- deliberately untouched, therefore
    least-recently-used -- was exactly what the 51st customer conversation
    evicted in October. Open Question 3's two-year retention only ever
    addressed TTL, and TTL is not the only thing that deletes rows.
    """
    rows = owned_rows(repo, sub, surface)  # already sorted most-recent-first
    for stale in rows[MAX_CONVERSATIONS - 1:]:
        repo.delete_conversation(sub, stale["conv_id"])


def start_conversation(
    repo, sub: str, message: str, surface: str = CUSTOMER_SURFACE
) -> dict:
    """Create a thread implicitly, for a message that named none.

    Pruning happens here rather than in a background job, and before the write,
    so the cap is never transiently exceeded.
    """
    prune_to_cap(repo, sub, surface)
    stamp = now_iso()
    return {
        "conv_id": new_ulid(),
        "sub": sub,
        "surface": surface,
        "title": derive_title(message),
        "created_at": stamp,
        "updated_at": stamp,
        "message_count": 0,
        "last_seq": 0,
        "panel_item_ids": [],
    }


def append_exchange(
    repo,
    row: dict,
    user_message: str,
    assistant_reply: str,
    artifact_item_ids: list[str],
    panel_item_ids: list[str],
    _retrying: bool = False,
) -> dict:
    """Persist one completed user/assistant exchange and update the thread.

    Called only AFTER Bedrock has answered. A model failure therefore leaves no
    trace -- no thread holding a question with no answer, and no conversation
    created for a request that produced nothing.

    ON A CONCURRENT-APPEND COLLISION THIS RETRIES ONCE rather than surfacing a
    409. RFC 0017 originally specified the 409, and that was wrong for where
    this call sits: Bedrock has already run and already been billed, so telling
    the client to retry throws away a paid-for answer AND bills a second call
    to regenerate it. Re-reading `last_seq` and appending after the winner
    costs nothing, preserves both exchanges, and is invisible to both users.
    One retry only -- a second collision means sustained contention, and the
    router's own guard then serves the reply while logging that it was not
    persisted.
    """
    stamp = now_iso()
    seq = int(row.get("last_seq", 0) or 0)

    # The thread's own surface, so its messages share its retention clock — a
    # two-year thread whose messages expire in six months is an empty thread.
    surface = surface_of(row)
    repo.put_conversation_message(row["conv_id"], row["sub"], {
        "seq": seq + 1,
        "role": "user",
        "content": user_message[:4000],
        "artifact_item_ids": [],
        "created_at": stamp,
    }, surface=surface)
    repo.put_conversation_message(row["conv_id"], row["sub"], {
        "seq": seq + 2,
        "role": "assistant",
        "content": assistant_reply[:4000],
        # IDs only -- see ConversationMessage.artifacts on why storing the card
        # records would re-serve a stale price.
        "artifact_item_ids": artifact_item_ids[:50],
        "created_at": stamp,
    }, surface=surface)

    row = {
        **row,
        "last_seq": seq + 2,
        "message_count": int(row.get("message_count", 0) or 0) + 2,
        "updated_at": stamp,
        "panel_item_ids": panel_item_ids[:50],
    }
    # The conditional write is the serialization point for this thread — see
    # InventoryRepository.put_conversation. `seq` is what we read before the
    # (multi-second) Bedrock call, so a concurrent append that already moved
    # `last_seq` makes this fail rather than silently overwriting its messages.
    try:
        repo.put_conversation(row, expected_last_seq=seq)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            raise
        if _retrying:
            raise
        fresh = repo.get_conversation(row["sub"], row["conv_id"])
        if fresh is None:
            # The thread was deleted mid-flight. Nothing to append to, and
            # recreating it would resurrect something the owner just removed.
            raise
        return append_exchange(
            repo,
            fresh,
            user_message,
            assistant_reply,
            artifact_item_ids,
            panel_item_ids,
            _retrying=True,
        )
    return row


def _hydrate_many(repo, item_ids: list[str]) -> dict:
    """One deduplicated, capped hydration pass shared by transcript and panel.

    Deduplication is what makes this cheap in the normal case: a card shown in
    four turns of a refining search is one hydration, not four.
    """
    from merlins_collection.services.bedrock import _hydrate_item

    hydrated: dict = {}
    for item_id in item_ids:
        if len(hydrated) >= MAX_HYDRATED_ITEMS:
            break
        if item_id in hydrated:
            continue
        card = _hydrate_item(repo, item_id)
        if card is not None:
            hydrated[item_id] = card
    return hydrated


def build_detail(repo, sub: str, row: dict) -> ConversationDetail:
    """A resumed thread, with every card re-hydrated LIVE (decision 4).

    Prices and availability are current, never snapshots. An item that has
    since sold hydrates to None and simply drops out -- the reply text still
    mentions it, which is correct: the text records what was said, the card is
    a claim about what is currently available and at what price.
    """
    conv_id = row["conv_id"]
    # Fetch one MORE than we return, so "truncated" means genuinely truncated:
    # `len(rows) >= MAX` would report a thread of exactly MAX as cut short.
    rows = repo.get_conversation_messages(conv_id, limit=MAX_TRANSCRIPT_MESSAGES + 1)
    truncated = len(rows) > MAX_TRANSCRIPT_MESSAGES
    rows = rows[-MAX_TRANSCRIPT_MESSAGES:]

    # The stored `sub` is ASSERTED, not merely carried — a field kept "for
    # defense in depth" that nothing reads is decoration. A row whose owner
    # disagrees is dropped rather than rendered. Equality, not `in (None, sub)`:
    # nothing is backfilled here, so every row this code can ever see was
    # written with a `sub`, and accepting a missing one would hand a
    # hypothetical malformed row to whoever asked first.
    rows = [r for r in rows if r.get("sub") == sub]

    panel_ids = [str(i) for i in (row.get("panel_item_ids") or [])]
    # Panel IDs first so the newest thing on screen never loses its cards to
    # the cap; then transcript IDs newest-turn-first.
    wanted = list(panel_ids)
    for r in reversed(rows):
        wanted.extend(str(i) for i in (r.get("artifact_item_ids") or []))
    hydrated = _hydrate_many(repo, wanted)

    messages = [
        ConversationMessage(
            seq=int(r["seq"]),
            role=r["role"],
            content=str(r.get("content", "")),
            artifacts=[
                hydrated[i]
                for i in (str(x) for x in (r.get("artifact_item_ids") or []))
                if i in hydrated
            ],
            created_at=r["created_at"],
        )
        for r in rows
    ]

    return ConversationDetail(
        conversation_id=conv_id,
        title=row.get("title") or _FALLBACK_TITLE,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        messages=messages,
        truncated=truncated,
        panel=DisplayPanel(
            cards=[hydrated[i] for i in panel_ids if i in hydrated],
            truncated=False,
        ),
    )


def rename(repo, row: dict, title: str) -> ConversationSummary:
    """Rename a thread WITHOUT touching ``updated_at``.

    A rename is not use: it must not reorder the history list, and it must not
    reprieve a thread from pruning or push its expiry forward.
    """
    row = {**row, "title": title.strip()[:MAX_TITLE_LENGTH]}
    repo.put_conversation(row)
    return _summary(row)


def clear_all(repo, sub: str, surface: str = CUSTOMER_SURFACE) -> None:
    """Delete every thread owned by ``sub``.

    Bounded at 50 threads, but NOT bounded in rows -- so index rows go first,
    in one pass, and the message sweeps follow. The history list is empty the
    moment the index pass completes, which is the whole observable contract;
    whatever message rows remain are unreachable and expire on their own TTL.
    """
    for conv_id in repo.delete_all_conversations(sub, surface):
        repo.delete_conversation_messages(conv_id)
