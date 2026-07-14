"""Unauthenticated liveness probe for Docker healthchecks and load balancers.

Deliberately does no I/O: a health check must not fail because DynamoDB is
slow, and must not incur an AWS call per poll.
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
