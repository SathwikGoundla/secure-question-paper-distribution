"""
paper_schedule_history — Phase 6H.

One row per SUCCESSFUL, EFFECTIVE change of a paper's release time
(PATCH /papers/{paper_id}/schedule). Why a dedicated table rather than
reusing audit_events: audit_events (LLD 7.6) deliberately has no
details/metadata column, so it cannot hold the previous and new release
timestamps. Adding a free-form JSON column to audit_events would alter a
table that already holds production rows and is mirrored to the
blockchain backend; a small purpose-built table is the smaller change and
creates cleanly through Base.metadata.create_all (no ALTER needed).

The existing "PAPER_RELEASE_RESCHEDULED" audit event is still written
(it is what feeds the audit log / ledger forwarding); this table adds
only the old/new values. The two are not competing mechanisms: the audit
event says "something happened", this table says exactly what changed.

Rows are written in the SAME database transaction as the
papers.release_timestamp update, so they can never disagree.

Foreign keys use the database default (NO ACTION): a paper or user that
has schedule history cannot be deleted out from under it, so history is
never silently removed. No code path deletes papers today.

Never stores secrets, tokens, OTPs, keys, or paper content.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.common import uuid_pk


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PaperScheduleHistory(Base):
    __tablename__ = "paper_schedule_history"
    __table_args__ = (Index("ix_paper_schedule_history_paper_created", "paper_id", "created_at"),)

    history_id: Mapped[uuid.UUID] = uuid_pk()
    paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("papers.paper_id"), nullable=False
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False
    )
    # Only value written today. A String (not a DB enum), matching papers.status
    # and audit_events.event_type, so future actions need no migration.
    action: Mapped[str] = mapped_column(String(50), nullable=False, default="RESCHEDULED")
    previous_release_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    new_release_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Assigned by the backend in UTC with microsecond precision (not only
    # server_default) so ordering is deterministic even on SQLite, whose
    # CURRENT_TIMESTAMP has one-second resolution. server_default remains
    # as a safety net for any row inserted without it.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, server_default=func.now(), nullable=False
    )
