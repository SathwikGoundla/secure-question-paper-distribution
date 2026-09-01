"""
security_events — LLD Section 7.7.

Failed logins, invalid OTP, unauthorized access, pre-release attempts,
hash mismatches (FR-019, FR-020). Kept distinct from audit_events
(LLD design decision) so the monitoring dashboard can query
security-relevant events efficiently.

NOTE: this table is distinct from exam_security_events (LLD 7.10,
Faculty-Review Addition), which covers examination-time violations
(tab-switch, session termination) specifically — see
models/exam_security_event.py.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.common import uuid_pk


class SecurityEvent(Base):
    __tablename__ = "security_events"

    security_event_id: Mapped[uuid.UUID] = uuid_pk()
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=True
    )
    paper_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("papers.paper_id"), nullable=True
    )
    # Exact severity scheme NOT YET DETERMINED per LLD 7.7 — plain string for now.
    severity: Mapped[str] = mapped_column(String(50), nullable=False, default="MEDIUM")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
