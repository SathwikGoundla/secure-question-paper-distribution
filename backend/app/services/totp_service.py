"""
TotpService — Phase 7A. Database-backed TOTP flows.

Why TOTP (and not SMTP email OTP): the existing challenge machinery
(OtpCode row: expiry, single use, per-challenge attempt limit; signed
pre-auth token) already supplies everything except "check the code", so TOTP
only replaces that one step; it needs no external service, no SMTP
credentials, no deliverability or cost, and works offline for exam centres.

Account lifecycle:
  1. An operator (server CLI) or another Admin issues a ONE-TIME ENROLLMENT
     CODE for a user (issue_enrollment_code). Issuing wipes any existing
     authenticator and revokes the user's sessions.
  2. The user opens the enrollment page and proves possession of
     password + enrollment code (start_enrollment). A fresh secret is
     generated, stored ENCRYPTED, and shown ONCE (QR + manual key).
  3. The user confirms with a valid code from the app (confirm_enrollment).
     Only then is the authenticator ACTIVE. The secret is never returned again.
  4. Login (auth_service) verifies codes with verify_login_code: +/- window,
     constant-time, replay-protected by last_used_step.

Why enrollment requires a code and not just the password: otherwise anyone
who steals a not-yet-enrolled user's password could enroll their own
authenticator and defeat the second factor. The first Admin is bootstrapped
by the server operator with the CLI (scripts/totp_enroll_code.py), which
requires access to the server/database — the trust root of the system.

Nothing here logs or returns a secret, an enrollment code or a TOTP code.
"""

from __future__ import annotations

import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from sqlalchemy.orm import Session

from app.api.deps import CurrentUser
from app.config import get_settings
from app.exceptions.base import (
    ForbiddenException,
    NotFoundException,
    ServiceUnavailableException,
    UnauthorizedException,
)
from app.models.auth_session import AuthSession
from app.models.user import User
from app.models.user_totp import UserTotp
from app.security import totp as totp_lib
from app.security.password import hash_password, verify_password
from app.services.audit_service import record_audit_event, record_security_event

logger = logging.getLogger(__name__)

_GENERIC_ENROLL_FAILURE = "Invalid username, password or enrollment code."
_GENERIC_CONFIRM_FAILURE = "Invalid or expired code. Please try again or ask your administrator for a new enrollment code."
_UNAVAILABLE = "Authenticator sign-in is temporarily unavailable. Please contact the administrator."

