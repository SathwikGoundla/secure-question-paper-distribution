"""
Question-paper lifecycle endpoints (SRS FR-006-FR-016; LLD API-04-API-08).

Phase 3 change: register/retrieve/authorize/status are now implemented
via app.services.paper_service, replacing the Phase 2 RBAC-only 501
stubs. RBAC wiring itself (require_role calls) is UNCHANGED from Phase
2 — only the handler bodies were filled in.

Phase 4 change: time-lock enforcement (SRS FR-012/FR-016) is now
implemented inside paper_service.retrieve_paper() — see that
function's docstring for the exact check order and security reasoning.

Phase 5D change: PaperRegisterResponse.ledger_tx_reference is now
populated from the real Paper.ledger_tx_reference column (previously
always None — see paper_service.register_paper() for the best-effort
blockchain-registration logic that fills it in).
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, require_role
from app.database import get_db
from app.schemas.papers import (
    PaperAuthorizeRequest,
    PaperAuthorizeResponse,
    PaperListItemResponse,
    PaperListResponse,
    PaperMetadataResponse,
    PaperRegisterResponse,
    PaperRescheduleRequest,
    PaperScheduleResponse,
    PaperStatusResponse,
)
from app.services import paper_service

router = APIRouter(prefix="/papers", tags=["papers"])


@router.get("", response_model=PaperListResponse)
def list_papers(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role("Admin", "Examination Centre")),
) -> PaperListResponse:
    """
    Phase 6C addition — GET /papers. Not a separately numbered LLD API
    (LLD API-05/API-08 are single-paper lookups by ID), but required
    for the Admin Portal's Question Papers page to show a real
    catalogue instead of a session-local cache of manually looked-up
    IDs (see PROJECT_STATE.md Phase 6B Section 17.20, item 2). Scoping:
    Admin sees every paper; Examination Centre sees only papers it is
    currently authorized for (see paper_service.list_papers's
    docstring for the full reasoning).
    """
    items, total = paper_service.list_papers(
        db, current_user, page=page, page_size=page_size, status_filter=status_filter
    )
    return PaperListResponse(
        items=[PaperListItemResponse.model_validate(p) for p in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    response_model=PaperRegisterResponse,
)
def register_paper(
    subject: Annotated[str, Form(min_length=1, max_length=255)],
    release_timestamp: Annotated[datetime, Form()],
    file: Annotated[UploadFile, File()],
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role("Admin")),
) -> PaperRegisterResponse:
    """
    LLD API-04. Admin-only. Reads the uploaded PDF fully into memory
    (acceptable for a B.Tech-scope prototype given PAPER_MAX_UPLOAD_SIZE_BYTES,
    default 20 MB — streaming large-file upload is out of scope here),
    then delegates the full validate/hash/encrypt/store/persist/audit
    pipeline to paper_service.register_paper.
    """
    file_bytes = file.file.read()
    paper = paper_service.register_paper(
        db=db,
        admin_user=current_user,
        subject=subject,
        release_timestamp=release_timestamp,
        filename=file.filename,
        content_type=file.content_type,
        file_bytes=file_bytes,
    )
    return PaperRegisterResponse(
        paper_id=paper.paper_id,
        subject=paper.subject,
        status=paper.status,
        sha256_hash=paper.sha256_hash,
        encryption_algorithm=paper.encryption_algorithm,
        release_timestamp=paper.release_timestamp,
        created_at=paper.created_at,
        # Phase 5D: real value from the Paper row (None if the blockchain
        # write failed/was unreachable, or if BLOCKCHAIN_BACKEND is
        # misconfigured — never fabricated here or anywhere else).
        ledger_tx_reference=paper.ledger_tx_reference,
    )


@router.get(
    "/{paper_id}",
    response_model=PaperMetadataResponse,
)
def get_paper_metadata(
    paper_id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role("Admin", "Examination Centre")),
) -> PaperMetadataResponse:
    """LLD API-05. Admin (any paper) or Examination Centre (only if authorized for this paper)."""
    paper = paper_service.get_paper_metadata(db, current_user, paper_id)
    return PaperMetadataResponse(
        paper_id=paper.paper_id,
        subject=paper.subject,
        status=paper.status,
        sha256_hash=paper.sha256_hash,
        release_timestamp=paper.release_timestamp,
        created_at=paper.created_at,
    )


@router.post(
    "/{paper_id}/authorize",
    response_model=PaperAuthorizeResponse,
)
def authorize_centre(
    paper_id: UUID,
    body: PaperAuthorizeRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role("Admin")),
) -> PaperAuthorizeResponse:
    """LLD API-06. Admin-only."""
    authorization = paper_service.authorize_centre(db, current_user, paper_id, body.centre_id)
    return PaperAuthorizeResponse(
        authorization_id=authorization.authorization_id,
        paper_id=authorization.paper_id,
        centre_id=authorization.centre_id,
        authorized_at=authorization.authorized_at,
    )


@router.post(
    "/{paper_id}/revoke",
    response_model=PaperAuthorizeResponse,
)
def revoke_centre(
    paper_id: UUID,
    body: PaperAuthorizeRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role("Admin")),
) -> PaperAuthorizeResponse:
    """
    Phase 6F. Admin-only. Revokes a previously granted centre
    authorization for this paper — the PostgreSQL-side counterpart of
    LLD CC-03 (RevokeCentre; see paper_service.revoke_centre_authorization
    for why no blockchain call is attempted, exactly mirroring
    authorize_centre's existing, pre-Phase-6F treatment of its own
    unsupported chaincode counterpart, CC-02). Reuses the same request/
    response shapes as POST /{paper_id}/authorize — no new schema was
    needed for this endpoint.
    """
    authorization = paper_service.revoke_centre_authorization(db, current_user, paper_id, body.centre_id)
    return PaperAuthorizeResponse(
        authorization_id=authorization.authorization_id,
        paper_id=authorization.paper_id,
        centre_id=authorization.centre_id,
        authorized_at=authorization.authorized_at,
    )


@router.get("/{paper_id}/retrieve")
def retrieve_paper(
    paper_id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role("Examination Centre")),
) -> Response:
    """
    LLD API-07. Examination-Centre-only, and only if authorized for
    THIS paper_id (app/services/authorization_service). Performs
    time-lock enforcement, then decryption + integrity verification
    (see paper_service.retrieve_paper for the full check order and
    security reasoning) and returns the plaintext PDF directly.
    """
    plaintext = paper_service.retrieve_paper(db, current_user, paper_id)
    return Response(content=plaintext, media_type="application/pdf")


@router.get(
    "/{paper_id}/status",
    response_model=PaperStatusResponse,
)
def paper_status(
    paper_id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role("Admin", "Examination Centre")),
) -> PaperStatusResponse:
    """LLD API-08. Admin (any paper) or Examination Centre (own paper). No audit event (read-only)."""
    paper = paper_service.get_paper_metadata(db, current_user, paper_id)
    return PaperStatusResponse(
        paper_id=paper.paper_id,
        status=paper.status,
        release_timestamp=paper.release_timestamp,
        lock_status="released" if paper_service.is_released(paper.release_timestamp) else "locked",
    )


@router.patch(
    "/{paper_id}/schedule",
    response_model=PaperScheduleResponse,
)
def reschedule_paper_release(
    paper_id: UUID,
    body: PaperRescheduleRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role("Admin")),
) -> PaperScheduleResponse:
    """
    Phase 6G. Admin-only. Changes the release time of a paper that is
    STILL LOCKED. This only edits the stored release_timestamp; the
    existing server-side time-lock in paper_service.retrieve_paper
    remains the sole enforcement point (no second mechanism).
    """
    paper = paper_service.reschedule_paper_release(db, current_user, paper_id, body.release_timestamp)
    return PaperScheduleResponse(
        paper_id=paper.paper_id,
        release_timestamp=paper.release_timestamp,
        lock_status="released" if paper_service.is_released(paper.release_timestamp) else "locked",
    )
