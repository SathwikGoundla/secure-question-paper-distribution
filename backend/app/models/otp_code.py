"""
otp_codes — LLD Section 7.8.

Short-lived OTP session records (FR-002). otp_hash is a HASHED value —
the raw OTP is never persisted. Delivery channel is
NOT YET DETERMINED (SRS OQ-4, LLD DD-12); this table is
delivery-channel-agnostic by design.

Phase 6E-1 addition — failed_attempts:
Closes the gap identified in the Phase 6E security audit: OTP
verification previously had no bound on how many times a given OTP
challenge could be guessed within its expiry window. This column
counts ONLY *failed* verification attempts against this specific
challenge (a successful verification never increments it — it sets
is_used=True instead, per the pre-existing single-use mechanism).
Once failed_attempts reaches settings.OTP_MAX_ATTEMPTS
(app/config.py), app/services/auth_service.verify_otp_step2() treats
the challenge as exhausted and rejects ANY further attempt against it
— including a subsequently-submitted CORRECT code — without
re-checking the OTP hash. See auth_service.py for the exact check
order, and scripts/add_phase6e1_columns.py for the additive schema
change on an already-existing otp_codes table.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.common import created_at_column, uuid_pk


class OtpCode(Base):
    __tablename__ = "otp_codes"

    otp_id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False, index=True
    )
    otp_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Phase 6E-1 (SRS FR-002 hardening). Count of FAILED verification
    # attempts against this exact challenge — never the raw OTP, never
    # a "total attempts" counter that would also count the eventual
    # successful one. Default 0; incremented atomically (see
    # auth_service.verify_otp_step2) so a challenge locks after
    # settings.OTP_MAX_ATTEMPTS consecutive/cumulative failures.
    failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at = created_at_column()
