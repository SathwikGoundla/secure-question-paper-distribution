"""
AuthService — implements the authentication chain approved in SRS
FR-001–FR-003 and LLD Section 5.3, 14, API-01–API-03:

    username+password -> pre-auth token -> OTP verify -> session JWT

Audit logging: Phase 2 originally implemented this privately inside
this module (LLD Section 5.11 assigns a generic AuditService to a
later, cross-cutting phase covering ALL subsystems). Phase 3 needed the
same logic for the paper lifecycle, so it has been lifted out to
app/services/audit_service.py unchanged in behaviour — this module now
simply calls the shared functions instead of keeping private copies.
"""

import uuid
from datetime import datetime, timedelta, timezone

import jwt as pyjwt
from sqlalchemy.orm import Session

from app.config import get_settings
from app.exceptions.base import UnauthorizedException
from app.models.auth_session import AuthSession
from app.models.otp_code import OtpCode
from app.models.user import User
from app.schemas.auth import LoginResponse, OtpVerifyResponse
from app.security.jwt_handler import create_access_token, create_pre_auth_token, decode_access_token
from app.security.otp import DevConsoleOTPProvider, generate_otp, hash_otp, verify_otp
from app.security.password import verify_password
from app.services.audit_service import record_audit_event as _record_audit_event
from app.services.audit_service import record_security_event as _record_security_event

settings = get_settings()

# LLD DD-12 / SRS OQ-4: delivery channel NOT YET DETERMINED. DevConsoleOTPProvider
# is the Phase-1-defined dev-only stand-in; swapping in a real channel later only
# requires changing this one line.
_otp_provider = DevConsoleOTPProvider()


def login_step1(db: Session, username: str, password: str) -> LoginResponse:
    """
    LLD API-01 (POST /auth/login). Validates username+password (first
    factor, FR-001). On success, generates and "delivers" an OTP and
    issues a short-lived pre-auth token. On failure, logs a FAILED_LOGIN
    security event and raises UnauthorizedException (-> HTTP 401),
    WITHOUT revealing whether the username or the password was wrong
    (safe error messages, per Phase 2 security requirements).
    """
    user = db.query(User).filter(User.username == username, User.is_active == True).first()  # noqa: E712

    if user is None or not verify_password(password, user.password_hash):
        _record_security_event(db, "FAILED_LOGIN", actor_id=user.user_id if user else None)
        raise UnauthorizedException("Invalid username or password.")

    # FR-002: generate a cryptographically secure, single-use, expiring OTP.
    otp_value = generate_otp()
    otp_row = OtpCode(
        user_id=user.user_id,
        otp_hash=hash_otp(otp_value),  # raw OTP is NEVER persisted
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=settings.OTP_EXPIRE_SECONDS),
        is_used=False,
    )
    db.add(otp_row)
    db.commit()

    # Dev-only delivery (LLD DD-12 remains open) — never logs the OTP at
    # a level that would appear in a production-style log stream; the
    # provider itself is explicitly labelled dev-only (see security/otp.py).
    _otp_provider.deliver(user.username, otp_value)

    _record_audit_event(db, "LOGIN_STEP1_SUCCESS", actor_id=user.user_id, outcome="SUCCESS")

    pre_auth_token = create_pre_auth_token(user.user_id)
    return LoginResponse(otp_required=True, pre_auth_token=pre_auth_token)


def verify_otp_step2(db: Session, pre_auth_token: str, otp_code: str) -> OtpVerifyResponse:
    """
    LLD API-02 (POST /auth/otp/verify). Validates the OTP (second
    factor, FR-002) and, on success, issues the full session JWT
    (FR-003) and creates the auth_sessions row (LLD 7.9).
    """
    try:
        claims = decode_access_token(pre_auth_token)
    except pyjwt.PyJWTError:
        raise UnauthorizedException("Invalid or expired pre-authentication token.")

    if claims.get("purpose") != "pre_auth":
        # A full session JWT (or any other token) must never be usable here.
        raise UnauthorizedException("Invalid token type for OTP verification.")

    user_id = uuid.UUID(claims["sub"])
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise UnauthorizedException("Invalid or expired pre-authentication token.")

    otp_row = (
        db.query(OtpCode)
        .filter(OtpCode.user_id == user_id, OtpCode.is_used == False)  # noqa: E712
        .order_by(OtpCode.created_at.desc())
        .first()
    )

    now = datetime.now(timezone.utc)
    otp_valid = (
        otp_row is not None
        and otp_row.expires_at > now
        and verify_otp(otp_code, otp_row.otp_hash)
    )

    if not otp_valid:
        _record_security_event(db, "INVALID_OTP", actor_id=user_id)
        raise UnauthorizedException("Invalid or expired OTP.")

    # FR-002: single-use enforcement.
    otp_row.is_used = True
    db.commit()

    role_name = user.role.role_name
    token, jti = create_access_token(user_id, role_name)

    db.add(
        AuthSession(
            user_id=user_id,
            jwt_reference=jti,  # opaque reference (LLD DD-06) — never the raw token
            issued_at=now,
            expires_at=now + timedelta(minutes=settings.JWT_EXPIRE_MINUTES),
        )
    )
    db.commit()

    _record_audit_event(db, "AUTH_SUCCESS", actor_id=user_id, outcome="SUCCESS")

    return OtpVerifyResponse(access_token=token, role=role_name)


def logout(db: Session, jti: str, user_id: uuid.UUID) -> None:
    """
    LLD API-03 (POST /auth/logout). Revokes the session identified by
    the JWT's jti claim (LLD 7.9 revoked_at). Requires a valid,
    non-revoked session to already exist — an already-invalid token
    reaching this point (should not normally happen, since get_current_user
    rejects revoked sessions first) is treated as a 401.
    """
    session = (
        db.query(AuthSession)
        .filter(AuthSession.jwt_reference == jti, AuthSession.revoked_at.is_(None))
        .first()
    )
    if session is None:
        raise UnauthorizedException("Session already invalid or expired.")

    session.revoked_at = datetime.now(timezone.utc)
    db.commit()

    _record_audit_event(db, "LOGOUT", actor_id=user_id, outcome="SUCCESS")
