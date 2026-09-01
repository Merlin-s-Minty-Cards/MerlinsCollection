"""``/chat`` router — the AI chat mode of the inventory tool.

Thin HTTP layer over ``BedrockChatService``: authenticate the caller, run the
message through Bedrock, and translate the service's typed errors into HTTP
status codes. All real logic lives in the service.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status

from merlins_collection.dependencies import get_bedrock_service, get_repo
from merlins_collection.models.auth import AuthenticatedUser
from merlins_collection.models.chat import (
    CUSTOMER_SURFACE,
    ChatRequest,
    ChatResponse,
    ConversationDetail,
    ConversationList,
    ConversationRenameRequest,
    ConversationSummary,
)
from merlins_collection.rate_limit import rate_limit_chat, rate_limit_search
from merlins_collection.services import conversations as convo
from merlins_collection.services.bedrock import (
    BedrockChatService,
    BedrockContentFilteredError,
    BedrockLoopError,
    BedrockServiceError,
    BedrockThrottledError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


# The cost-critical route. `rate_limit_chat` is a dependency, so it (and its
# three tiers — per-user minute, per-user day, global account-wide day) runs
# BEFORE the endpoint body: an over-limit request 429s without ever calling
# Bedrock, and if the DynamoDB limiter can't verify usage it fails CLOSED (503)
# rather than proceeding to Bedrock uncapped. It also enforces auth (401 first)
# and reads settings live so the master switch works without a rebuild.
@router.post("/", response_model=ChatResponse)
def chat(
    body: ChatRequest,
    user: AuthenticatedUser = Depends(rate_limit_chat),
    service: BedrockChatService = Depends(get_bedrock_service),
    repo=Depends(get_repo),
) -> ChatResponse:
    """Answer a chat message about the inventory; requires a valid bearer token.

    RFC 0017: the transcript is server-owned. ``body.history`` is accepted and
    IGNORED — the replay window is loaded from storage, which is what stops a
    client forging assistant turns. Omitting ``conversation_id`` starts a
    thread implicitly.

    Maps service failures to HTTP: throttling → 429, tool-loop limit → 503,
    content filtering → 422, any other Bedrock error → 502.
    """
    if body.conversation_id:
        # get_owned, not repo.get_conversation: the lookup is scoped to THIS
        # surface, so an admin analyst thread's id handed to the customer chat
        # is a 404 rather than a thread that quietly gains a customer turn.
        row = convo.get_owned(repo, user.sub, body.conversation_id, CUSTOMER_SURFACE)
        if row is None:
            # 404, never 403: a 403 would confirm the id exists.
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found."
            )
        history = convo.replay_turns(
            repo.get_conversation_messages(
                row["conv_id"], limit=convo.MAX_REPLAY_TURNS * 2
            )
        )
    else:
        row = convo.start_conversation(repo, user.sub, body.message, CUSTOMER_SURFACE)
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

    # Written only after Bedrock has answered, so a model failure leaves no
    # half-thread behind — no thread holding a question with no answer, and no
    # conversation created for a request that produced nothing.
    #
    # PERSISTENCE FAILURE MUST NOT SWALLOW THE REPLY. Bedrock has already been
    # called and already been paid for by this point; turning a DynamoDB blip
    # into a 500 would bill the owner for an answer the customer never sees.
    # The thread simply does not gain this exchange, and that is logged loudly
    # rather than hidden.
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
            "failed to persist chat exchange for conversation %s; reply still served",
            row.get("conv_id"),
        )

    response.conversation_id = row["conv_id"]
    response.title = row["title"]
    return response


# ---- conversation history (RFC 0017) ----
#
# These five routes carry `rate_limit_search`, NOT `rate_limit_chat`, and the
# difference is load-bearing: `rate_limit_chat` fails CLOSED (503) because
# Bedrock costs money per call, while `rate_limit_search` fails OPEN. Putting
# history behind the chat limiter would let LISTING conversations consume the
# daily budget for ASKING questions, and would lock a customer out of reading
# their own transcripts during a DynamoDB blip — a read that costs nothing
# failing because a write that costs money could not be metered.
#
# There is deliberately no admin equivalent of any of these. A conversation is
# customer-private (decision 11); see test_conversations.py's permanent
# tripwire asserting no admin router exposes one.


def _owned_or_404(repo, sub: str, conversation_id: str) -> dict:
    """The caller's own CUSTOMER thread, or a 404.

    Wrong-surface is deliberately indistinguishable from not-found: an admin
    thread's id must not be confirmable through the customer routes.
    """
    row = convo.get_owned(repo, sub, conversation_id, CUSTOMER_SURFACE)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found."
        )
    return row


@router.get("/conversations", response_model=ConversationList)
def list_conversations(
    user: AuthenticatedUser = Depends(rate_limit_search),
    repo=Depends(get_repo),
) -> ConversationList:
    """The caller's own threads, at most 50, most recently used first."""
    return ConversationList(
        conversations=convo.list_summaries(repo, user.sub, CUSTOMER_SURFACE)
    )


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    conversation_id: str,
    user: AuthenticatedUser = Depends(rate_limit_search),
    repo=Depends(get_repo),
) -> ConversationDetail:
    """One thread's transcript, with every card re-hydrated live."""
    row = _owned_or_404(repo, user.sub, conversation_id)
    return convo.build_detail(repo, user.sub, row)


@router.patch("/conversations/{conversation_id}", response_model=ConversationSummary)
def rename_conversation(
    conversation_id: str,
    body: ConversationRenameRequest,
    user: AuthenticatedUser = Depends(rate_limit_search),
    repo=Depends(get_repo),
) -> ConversationSummary:
    """Rename a thread. Does not touch `updated_at` — a rename is not use."""
    row = _owned_or_404(repo, user.sub, conversation_id)
    return convo.rename(repo, row, body.title)


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(
    conversation_id: str,
    user: AuthenticatedUser = Depends(rate_limit_search),
    repo=Depends(get_repo),
) -> Response:
    """Hard delete (decision 10) — index row first, then the message sweep."""
    _owned_or_404(repo, user.sub, conversation_id)
    repo.delete_conversation(user.sub, conversation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/conversations", status_code=status.HTTP_204_NO_CONTENT)
def clear_conversations(
    user: AuthenticatedUser = Depends(rate_limit_search),
    repo=Depends(get_repo),
) -> Response:
    """Delete every thread the caller owns. Irreversible; the UI confirms."""
    convo.clear_all(repo, user.sub, CUSTOMER_SURFACE)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
