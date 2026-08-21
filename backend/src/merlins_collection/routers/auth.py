"""``/auth`` router — identity endpoints backed by Cognito JWT verification.

Token validation itself lives in ``services/cognito.py`` and is applied via the
``get_current_user`` dependency; these routes just expose the verified identity.
"""

from fastapi import APIRouter, Depends

from merlins_collection.models.auth import AuthenticatedUser
from merlins_collection.rate_limit import rate_limit_auth

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me", response_model=AuthenticatedUser)
def read_current_user(
    user: AuthenticatedUser = Depends(rate_limit_auth),
) -> AuthenticatedUser:
    """Return the identity and role of the authenticated caller."""
    return user
