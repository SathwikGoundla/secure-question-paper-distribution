"""
users — LLD Section 7.1.

Stores authentication-relevant account records for Admin and Examination
Centre actors. password_hash is a salted hash ONLY (SEC-010) — never
plaintext, and never returned by any API response (enforced in the
schemas layer in a later phase, not here).
"""

import uuid

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.common import created_at_column, uuid_pk


class User(Base):
    __tablename__ = "users"

    user_id: Mapped[uuid.UUID] = uuid_pk()
    username: Mapped[str] = mapped_column(String(150), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.role_id"), nullable=False, index=True
    )
    # Nullable: only set for Examination-Centre-type users (LLD 7.1).
    centre_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exam_centres.centre_id"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at = created_at_column()

    role: Mapped["Role"] = relationship(back_populates="users")  # noqa: F821
    centre: Mapped["ExamCentre | None"] = relationship(foreign_keys=[centre_id])  # noqa: F821
