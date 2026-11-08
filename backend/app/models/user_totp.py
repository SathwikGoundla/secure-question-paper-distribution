"""
user_totp — Phase 7A. One row per user that has been issued an enrollment
code and/or enrolled a TOTP authenticator.

States (derived, not stored):
  * no row                                  -> not enrolled
  * code hash set, no secret                -> enrollment code issued, waiting
  * secret set, confirmed_at NULL           -> enrollment started, not yet confirmed (NOT usable for login)
  * secret set, confirmed_at set            -> ACTIVE (usable for login)

Security properties:
  * secret_encrypted holds the TOTP secret encrypted with AES-256-GCM under
    the dedicated TOTP_ENCRYPTION_KEY (never the paper master key). The
    plaintext secret is never stored, logged or returned after enrollment
    confirmation.
  * enrollment_code_hash is a SHA-256 of a high-entropy random one-time code;
    the code itself is shown once to the issuer and never stored.
  * last_used_step is the 30-second time step of the last ACCEPTED code
    (replay prevention: a code is accepted only for a strictly newer step).
  * code_issued_by records which Admin issued the code (NULL = server
    operator via the CLI). audit_events has no target-user column, so this
    is where the target of an issuance is recorded.

Created by Base.metadata.create_all (new table; no ALTER of existing tables).
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, LargeBinary, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class UserTotp(Base):
    __tablename__ = "user_totp"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id"), primary_key=True
    )
    # Versioned envelope: b"v1" + 12-byte nonce + ciphertext||tag (see app/security/totp.py).
    secret_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_step: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    enrollment_code_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    enrollment_code_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    enrollment_failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    code_issued_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=True
    )
    code_issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
