"""
Shared helpers for ORM models.

Every table in LLD Section 7 uses a UUID (or BIGSERIAL) primary key.
This project standardises on UUID primary keys generated in Python
(uuid4) for all tables, which is a Phase-1 implementation decision
consistent with, but not dictated by, the LLD ("UUID / BIGSERIAL").
"""

import uuid

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def created_at_column() -> Mapped:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
