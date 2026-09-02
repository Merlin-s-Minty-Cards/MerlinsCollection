"""``/admin/chat`` — the read-only admin analyst chat (RFC 0018).

Structurally the customer ``/chat`` router's sibling, with three deliberate
differences:

1. **A 403 on the ROUTE, unlike the 404 on a thread id.** A 404 on a thread id
   hides whether that id exists; a 403 here hides nothing, because the route's
   existence is not a secret and an admin who has lost their group membership
   needs to be told that rather than shown an empty room.
2. **Every conversation call is scoped to ``ADMIN_SURFACE``**, so the two thread
   lists never mix and an id from one surface is a 404 on the other.
3. **A different Bedrock service instance** — different tool schemas, different
   system prompt, and an executor wired to a different subprocess. The customer
   chat is never handed any of the three.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status

from merlins_collection.dependencies import (
    get_admin_bedrock_service,
    get_repo,
)
from merlins_collection.models.auth import AuthenticatedUser
from merlins_collection.models.chat import (
    ADMIN_SURFACE,
    ChatRequest,
    ChatResponse,
    ConversationDetail,
    ConversationList,
    ConversationRenameRequest,
    ConversationSummary,
)
from merlins_collection.rate_limit import rate_limit_admin_chat, rate_limit_search
from merlins_collection.services import conversations as convo
from merlins_collection.services.bedrock import (
    BedrockChatService,
    BedrockContentFilteredError,
    BedrockLoopError,
    BedrockServiceError,
    BedrockThrottledError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["admin-chat"])


def _owned_or_404(repo, sub: str, conversation_id: str) -> dict:
    """The caller's own ADMIN thread, or a 404.

    Wrong-surface is deliberately indistinguishable from not-found: a customer
    thread's id must not be confirmable through the admin routes any more than
    the reverse.
    """
    row = convo.get_owned(repo, sub, conversation_id, ADMIN_SURFACE)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found."
        )
    return row


@router.post("/", response_model=ChatResponse)
def admin_chat(
    body: ChatRequest,
    user: AuthenticatedUser = Depends(rate_limit_admin_chat),
    service: BedrockChatService = Depends(get_admin_bedrock_service),
    repo=Depends(get_repo),
) -> ChatResponse:
    """Answer an analyst question over the business's own numbers.

    Read-only (owner decision 1): every tool this service can name is
    `readOnlyHint`, and the server behind them registers no write path at all.
    """
    if body.conversation_id:
        row = _owned_or_404(repo, user.sub, body.conversation_id)
        history = convo.replay_turns(
            repo.get_conversation_messages(
                row["conv_id"], limit=convo.MAX_REPLAY_TURNS * 2
            )
        )
    else:
        row = convo.start_conversation(repo, user.sub, body.message, ADMIN_SURFACE)
        history = []

    try:
        result = service.chat(body.message, history, body.panel_item_ids)
    except BedrockThrottledError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Service is temporarily busy — please try again shortly.",
        ) from exc
    except BedrockLoopError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Your request required too many steps to complete. Try rephrasing.",
        ) from exc
    except BedrockContentFilteredError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Your message could not be processed due to content policy.",
        ) from exc
    except BedrockServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Upstream AI service error.",
        ) from exc

    response = ChatResponse.model_validate(result)

    # Same "already paid for it" rule as the customer route: Bedrock has been
    # billed by this point, so a DynamoDB blip must not turn a delivered answer
    # into a 500. The thread simply does not gain this exchange, loudly logged.
    try:
        row = convo.append_exchange(
            repo,
            row,
            body.message,
            response.reply,
            [card.item_id for card in response.artifacts],
            [card.item_id for card in response.panel.cards],
        )
    except Exception:  # noqa: BLE001 — deliberately broad, see above
        logger.exception(
            "failed to persist admin chat exchange for conversation %s; reply still served",
            row.get("conv_id"),
        )

    response.conversation_id = row["conv_id"]
    response.title = row["title"]
    return response


# ---- admin conversation history ----
#
# `rate_limit_search` (fails OPEN), never `rate_limit_admin_chat` (fails
# CLOSED): reading your own analysis must not fail because a WRITE could not be
# metered. Same reasoning as the customer routes.


@router.get("/conversations", response_model=ConversationList)
def list_admin_conversations(
    user: AuthenticatedUser = Depends(rate_limit_search),
    repo=Depends(get_repo),
) -> ConversationList:
    """The caller's own ADMIN threads. Private per admin (Open Question 2)."""
    return ConversationList(
        conversations=convo.list_summaries(repo, user.sub, ADMIN_SURFACE)
    )


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def get_admin_conversation(
    conversation_id: str,
    user: AuthenticatedUser = Depends(rate_limit_search),
    repo=Depends(get_repo),
) -> ConversationDetail:
    row = _owned_or_404(repo, user.sub, conversation_id)
    return convo.build_detail(repo, user.sub, row)


@router.patch("/conversations/{conversation_id}", response_model=ConversationSummary)
def rename_admin_conversation(
    conversation_id: str,
    body: ConversationRenameRequest,
    user: AuthenticatedUser = Depends(rate_limit_search),
    repo=Depends(get_repo),
) -> ConversationSummary:
    """Rename. Does not touch `updated_at` — a rename is not use."""
    row = _owned_or_404(repo, user.sub, conversation_id)
    return convo.rename(repo, row, body.title)


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_admin_conversation(
    conversation_id: str,
    user: AuthenticatedUser = Depends(rate_limit_search),
    repo=Depends(get_repo),
) -> Response:
    _owned_or_404(repo, user.sub, conversation_id)
    repo.delete_conversation(user.sub, conversation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/conversations", status_code=status.HTTP_204_NO_CONTENT)
def clear_admin_conversations(
    user: AuthenticatedUser = Depends(rate_limit_search),
    repo=Depends(get_repo),
) -> Response:
    """Clear the caller's ADMIN threads only — never their customer ones."""
    convo.clear_all(repo, user.sub, ADMIN_SURFACE)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
