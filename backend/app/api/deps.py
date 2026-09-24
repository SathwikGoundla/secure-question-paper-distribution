"""
Shared FastAPI dependencies for authentication and RBAC
(LLD Section 5.4 Authorization/RBAC Module, Section 15 RBAC table).

get_current_user is the single trust boundary every protected endpoint
goes through: it verifies the JWT signature/expiry, rejects anything
that isn't a full "access" token, AND checks the session hasn't been
revoked (auth_sessions.revoked_at) — a valid, unexpired JWT signature
alone is NOT sufficient if the session was explicitly logged out
(defense in depth beyond what the JWT's own exp claim provides).
"""

import uuid
from dataclasses import dataclass

import jwt as pyjwt
from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.database import get_db
from app.exceptions.base import ForbiddenException, UnauthorizedException
from app.models.auth_session import AuthSession
from app.models.user import User
from app.security.jwt_handler import decode_access_token


@dataclass
class CurrentUser:
    """Minimal authenticated-identity context passed to route handlers."""
    user_id: uuid.UUID
    username: str
    role_name: str
    centre_id: uuid.UUID | None
    jti: str


def _extract_bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise UnauthorizedException("Missing or malformed Authorization header.")
    return authorization.split(" ", 1)[1].strip()


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> CurrentUser:
    """
    Validates the bearer JWT end-to-end:
      1. Present and well-formed Authorization header
      2. Valid signature and not expired (pyjwt.decode raises otherwise)
      3. purpose == "access" (a pre-auth token must never work here)
      4. Corresponding auth_sessions row exists and is not revoked
      5. The user still exists and is active

    Any failure -> UnauthorizedException (HTTP 401). Never leaks which
    specific check failed in the response body.
    """
    token = _extract_bearer_token(authorization)

    try:
        claims = decode_access_token(token)
    except pyjwt.PyJWTError:
        raise UnauthorizedException("Invalid or expired authentication token.")

    if claims.get("purpose") != "access":
        raise UnauthorizedException("Invalid or expired authentication token.")

    jti = claims.get("jti")
    session = (
        db.query(AuthSession)
        .filter(AuthSession.jwt_reference == jti, AuthSession.revoked_at.is_(None))
        .first()
    )
    if session is None:
        raise UnauthorizedException("Session has been revoked or does not exist.")

    user = db.get(User, uuid.UUID(claims["sub"]))
    if user is None or not user.is_active:
        raise UnauthorizedException("Invalid or expired authentication token.")

    return CurrentUser(
        user_id=user.user_id,
        username=user.username,
        role_name=user.role.role_name,
        centre_id=user.centre_id,
        jti=jti,
    )


def require_role(*allowed_roles: str):
    """
    RBAC dependency factory (LLD Section 15 RBAC table). Usage:

        @router.post(..., dependencies=[Depends(require_role("Admin"))])

    Roles are exactly the ones already defined in roles (LLD 7.2) /
    SRS Section 4 — Admin, Examination Centre, Auditor. No new roles
    are introduced here.
    """

    def _dependency(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if current_user.role_name not in allowed_roles:
            raise ForbiddenException("You do not have permission to perform this action.")
        return current_user

    return _dependency
