"""
auth_sessions — LLD Section 7.9.

Operational bookkeeping for issued JWT sessions (logout/revocation,
API-03). jwt_reference is an OPAQUE reference to the token, not the raw
JWT itself (LLD design decision DD-06) — avoids storing bearer tokens
verbatim in the database.

This table is also the FK target for exam_security_events.exam_session_id
(LLD 7.10, Faculty-Review Addition) — an examination session IS an
auth_session for an Examination-Centre-role user.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.common import uuid_pk


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    session_id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False, index=True
    )
    jwt_reference: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
