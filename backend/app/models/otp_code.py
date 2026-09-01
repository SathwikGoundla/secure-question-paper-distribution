"""
otp_codes — LLD Section 7.8.

Short-lived OTP session records (FR-002). otp_hash is a HASHED value —
the raw OTP is never persisted. Delivery channel is
NOT YET DETERMINED (SRS OQ-4, LLD DD-12); this table is
delivery-channel-agnostic by design.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String
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
    created_at = created_at_column()
