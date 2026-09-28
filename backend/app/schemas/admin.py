"""
Request/response schemas for admin exam-centre management (LLD API-11,
API-12; a list/get pair the numbered LLD API table does not separately
enumerate but which is required for the Admin Portal to function — see
PROJECT_STATE.md Phase 6C section) and the dashboard summary (LLD
API-13).

Response models mirror the existing narrow-response convention already
established in schemas/auth.py and schemas/papers.py: no secrets, no
internal-only fields, only what a legitimate API client needs.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CentreCreateRequest(BaseModel):
    """LLD API-11 request body."""

    centre_name: str = Field(min_length=1, max_length=255)

    @field_validator("centre_name")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("centre_name must not be blank.")
        return value


class CentreUpdateRequest(BaseModel):
    """
    LLD API-12 request body. Both fields optional, but at least one
    must be supplied (enforced in app.services.centre_service, not
    here, so the exact error message stays consistent with the rest of
    the service layer's validation).
    """

    centre_name: str | None = Field(default=None, min_length=1, max_length=255)
    is_active: bool | None = None

    @field_validator("centre_name")
    @classmethod
    def _not_blank_if_present(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("centre_name must not be blank.")
        return value


class CentreResponse(BaseModel):
    """Common response shape for create/get/update/list-item (LLD 7.3)."""

    model_config = ConfigDict(from_attributes=True)

    centre_id: uuid.UUID
    centre_name: str
    is_active: bool
    created_at: datetime


class CentreListResponse(BaseModel):
    items: list[CentreResponse]
    total: int
    page: int
    page_size: int


class DashboardSummaryResponse(BaseModel):
    """
    LLD API-13 response. Every field is a real, database-derived
    aggregate (app.services.dashboard_service) — never a hard-coded,
    random, or fabricated value.
    """

    total_papers: int
    papers_by_status: dict[str, int]
    total_exam_centres: int
    active_exam_centres: int
    total_paper_authorizations: int
    total_audit_events: int
    total_security_events: int
    security_events_by_severity: dict[str, int]
