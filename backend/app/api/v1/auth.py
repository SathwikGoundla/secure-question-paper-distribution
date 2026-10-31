"""
Authentication endpoints (SRS FR-001-FR-003; LLD API-01-API-03).

Phase 2 implementation — replaces the Phase 1 501 scaffold. Route
paths, methods, and request/response shapes follow LLD Section 6
exactly; no endpoint names were invented.

Phase 6E-2 addition: POST /auth/login and POST /auth/otp/verify are
each guarded by a small in-process rate limiter
(app/security/rate_limiter.py), checked via a FastAPI dependency so it
runs BEFORE the route body — i.e. before login's password check and
before OTP's verify_otp_step2 (and therefore before that function can
touch the Phase 6E-1 failed_attempts counter at all). This ordering is
what guarantees a 429 never increments failed_attempts: the OTP
service function is simply never called on a rate-limited request.
"""

import hashlib
import logging
import uuid

import jwt as pyjwt

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_current_user
from app.config import get_settings
from app.database import get_db
from app.exceptions.base import TooManyRequestsException, UnauthorizedException
from app.schemas.auth import (
    TotpEnrollConfirmRequest,
    TotpEnrollConfirmResponse,
    TotpEnrollStartRequest,
    TotpEnrollStartResponse,
    CurrentUserResponse,
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    OtpVerifyRequest,
    OtpVerifyResponse,
)
from app.security.rate_limiter import FixedWindowRateLimiter
from app.security.jwt_handler import ENROLLMENT_TOKEN_EXPIRE_MINUTES, create_enrollment_token, decode_access_token
from app.services import auth_service, totp_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["authentication"])

_settings = get_settings()

# Module-level singletons (constructed once, at import time) — the
# same pattern app/services/auth_service.py already uses for its
# _otp_provider. Each call to get_settings() is cached (lru_cache), so
# these read the real configured values exactly once at startup;
# changing the env vars requires a process restart, same as every
# other Settings-derived value in this app.
_login_limiter = FixedWindowRateLimiter(
    limit=_settings.AUTH_LOGIN_RATE_LIMIT,
    window_seconds=_settings.AUTH_LOGIN_RATE_WINDOW_SECONDS,
)
_otp_limiter = FixedWindowRateLimiter(
    limit=_settings.AUTH_OTP_RATE_LIMIT,
    window_seconds=_settings.AUTH_OTP_RATE_WINDOW_SECONDS,
)
# Phase 7A: enrollment endpoints get their own budgets (same limits as login / OTP verify).
_enroll_start_limiter = FixedWindowRateLimiter(
    limit=_settings.AUTH_LOGIN_RATE_LIMIT,
    window_seconds=_settings.AUTH_LOGIN_RATE_WINDOW_SECONDS,
)
_enroll_confirm_limiter = FixedWindowRateLimiter(
    limit=_settings.AUTH_OTP_RATE_LIMIT,
    window_seconds=_settings.AUTH_OTP_RATE_WINDOW_SECONDS,
)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _otp_challenge_identity(pre_auth_token: str) -> str:
    """
    OTP rate-limit key component: a short, stable hash of the pre-auth
    token ITSELF — never the raw token (see module docstring: never
    log/expose it) and deliberately NOT the underlying user_id.

    Each POST /auth/login call mints a brand-new pre-auth token, so
    this gives each login's OTP challenge its OWN rate-limit budget,
    independent of any other challenge the same user requested earlier
    or later. Exhausting one challenge's REQUEST budget therefore never
    reduces the budget available to a legitimately fresh challenge from
    a subsequent login — matching the Phase 6E-1 "a new login creates a
    new usable challenge" semantics exactly, rather than silently
    tying a user's lifetime OTP-verify call count together across
    unrelated login attempts. A malformed/undecodable token still gets
    a perfectly valid, stable key here (this function never needs to
    decode or validate the token — that remains auth_service's job) —
    repeated submissions of the exact same garbage string are still
    throttled; different garbage strings simply get separate buckets.
    """
    return "tok:" + hashlib.sha256(pre_auth_token.encode("utf-8")).hexdigest()[:16]


def enforce_login_rate_limit(request: Request, payload: LoginRequest) -> None:
    """
    FastAPI dependency for POST /auth/login. Key = client IP +
    normalized (lowercased, trimmed) username — NOT username alone
    (an attacker could otherwise spray many different usernames from
    one IP, each starting a fresh per-username window) and NOT IP
    alone (which could over-penalize many legitimate users sharing one
    exam-centre/college NAT gateway). Runs before any DB lookup or
    password verification, so a 429 here carries zero information
    about whether the submitted username exists.
    """
    key = f"{_client_ip(request)}:{payload.username.strip().lower()}"
    if not _login_limiter.allow(key):
        retry_after = _login_limiter.retry_after_seconds(key)
        logger.warning("Login rate limit exceeded for client=%s", _client_ip(request))
        raise TooManyRequestsException(retry_after_seconds=retry_after)


def enforce_otp_rate_limit(request: Request, payload: OtpVerifyRequest) -> None:
    """
    FastAPI dependency for POST /auth/otp/verify. Key = client IP +
    the challenge identity derived above. Runs before
    auth_service.verify_otp_step2 is ever called, so a 429 here never
    reaches — and therefore never increments — the Phase 6E-1
    otp_codes.failed_attempts counter. The two protections are
    independent: this limiter bounds REQUEST VOLUME regardless of
    correctness; failed_attempts bounds WRONG GUESSES against one
    specific challenge. Hitting one does not consume or reset the
    other.
    """
    key = f"{_client_ip(request)}:{_otp_challenge_identity(payload.pre_auth_token)}"
    if not _otp_limiter.allow(key):
        retry_after = _otp_limiter.retry_after_seconds(key)
        logger.warning("OTP verification rate limit exceeded for client=%s", _client_ip(request))
        raise TooManyRequestsException(retry_after_seconds=retry_after)


