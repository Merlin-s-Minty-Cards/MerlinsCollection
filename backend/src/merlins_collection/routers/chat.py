"""``/chat`` router — the AI chat mode of the inventory tool.

Thin HTTP layer over ``BedrockChatService``: authenticate the caller, run the
message through Bedrock, and translate the service's typed errors into HTTP
status codes. All real logic lives in the service.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from merlins_collection.dependencies import get_bedrock_service, get_current_user
from merlins_collection.models.auth import AuthenticatedUser
from merlins_collection.models.chat import ChatRequest, ChatResponse
from merlins_collection.services.bedrock import (
    BedrockChatService,
    BedrockContentFilteredError,
    BedrockLoopError,
    BedrockServiceError,
    BedrockThrottledError,
)

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/", response_model=ChatResponse)
def chat(
    request: ChatRequest,
    _user: AuthenticatedUser = Depends(get_current_user),
    service: BedrockChatService = Depends(get_bedrock_service),
) -> ChatResponse:
    """Answer a chat message about the inventory; requires a valid bearer token.

    Maps service failures to HTTP: throttling → 429, tool-loop limit → 503,
    content filtering → 422, any other Bedrock error → 502.
    """
    try:
        reply = service.chat(request.message, request.history)
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
    return ChatResponse(reply=reply)
