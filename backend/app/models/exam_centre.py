"""exam_centres — LLD Section 7.3. Managed exclusively by Admin (FR-018, FR-023)."""

import uuid

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.common import created_at_column, uuid_pk


class ExamCentre(Base):
    __tablename__ = "exam_centres"

    centre_id: Mapped[uuid.UUID] = uuid_pk()
    centre_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at = created_at_column()
    # use_alter/name required because users <-> exam_centres is a circular
    # FK relationship (users.centre_id -> exam_centres, exam_centres.created_by
    # -> users): this defers adding the constraint until both tables exist.
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", use_alter=True, name="fk_exam_centres_created_by"),
        nullable=False,
    )

    creator: Mapped["User"] = relationship(foreign_keys=[created_by])  # noqa: F821
