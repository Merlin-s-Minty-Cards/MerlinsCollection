from __future__ import annotations

from pydantic import BaseModel


class AuthenticatedUser(BaseModel):
    """Identity + role of the caller, derived from a verified Cognito token.

    A dumb DTO: ``is_admin`` is computed by the verifier (which knows the
    configured admin group), not by this model.
    """

    sub: str
    username: str | None = None
    email: str | None = None
    groups: list[str] = []
    is_admin: bool = False
