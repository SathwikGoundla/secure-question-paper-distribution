"""
audit_events — LLD Section 7.6.

Operational copy of the audit trail (FR-013/FR-017). Hyperledger Fabric
holds the immutable counterpart (see services/blockchain_service.py,
CC-08 RecordAuditEvent). This table alone does NOT satisfy SEC-008
(immutable audit trail) — the Fabric write is required too; that
orchestration happens in AuditService, added in a later phase.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.common import uuid_pk


class AuditEvent(Base):
    __tablename__ = "audit_events"

    event_id: Mapped[uuid.UUID] = uuid_pk()
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=True
    )
    paper_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("papers.paper_id"), nullable=True
    )
    outcome: Mapped[str] = mapped_column(String(50), nullable=False)
    ledger_tx_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
