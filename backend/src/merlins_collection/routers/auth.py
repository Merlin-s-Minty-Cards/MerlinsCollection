from fastapi import APIRouter, Depends

from merlins_collection.dependencies import get_current_user
from merlins_collection.models.auth import AuthenticatedUser

# Cognito JWT validation and session endpoints — implemented via TDD
router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me", response_model=AuthenticatedUser)
def read_current_user(
    user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUser:
    """Return the identity and role of the authenticated caller."""
    return user
