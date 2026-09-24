"""
exam_security_events — LLD Section 7.10 (Faculty-Review Addition, 23 Aug 2026).

Records examination-time browser-level violations (tab-switch,
visibility-change, unauthorized navigation), the termination action
taken, and the resulting security status (SRS FR-024–FR-028).

Kept distinct from security_events (Section 7.7) so the exam-security
dashboard (API-15, LLD Section 6) can query violations independently
without scanning the general security-event table — this is LLD design
decision DD-15.

Reminder (binding, from PRD Section 24.4 / HLD 7.9): this table records
BROWSER-LEVEL exam-tab events only. It never claims visibility into
other applications, other tabs, the OS, or any device outside the
examination browser context.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.common import uuid_pk


class ExamSecurityEvent(Base):
    __tablename__ = "exam_security_events"

    exam_event_id: Mapped[uuid.UUID] = uuid_pk()
    exam_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("auth_sessions.session_id"), nullable=False, index=True
    )
    paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("papers.paper_id"), nullable=False, index=True
    )
    centre_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exam_centres.centre_id"), nullable=False
    )
    # e.g. 'TAB_SWITCH', 'VISIBILITY_CHANGE', 'NAVIGATION_AWAY' (LLD 7.10)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # e.g. 'SESSION_TERMINATED' (LLD 7.10)
    action_taken: Mapped[str] = mapped_column(String(50), nullable=False)
    # e.g. 'VIOLATION_CONFIRMED' (LLD 7.10)
    security_status: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
