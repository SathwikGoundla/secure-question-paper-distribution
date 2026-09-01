"""
Question-paper lifecycle endpoints (SRS FR-006-FR-016; LLD API-04-API-08).

Phase 2 change: RBAC protection wired on per LLD Section 15's RBAC
table. Business logic (PaperService, encryption, storage, retrieval
pipeline) is explicitly OUT OF SCOPE for Phase 2 and still returns 501
— only authentication + role checks are added here.
"""

from fastapi import APIRouter, Depends, status

from app.api.deps import require_role

router = APIRouter(prefix="/papers", tags=["papers"])


@router.post(
    "/register",
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    dependencies=[Depends(require_role("Admin"))],
)
def register_paper() -> dict:
    """LLD API-04. Admin-only. Implemented in a later Backend Development phase."""
    return {"detail": "Not implemented yet — planned for the paper-registration implementation phase."}


@router.get(
    "/{paper_id}",
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    dependencies=[Depends(require_role("Admin", "Examination Centre"))],
)
def get_paper_metadata(paper_id: str) -> dict:
    """LLD API-05. Admin (any paper) or Examination Centre (own paper — checked in Phase 3+)."""
    return {"detail": "Not implemented yet — planned for the paper-registration implementation phase."}


@router.post(
    "/{paper_id}/authorize",
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    dependencies=[Depends(require_role("Admin"))],
)
def authorize_centre(paper_id: str) -> dict:
    """LLD API-06. Admin-only. Implemented in a later Backend Development phase."""
    return {"detail": "Not implemented yet — planned for the paper-registration implementation phase."}


@router.get(
    "/{paper_id}/retrieve",
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    dependencies=[Depends(require_role("Examination Centre"))],
)
def retrieve_paper(paper_id: str) -> dict:
    """
    LLD API-07. Examination-Centre-only, and only if authorized for
    THIS paper_id — the per-paper check
    (app/services/authorization_service.is_centre_authorized_for_paper)
    is ready but not yet wired here, since the retrieval pipeline
    itself (time-lock, integrity, decryption) is Phase 3+ scope.
    """
    return {"detail": "Not implemented yet — planned for the paper-retrieval implementation phase."}


@router.get(
    "/{paper_id}/status",
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    dependencies=[Depends(require_role("Admin", "Examination Centre"))],
)
def paper_status(paper_id: str) -> dict:
    """LLD API-08. Admin (any paper) or Examination Centre (own paper)."""
    return {"detail": "Not implemented yet — planned for the paper-registration implementation phase."}
