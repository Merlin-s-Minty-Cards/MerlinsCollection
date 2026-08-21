"""``/chat`` router — the AI chat mode of the inventory tool.

Thin HTTP layer over ``BedrockChatService``: authenticate the caller, run the
message through Bedrock, and translate the service's typed errors into HTTP
status codes. All real logic lives in the service.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from merlins_collection.dependencies import get_bedrock_service
from merlins_collection.models.auth import AuthenticatedUser
from merlins_collection.models.chat import ChatRequest, ChatResponse
from merlins_collection.rate_limit import rate_limit_chat
from merlins_collection.services.bedrock import (
    BedrockChatService,
    BedrockContentFilteredError,
    BedrockLoopError,
    BedrockServiceError,
    BedrockThrottledError,
)

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
    _user: AuthenticatedUser = Depends(rate_limit_chat),
    service: BedrockChatService = Depends(get_bedrock_service),
) -> ChatResponse:
    """Answer a chat message about the inventory; requires a valid bearer token.

    Maps service failures to HTTP: throttling → 429, tool-loop limit → 503,
    content filtering → 422, any other Bedrock error → 502.
    """
    try:
        result = service.chat(body.message, body.history, body.panel_item_ids)
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
    # Keep dependency-override stubs and older service implementations compatible
    # while the real service returns the extended response envelope.
    if isinstance(result, str):
        return ChatResponse(reply=result)
    return ChatResponse.model_validate(result)
