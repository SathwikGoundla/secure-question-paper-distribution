"""
RecoveryCodeService — Phase 7B. Backup/recovery codes as an alternative SECOND factor.

Policy (documented in PROJECT_STATE.md Section 28):
  * A recovery code is accepted only at the second-factor step, i.e. after the
    password was verified and a restricted pre-auth challenge exists. It never
    bypasses the password.
  * Each code works exactly once. Consumption is a conditional UPDATE
    (WHERE used_at IS NULL AND revoked_at IS NULL) preceded by a row lock, so
    concurrent requests with the same code produce at most one session.
  * Regenerating replaces the whole set: all unused codes of the previous set are
    revoked in the same transaction. Requires a normal MFA-issued session AND the
    current password (step-up); a pre-auth or enrollment token cannot call it.
  * An administrator-issued re-enrollment (lost device) also revokes every
    recovery code of that user, because the old set may be in the lost
    device's owner's hands.
  * A successful recovery-code sign-in revokes the user's OTHER active sessions
    and is recorded as a MEDIUM security event; it does not disable the
    authenticator (the user may simply have mislaid the phone) but the UI
    tells the user how many codes remain.

Plaintext codes are returned once from regenerate() and never stored, logged,
or placed in audit records.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import get_settings
from app.exceptions.base import ConflictException
from app.models.user import User
from app.models.user_recovery_code import UserRecoveryCode
from app.security import recovery_codes as rc
from app.services import totp_service
from app.services.audit_service import record_audit_event


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(ts: datetime | None) -> datetime | None:
    if ts is not None and ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


def unused_count(db: Session, user_id: uuid.UUID) -> int:
    return (
        db.query(func.count(UserRecoveryCode.code_id))
        .filter(
            UserRecoveryCode.user_id == user_id,
            UserRecoveryCode.used_at.is_(None),
            UserRecoveryCode.revoked_at.is_(None),
        )
        .scalar()
        or 0
    )


def status(db: Session, user_id: uuid.UUID) -> tuple[int, datetime | None]:
    """(unused codes, when the current set was generated). Never returns any code material."""
    latest = (
        db.query(UserRecoveryCode.created_at)
        .filter(UserRecoveryCode.user_id == user_id, UserRecoveryCode.revoked_at.is_(None))
        .order_by(UserRecoveryCode.created_at.desc())
        .first()
    )
    return unused_count(db, user_id), (_aware(latest[0]) if latest else None)


def revoke_all(db: Session, user_id: uuid.UUID, now: datetime | None = None) -> None:
    """Invalidate every unused code of a user. Does NOT commit (caller's transaction)."""
    when = now or _now()
    db.query(UserRecoveryCode).filter(
        UserRecoveryCode.user_id == user_id,
        UserRecoveryCode.used_at.is_(None),
        UserRecoveryCode.revoked_at.is_(None),
    ).update({UserRecoveryCode.revoked_at: when}, synchronize_session=False)


def regenerate(db: Session, user: User) -> list[str]:
    """
    Replace the user's recovery codes with a fresh set and return the plaintext
    codes (their only appearance anywhere). Requires an ACTIVE authenticator:
    recovery codes are only meaningful as a backup for it.
    """
    if totp_service.get_active(db, user.user_id) is None:
        raise ConflictException("Set up an authenticator before generating recovery codes.")
    count = get_settings().RECOVERY_CODE_COUNT

    # Serialize concurrent regenerations for the same user (PostgreSQL row lock on the user row).
    db.query(User).filter(User.user_id == user.user_id).with_for_update().one()
    now = _now()
    revoke_all(db, user.user_id, now)

    batch_id = uuid.uuid4()
    codes: list[str] = []
    seen: set[str] = set()
    while len(codes) < count:
        code = rc.generate_code()
        h = rc.hash_code(user.user_id, code)
        if h in seen:
            continue
        seen.add(h)
        codes.append(code)
        db.add(UserRecoveryCode(user_id=user.user_id, batch_id=batch_id, code_hash=h))
    db.commit()

    record_audit_event(db, "RECOVERY_CODES_GENERATED", actor_id=user.user_id, outcome="SUCCESS")
    return codes


def consume(db: Session, user_id: uuid.UUID, code: str) -> bool:
    """
    Atomically consume ONE valid recovery code for THIS user. Returns True iff a
    code was consumed. Does not commit: the caller commits it together with
    marking the login challenge used, so consumption and session issuance
    cannot diverge. A code of another user hashes differently (the user id is
    part of the hash), so cross-user use is impossible by construction.
    """
    if not rc.is_well_formed(code):
        return False
    h = rc.hash_code(user_id, code)
    row = (
        db.query(UserRecoveryCode)
        .filter(
            UserRecoveryCode.user_id == user_id,
            UserRecoveryCode.code_hash == h,
            UserRecoveryCode.used_at.is_(None),
            UserRecoveryCode.revoked_at.is_(None),
        )
        .with_for_update()
        .one_or_none()
    )
    if row is None:
        return False
    updated = (
        db.query(UserRecoveryCode)
        .filter(
            UserRecoveryCode.code_id == row.code_id,
            UserRecoveryCode.used_at.is_(None),
            UserRecoveryCode.revoked_at.is_(None),
        )
        .update({UserRecoveryCode.used_at: _now()}, synchronize_session=False)
    )
    db.flush()
    return updated == 1
