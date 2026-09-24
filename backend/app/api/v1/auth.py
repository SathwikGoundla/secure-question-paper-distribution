"""
Authentication endpoints (SRS FR-001-FR-003; LLD API-01-API-03).

Phase 2 implementation — replaces the Phase 1 501 scaffold. Route
paths, methods, and request/response shapes follow LLD Section 6
exactly; no endpoint names were invented.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_current_user
from app.database import get_db
from app.schemas.auth import (
    CurrentUserResponse,
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    OtpVerifyRequest,
    OtpVerifyResponse,
)
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post("/login", response_model=LoginResponse, status_code=status.HTTP_200_OK)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    """
    LLD API-01. Validates username+password (FR-001). Raises 401 via
    UnauthorizedException (handled globally, app/exceptions/handlers.py)
    on invalid credentials.
    """
    return auth_service.login_step1(db, payload.username, payload.password)


@router.post("/otp/verify", response_model=OtpVerifyResponse, status_code=status.HTTP_200_OK)
def verify_otp(payload: OtpVerifyRequest, db: Session = Depends(get_db)) -> OtpVerifyResponse:
    """
    LLD API-02. Validates OTP (FR-002) and issues the session JWT (FR-003).
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
