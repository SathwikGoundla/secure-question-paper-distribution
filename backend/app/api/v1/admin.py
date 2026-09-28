"""
Admin endpoints (SRS FR-021, FR-023; LLD API-11-API-13, API-15).

Phase 2: RBAC protection wired on (require_role("Admin")) for centre
create/update and the dashboard summary, and require_role("Admin",
"Auditor") for the Faculty-Review exam-security-events endpoint.
Business logic itself was deferred (501 stubs).

Phase 6C: real business logic implemented for centre create/update
(LLD API-11/API-12), plus a list/get pair the numbered LLD API table
does not separately enumerate (see app/services/centre_service.py's
module docstring) and the dashboard summary (LLD API-13). RBAC is
UNCHANGED from Phase 2 — every one of these remains Admin-only, per
LLD Section 15's RBAC table (management operations are not delegated
to Auditor or Examination Centre). exam_security_events (the Faculty-
Review Addition, API-15) is untouched — out of Phase 6C's scope.
"""

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, require_role
from app.database import get_db
from app.schemas.admin import (
    CentreCreateRequest,
    CentreListResponse,
    CentreResponse,
    CentreUpdateRequest,
    DashboardSummaryResponse,
)
from app.services import centre_service, dashboard_service

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get(
    "/centres",
    response_model=CentreListResponse,
    dependencies=[Depends(require_role("Admin"))],
)
def list_centres(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> CentreListResponse:
    """
    Admin-only. Required for the Admin Portal's exam-centre management
    page and for the paper-authorization workflow (picking a real
    centre_id instead of requiring the operator to already know one —
    see PROJECT_STATE.md Phase 6B Section 17.20, item 5).
    """
    items, total = centre_service.list_centres(db, page=page, page_size=page_size)
    return CentreListResponse(
        items=[CentreResponse.model_validate(c) for c in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/centres/{centre_id}",
    response_model=CentreResponse,
    dependencies=[Depends(require_role("Admin"))],
)
def get_centre(centre_id: uuid.UUID, db: Session = Depends(get_db)) -> CentreResponse:
    """Admin-only. 404 if the centre_id does not exist."""
    centre = centre_service.get_centre_or_404(db, centre_id)
    return CentreResponse.model_validate(centre)


@router.post(
    "/centres",
    response_model=CentreResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_centre(
    body: CentreCreateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role("Admin")),
) -> CentreResponse:
    """LLD API-11. Admin-only. 409 if a centre with the same name (case-insensitively) already exists."""
    centre = centre_service.create_centre(db, current_user, body)
    return CentreResponse.model_validate(centre)


@router.patch(
    "/centres/{centre_id}",
    response_model=CentreResponse,
)
def update_centre(
    centre_id: uuid.UUID,
    body: CentreUpdateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role("Admin")),
) -> CentreResponse:
    """
    LLD API-12. Admin-only. Supports renaming and/or activating/
    deactivating a centre (partial update — both fields optional, but
    at least one is required). 404 if unknown, 409 on a name collision
    with a DIFFERENT existing centre.
    """
    centre = centre_service.update_centre(db, current_user, centre_id, body)
    return CentreResponse.model_validate(centre)


@router.get(
    "/dashboard/summary",
    response_model=DashboardSummaryResponse,
    dependencies=[Depends(require_role("Admin"))],
)
def dashboard_summary(db: Session = Depends(get_db)) -> DashboardSummaryResponse:
    """LLD API-13. Admin-only. Every field is a real, database-derived aggregate — see dashboard_service.py."""
    return dashboard_service.get_dashboard_summary(db)


@router.get(
    "/exam-security-events",
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    dependencies=[Depends(require_role("Admin", "Auditor"))],
)
def exam_security_events() -> dict:
    """LLD API-15 (Faculty-Review Addition). Out of Phase 6C's scope — untouched."""
    return {"detail": "Not implemented yet — planned for the examination-session-security implementation phase."}
