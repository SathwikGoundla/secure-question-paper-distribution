"""
Audit and monitoring endpoints (SRS FR-017, FR-022; LLD API-09, API-10).

Phase 2 change: RBAC protection wired on (Admin or Auditor, per LLD
Section 15 — Examination Centre denied). Business logic still Phase 3+.
"""

from fastapi import APIRouter, Depends, status

from app.api.deps import require_role

router = APIRouter(tags=["audit"])


@router.get(
    "/audit/logs",
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    dependencies=[Depends(require_role("Admin", "Auditor"))],
)
def get_audit_logs() -> dict:
    """LLD API-09. Admin or Auditor (read-only). Implemented in a later Backend Development phase."""
    return {"detail": "Not implemented yet — planned for the audit/monitoring implementation phase."}


@router.get(
    "/monitoring/security-events",
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    dependencies=[Depends(require_role("Admin", "Auditor"))],
)
def get_security_events() -> dict:
    """LLD API-10. Admin or Auditor (read-only). Implemented in a later Backend Development phase."""
    return {"detail": "Not implemented yet — planned for the audit/monitoring implementation phase."}
