"""
Examination-session security endpoints (SRS FR-024-FR-028, Faculty-Review
Addition; LLD API-14, Section 17A).

Phase 2 change: RBAC protection wired on. Violation-handling business
logic (LLD Section 17A HandleExamViolation algorithm) is explicitly
Phase 3+/examination-session-security phase scope and still returns
501 here — only authentication + role checks are added in Phase 2.
"""

from fastapi import APIRouter, Depends, status

from app.api.deps import require_role

router = APIRouter(prefix="/exam-session", tags=["examination-session-security"])


@router.post(
    "/violation",
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    dependencies=[Depends(require_role("Examination Centre"))],
)
def report_exam_violation() -> dict:
    """
    LLD API-14. Only the Examination Centre running the active session
    may report a violation for it. Business logic implemented in the
    Examination-Session Security phase.
    """
    return {"detail": "Not implemented yet — planned for the examination-session-security implementation phase."}
