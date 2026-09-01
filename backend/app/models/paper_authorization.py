"""paper_authorizations — LLD Section 7.5. Which centre may retrieve which paper (FR-004, FR-009)."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.common import uuid_pk


class PaperAuthorization(Base):
    __tablename__ = "paper_authorizations"
    __table_args__ = (
        # LLD 7.5: "Unique constraint recommended on (paper_id, centre_id)"
        UniqueConstraint("paper_id", "centre_id", name="uq_paper_authorizations_paper_centre"),
    )

    authorization_id: Mapped[uuid.UUID] = uuid_pk()
    paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("papers.paper_id"), nullable=False, index=True
    )
    centre_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exam_centres.centre_id"), nullable=False, index=True
    )
    authorized_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False
    )
    authorized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    paper: Mapped["Paper"] = relationship()  # noqa: F821
    centre: Mapped["ExamCentre"] = relationship()  # noqa: F821
