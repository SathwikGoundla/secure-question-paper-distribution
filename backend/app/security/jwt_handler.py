"""
JWT issuance and validation (SRS FR-003, SEC-004; LLD Section 14.3-14.6).

The signing secret comes exclusively from configuration (JWT_SECRET_KEY,
app/config.py), which is read from the environment — it is never
hard-coded here or anywhere else in the codebase (SEC-010).

Full claim structure and refresh/revocation strategy are
NOT YET DETERMINED (LLD 14.5, 14.6, 26; SRS OQ). This module implements
the minimal claim set actually required so far: subject (user_id) and
role, plus standard exp/iat.

Phase 2 addition: two distinct token kinds share this module —
  - "access" tokens: the full session JWT, issued only after BOTH
    password AND OTP succeed (FR-003). Carries a "jti" (JWT ID) that
    is stored as auth_sessions.jwt_reference (LLD DD-06: an OPAQUE
    reference is stored, never the raw token) so a session can later
    be looked up/revoked without storing the bearer token itself.
  - "pre_auth" tokens: short-lived, issued after password success
    only (LLD API-01: "a short-lived pre-auth token"), before OTP is
    verified. Deliberately cannot be used to call protected endpoints
    (app/api/deps.py rejects any token whose purpose != "access").
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from app.config import get_settings

settings = get_settings()


def create_access_token(user_id: uuid.UUID, role_name: str, jti: str | None = None) -> tuple[str, str]:
    """
    Issue the full session JWT, only ever called after BOTH authentication
    factors (password + OTP) have succeeded, per FR-003.

    Returns (token, jti) — the caller persists jti as
    auth_sessions.jwt_reference (LLD 7.9, DD-06), never the raw token.
    """
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    token_id = jti or str(uuid.uuid4())

    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role_name,
        "purpose": "access",
        "jti": token_id,
        "iat": now,
        "exp": expires_at,
    }
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, token_id


def create_pre_auth_token(user_id: uuid.UUID) -> str:
    """
    Issue a short-lived pre-auth token after password verification
    succeeds (LLD API-01), before OTP has been checked. Intentionally
    carries no role claim and a distinct "purpose" so it can never be
    mistaken for — or misused as — a full session token.
    """
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=settings.PRE_AUTH_TOKEN_EXPIRE_MINUTES)

    payload: dict[str, Any] = {
        "sub": str(user_id),
        "purpose": "pre_auth",
        "iat": now,
        "exp": expires_at,
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """
    Validate signature and expiry, returning the decoded claims for
    ANY token kind issued above (access or pre_auth). Raises
    jwt.PyJWTError (or a subclass) on any failure — including
    tampering, since signature verification happens here.

    Callers MUST check claims["purpose"] themselves: a pre_auth token
    successfully decoding is not sufficient to authorize access to a
    protected endpoint (see app/api/deps.py).
    """
    return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
