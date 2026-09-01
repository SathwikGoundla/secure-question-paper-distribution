"""
Admin endpoints (SRS FR-021, FR-023; LLD API-11-API-13, API-15).

Phase 2 change: RBAC protection (require_role("Admin")) is now wired on
per LLD Section 15's RBAC table (all four of these operations are
Admin-only, Auditor/Examination-Centre denied). The underlying business
logic (centre management, dashboard aggregation) is still NOT
implemented — these intentionally still return 501, but ONLY after
authentication + role checks pass. This lets Phase 2's RBAC tests
exercise real protected endpoints without pulling in Phase 3+ work.
"""

from fastapi import APIRouter, Depends, status

from app.api.deps import require_role

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post(
    "/centres",
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    dependencies=[Depends(require_role("Admin"))],
)
def create_centre() -> dict:
    """LLD API-11. Admin-only (LLD Section 15). Business logic implemented in a later phase."""
    return {"detail": "Not implemented yet — planned for the admin-management implementation phase."}


@router.patch(
    "/centres/{centre_id}",
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    dependencies=[Depends(require_role("Admin"))],
)
def update_centre(centre_id: str) -> dict:
    """LLD API-12. Admin-only. Business logic implemented in a later phase."""
    return {"detail": "Not implemented yet — planned for the admin-management implementation phase."}


@router.get(
    "/dashboard/summary",
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    dependencies=[Depends(require_role("Admin"))],
)
def dashboard_summary() -> dict:
    """LLD API-13. Admin-only. Business logic implemented in a later phase."""
    return {"detail": "Not implemented yet — planned for the monitoring/dashboard implementation phase."}


@router.get(
    "/exam-security-events",
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    dependencies=[Depends(require_role("Admin", "Auditor"))],
)
def exam_security_events() -> dict:
    """LLD API-15 (Faculty-Review Addition). Admin or Auditor (read-only), per LLD Section 15."""
    return {"detail": "Not implemented yet — planned for the examination-session-security implementation phase."}
