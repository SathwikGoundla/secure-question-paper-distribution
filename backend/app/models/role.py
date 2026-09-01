"""roles — LLD Section 7.2. Fixed RBAC role set: Admin, Examination Centre, Auditor."""

import uuid

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.common import uuid_pk


class Role(Base):
    __tablename__ = "roles"

    role_id: Mapped[uuid.UUID] = uuid_pk()
    role_name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)

    users: Mapped[list["User"]] = relationship(back_populates="role")  # noqa: F821
