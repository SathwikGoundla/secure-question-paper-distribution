"""
papers — LLD Section 7.4.

Application-level paper metadata plus the off-chain file reference.
The SHA-256 hash and release timestamp are ALSO recorded on Hyperledger
Fabric as the tamper-evident source of truth (HLD Section 8); this
table's copy exists purely for fast application queries — it is never
the authoritative value at retrieval time (LLD Section 13, 17).

No column here stores plaintext question-paper content (SEC-001).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.common import created_at_column, uuid_pk


class Paper(Base):
    __tablename__ = "papers"

    paper_id: Mapped[uuid.UUID] = uuid_pk()
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    file_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    sha256_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    release_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Exact value set NOT YET DETERMINED per LLD 7.4 — using a plain string
    # column (not a DB enum) so the allowed set can be finalised later
    # without a migration to change the column type.
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="registered")
    registered_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False
    )
    created_at = created_at_column()

    registrar: Mapped["User"] = relationship(foreign_keys=[registered_by])  # noqa: F821
