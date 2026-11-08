"""
user_recovery_codes — Phase 7B. One row per backup/recovery code.

Recovery codes are an ALTERNATIVE SECOND FACTOR (used instead of an
authenticator-app code, after the password has been verified). They never
replace the password.

  * Only a SHA-256 of (user id, code) is stored (see app/security/recovery_codes.py
    for why that is appropriate for a high-entropy random code). The code itself
    exists in clear only in the one HTTP response that creates it.
  * used_at is set exactly once, by a conditional UPDATE (WHERE used_at IS NULL),
    so a code can create at most one session even under concurrent requests.
  * revoked_at marks codes invalidated by regeneration or by an administrator
    re-enrollment; revoked codes can never be used.
  * batch_id groups the codes generated together (the "current set").

Created by Base.metadata.create_all (new table; no ALTER of existing tables).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.common import uuid_pk


class UserRecoveryCode(Base):
    __tablename__ = "user_recovery_codes"
    __table_args__ = (
        UniqueConstraint("user_id", "code_hash", name="uq_user_recovery_codes_user_hash"),
        Index("ix_user_recovery_codes_user_state", "user_id", "used_at", "revoked_at"),
    )

    code_id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False)
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