@router.post(
    "/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    response_model_exclude_none=True,
    dependencies=[Depends(enforce_login_rate_limit)],
)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    """
    LLD API-01. Validates username+password (FR-001). Raises 401 via
    UnauthorizedException (handled globally, app/exceptions/handlers.py)
    on invalid credentials. Phase 6E-2: rate-limited per
    enforce_login_rate_limit above.
    """
    return auth_service.login_step1(db, payload.username, payload.password)


@router.post(
    "/otp/verify",
    response_model=OtpVerifyResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(enforce_otp_rate_limit)],
)
def verify_otp(payload: OtpVerifyRequest, db: Session = Depends(get_db)) -> OtpVerifyResponse:
    """
    LLD API-02. Validates OTP (FR-002) and issues the session JWT
    (FR-003). Phase 6E-1: bounded failed-attempt limiting inside
    auth_service.verify_otp_step2. Phase 6E-2: rate-limited per
    enforce_otp_rate_limit above — checked BEFORE this function is
    called, so a 429 never touches the Phase 6E-1 counter.
    """
    return auth_service.verify_otp_step2(db, payload.pre_auth_token, payload.otp_code)


@router.post("/logout", response_model=LogoutResponse, status_code=status.HTTP_200_OK)
def logout(
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LogoutResponse:
    """
    LLD API-03. Requires a valid JWT (enforced by get_current_user).
    Revokes the corresponding auth_sessions row.
    """
    auth_service.logout(db, current_user.jti, current_user.user_id)
    return LogoutResponse()


@router.get("/me", response_model=CurrentUserResponse, status_code=status.HTTP_200_OK)
def get_me(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUserResponse:
    """
    Not an LLD-numbered endpoint. A minimal identity-check endpoint so
    JWT validation + RBAC context can be demonstrated/tested end-to-end
    without depending on any Phase 3+ business endpoint. Returns only
    non-sensitive identity fields.
    """
    return CurrentUserResponse(
        user_id=str(current_user.user_id),
        username=current_user.username,
        role=current_user.role_name,
        centre_id=str(current_user.centre_id) if current_user.centre_id else None,
    )


def enforce_enroll_start_rate_limit(request: Request, payload: TotpEnrollStartRequest) -> None:
    """Phase 7A. Key = client IP + normalized username; runs before any DB lookup."""
    key = f"{_client_ip(request)}:{payload.username.strip().lower()}"
    if not _enroll_start_limiter.allow(key):
        raise TooManyRequestsException(retry_after_seconds=_enroll_start_limiter.retry_after_seconds(key))


def enforce_enroll_confirm_rate_limit(request: Request, payload: TotpEnrollConfirmRequest) -> None:
    """Phase 7A. Key = client IP + hash of the enrollment token (never the token itself)."""
    key = f"{_client_ip(request)}:{_otp_challenge_identity(payload.enrollment_token)}"
    if not _enroll_confirm_limiter.allow(key):
        raise TooManyRequestsException(retry_after_seconds=_enroll_confirm_limiter.retry_after_seconds(key))


@router.post(
    "/totp/enroll/start",
    response_model=TotpEnrollStartResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(enforce_enroll_start_rate_limit)],
    summary="Start authenticator enrollment (password + one-time enrollment code)",
    responses={
        401: {"description": "Invalid username, password or enrollment code (one generic message for every cause)."},
        429: {"description": "Rate limited."},
        503: {"description": "TOTP security configuration unavailable."},
    },
)
def totp_enroll_start(payload: TotpEnrollStartRequest, db: Session = Depends(get_db)) -> TotpEnrollStartResponse:
    """
    Phase 7A. Public (no JWT exists yet) but gated by password AND a one-time
    enrollment code issued by an Admin or the server operator. Returns the
    TOTP secret / QR exactly once; it is stored only encrypted and is never
    returned again. The authenticator is NOT active until
    /auth/totp/enroll/confirm succeeds.
    """
    started = totp_service.start_enrollment(db, payload.username, payload.password, payload.enrollment_code)
    return TotpEnrollStartResponse(
        enrollment_token=create_enrollment_token(started.user_id),
        provisioning_uri=started.provisioning_uri,
        secret=started.secret_b32,
        qr_svg_data_uri=started.qr_svg_data_uri,
        expires_in_seconds=ENROLLMENT_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post(
    "/totp/enroll/confirm",
    response_model=TotpEnrollConfirmResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(enforce_enroll_confirm_rate_limit)],
    summary="Confirm authenticator enrollment with a code from the app",
    responses={
        401: {"description": "Invalid/expired enrollment token or wrong code."},
        429: {"description": "Rate limited."},
    },
)
def totp_enroll_confirm(payload: TotpEnrollConfirmRequest, db: Session = Depends(get_db)) -> TotpEnrollConfirmResponse:
    """
    Phase 7A. Accepts ONLY an enrollment token (purpose "totp_enroll"); a
    session or pre-auth token is rejected. Activates the authenticator when
    the submitted code is valid. Issues NO session: the user then signs in
    normally (password, then a fresh authenticator code).
    """
    try:
        claims = decode_access_token(payload.enrollment_token)
    except pyjwt.PyJWTError:
        raise UnauthorizedException("Invalid or expired enrollment token.")
    if claims.get("purpose") != "totp_enroll":
        raise UnauthorizedException("Invalid or expired enrollment token.")
    totp_service.confirm_enrollment(db, uuid.UUID(claims["sub"]), payload.otp_code)
    return TotpEnrollConfirmResponse(enrolled=True)