VerifyResult = Literal["ok", "invalid", "replay"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(ts: datetime | None) -> datetime | None:
    if ts is not None and ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


_DUMMY_HASH: str | None = None


def _dummy_hash() -> str:
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password(secrets.token_urlsafe(16))
    return _DUMMY_HASH


def require_configured() -> None:
    """Fail safely (generic 503, secret-free log line) if TOTP security configuration is unusable."""
    try:
        totp_lib.load_encryption_key()
    except totp_lib.TotpConfigError as exc:
        logger.error("TOTP is not usable: %s", exc)  # message names the setting, never a value
        raise ServiceUnavailableException(_UNAVAILABLE) from None


def get_active(db: Session, user_id: uuid.UUID) -> UserTotp | None:
    row = db.get(UserTotp, user_id)
    if row is None or row.confirmed_at is None or row.secret_encrypted is None:
        return None
    return row


# --------------------------------------------------------------------------- issuing codes


def issue_enrollment_code(db: Session, target: User, issued_by: uuid.UUID | None) -> tuple[str, datetime]:
    """
    Create (or replace) a one-time enrollment code for `target`.

    Side effects, deliberately strict because this is the account-recovery
    path: any existing authenticator is WIPED immediately (a lost device must
    stop working), the user's active sessions are revoked, and the attempt
    counter is reset. The plaintext code is returned exactly once.
    `issued_by` is the Admin's user id, or None for the server operator (CLI).
    """
    settings = get_settings()
    code = totp_lib.generate_enrollment_code()
    now = _now()
    expires_at = now + timedelta(hours=settings.TOTP_ENROLLMENT_CODE_TTL_HOURS)

    row = db.query(UserTotp).filter(UserTotp.user_id == target.user_id).with_for_update().one_or_none()
    if row is None:
        row = UserTotp(user_id=target.user_id)
        db.add(row)
    row.secret_encrypted = None
    row.confirmed_at = None
    row.last_used_step = None
    row.enrollment_code_hash = totp_lib.hash_enrollment_code(code)
    row.enrollment_code_expires_at = expires_at
    row.enrollment_failed_attempts = 0
    row.code_issued_by = issued_by
    row.code_issued_at = now

    for session in db.query(AuthSession).filter(AuthSession.user_id == target.user_id, AuthSession.revoked_at.is_(None)).all():
        session.revoked_at = now
    db.commit()

    record_audit_event(db, "TOTP_ENROLLMENT_CODE_ISSUED", actor_id=issued_by, outcome="SUCCESS")
    return code, expires_at


# --------------------------------------------------------------------------- enrollment


@dataclass
class EnrollmentStart:
    user_id: uuid.UUID
    secret_b32: str
    provisioning_uri: str
    qr_svg_data_uri: str


def _lock_enrollment(db: Session, row: UserTotp, user_id: uuid.UUID) -> None:
    """Too many wrong attempts: destroy the pending enrollment so a new code must be issued."""
    row.secret_encrypted = None
    row.enrollment_code_hash = None
    row.enrollment_code_expires_at = None
    db.commit()
    record_security_event(db, "TOTP_ENROLLMENT_LOCKED", actor_id=user_id, severity="HIGH")


def start_enrollment(db: Session, username: str, password: str, enrollment_code: str) -> EnrollmentStart:
    """All failure modes return the same generic 401; the true reason goes only to security events."""
    require_configured()
    settings = get_settings()

    user = db.query(User).filter(User.username == username, User.is_active == True).first()  # noqa: E712
    # Run a password check even for unknown users so timing does not reveal existence.
    password_ok = verify_password(password, user.password_hash if user else _dummy_hash())
    if user is None or not password_ok:
        record_security_event(db, "TOTP_ENROLLMENT_FAILED", actor_id=user.user_id if user else None)
        raise UnauthorizedException(_GENERIC_ENROLL_FAILURE)

    row = db.query(UserTotp).filter(UserTotp.user_id == user.user_id).with_for_update().one_or_none()
    now = _now()
    usable = (
        row is not None
        and row.enrollment_code_hash is not None
        and row.enrollment_code_expires_at is not None
        and _aware(row.enrollment_code_expires_at) > now
    )
    code_ok = usable and secrets.compare_digest(
        row.enrollment_code_hash, totp_lib.hash_enrollment_code(enrollment_code or "")
    )
    if not code_ok:
        if row is not None and row.enrollment_code_hash is not None:
            row.enrollment_failed_attempts += 1
            if row.enrollment_failed_attempts >= settings.TOTP_ENROLLMENT_MAX_ATTEMPTS:
                _lock_enrollment(db, row, user.user_id)
            else:
                db.commit()
        else:
            db.rollback()
        record_security_event(db, "TOTP_ENROLLMENT_FAILED", actor_id=user.user_id)
        raise UnauthorizedException(_GENERIC_ENROLL_FAILURE)

    secret = totp_lib.generate_secret()
    row.secret_encrypted = totp_lib.encrypt_secret(secret, user.user_id)
    row.confirmed_at = None
    row.last_used_step = None
    db.commit()

    uri = totp_lib.provisioning_uri(secret, user.username)
    record_audit_event(db, "TOTP_ENROLLMENT_STARTED", actor_id=user.user_id, outcome="SUCCESS")
    return EnrollmentStart(user.user_id, secret, uri, totp_lib.qr_svg_data_uri(uri))


def confirm_enrollment(db: Session, user_id: uuid.UUID, code: str) -> None:
    """Activate the authenticator only after a valid code proves the app holds the secret."""
    require_configured()
    settings = get_settings()
    row = db.query(UserTotp).filter(UserTotp.user_id == user_id).with_for_update().one_or_none()
    now = _now()
    pending = (
        row is not None
        and row.secret_encrypted is not None
        and row.confirmed_at is None
        and row.enrollment_code_hash is not None
        and row.enrollment_code_expires_at is not None
        and _aware(row.enrollment_code_expires_at) > now
    )
    if not pending:
        db.rollback()
        record_security_event(db, "TOTP_ENROLLMENT_FAILED", actor_id=user_id)
        raise UnauthorizedException(_GENERIC_CONFIRM_FAILURE)

    try:
        secret = totp_lib.decrypt_secret(row.secret_encrypted, user_id)
    except totp_lib.TotpDecryptError:
        logger.error("A pending TOTP secret could not be decrypted; enrollment refused.")
        db.rollback()
        raise ServiceUnavailableException(_UNAVAILABLE) from None

    matched = totp_lib.match_code(secret, code, settings.TOTP_VALID_WINDOW)
    if matched is None:
        row.enrollment_failed_attempts += 1
        if row.enrollment_failed_attempts >= settings.TOTP_ENROLLMENT_MAX_ATTEMPTS:
            _lock_enrollment(db, row, user_id)
        else:
            db.commit()
        record_security_event(db, "TOTP_ENROLLMENT_FAILED", actor_id=user_id)
        raise UnauthorizedException(_GENERIC_CONFIRM_FAILURE)

    row.confirmed_at = now
    row.last_used_step = matched  # the confirmation code cannot be replayed as a login code
    row.enrollment_code_hash = None
    row.enrollment_code_expires_at = None
    row.enrollment_failed_attempts = 0
    db.commit()
    record_audit_event(db, "TOTP_ENROLLED", actor_id=user_id, outcome="SUCCESS")


# --------------------------------------------------------------------------- login verification


def verify_login_code(db: Session, user_id: uuid.UUID, code: str) -> VerifyResult:
    """
    Check a login code for an ACTIVE authenticator.

    Runs inside the caller's transaction and does NOT commit: on "ok" it
    records last_used_step on the (row-locked) UserTotp row, and the caller
    commits that together with marking the challenge used, so acceptance and
    replay-protection are atomic. "replay" means the code is valid but its
    time step is not newer than the last accepted one.
    """
    row = db.query(UserTotp).filter(UserTotp.user_id == user_id).with_for_update().one_or_none()
    if row is None or row.confirmed_at is None or row.secret_encrypted is None:
        return "invalid"
    try:
        secret = totp_lib.decrypt_secret(row.secret_encrypted, user_id)
    except (totp_lib.TotpDecryptError, totp_lib.TotpConfigError):
        logger.error("A stored TOTP secret could not be decrypted; code rejected.")
        return "invalid"

    matched = totp_lib.match_code(secret, code, get_settings().TOTP_VALID_WINDOW)
    if matched is None:
        return "invalid"
    if row.last_used_step is not None and matched <= row.last_used_step:
        return "replay"
    row.last_used_step = matched
    db.flush()
    return "ok"


def admin_issue_enrollment_code(db: Session, admin: CurrentUser, username: str) -> tuple[User, str, datetime]:
    """
    Admin-assisted (re-)enrollment for ANOTHER user, e.g. after a lost phone.
    An Admin may not reset their OWN authenticator through the API: a hijacked
    admin session must not be able to enroll the attacker's device. Admins
    recover their own access through the server operator CLI
    (scripts/totp_enroll_code.py), which requires server access.
    """
    target = db.query(User).filter(User.username == username, User.is_active == True).first()  # noqa: E712
    if target is None:
        raise NotFoundException("The requested resource was not found.")
    if target.user_id == admin.user_id:
        raise ForbiddenException("You cannot reset your own authenticator here. Ask the server operator.")
    code, expires_at = issue_enrollment_code(db, target, issued_by=admin.user_id)
    return target, code, expires_at
