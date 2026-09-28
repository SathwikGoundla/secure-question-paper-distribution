"""
CentreService — Phase 6C. Real business logic behind LLD API-11
(create centre) and API-12 (update centre), plus list/get operations
the numbered LLD API table does not separately enumerate but which the
Admin Portal genuinely needs (PROJECT_STATE.md Phase 6B Section 17.20
documented this exact gap: "no list-centres endpoint at all").

RBAC itself is NOT decided here — it stays entirely in
app/api/deps.py/require_role, wired at the router layer
(app/api/v1/admin.py), matching every other service module in this
codebase (paper_service.py, auth_service.py). This module only ever
receives a CurrentUser that has ALREADY passed require_role("Admin").

Deletion is intentionally NOT implemented. Neither the approved LLD
nor SRS defines a delete-centre operation, and a hard delete would
either violate the real foreign-key relationships this table
participates in (users.centre_id, paper_authorizations.centre_id) or
silently orphan history if those constraints were relaxed. Retiring a
centre is done via update_centre(is_active=False), which the Admin
Portal can already express with the existing PATCH endpoint — no
schema change or new endpoint was needed for that.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser
from app.exceptions.base import ConflictException, NotFoundException, ValidationFailedException
from app.models.exam_centre import ExamCentre
from app.schemas.admin import CentreCreateRequest, CentreUpdateRequest
from app.services.audit_service import record_audit_event


def _duplicate_name_exists(
    db: Session, centre_name: str, exclude_centre_id: uuid.UUID | None = None
) -> bool:
    """
    Case-insensitive duplicate check. The exam_centres table (LLD 7.3)
    has no unique constraint on centre_name at the schema level — this
    is a Phase 6C service-level check (a genuine, testable "duplicate/
    conflict handling" behaviour) rather than a migration, since a DB
    constraint is not strictly required to satisfy the requested
    functionality and this project's rule is "only migrate if the
    schema genuinely lacks something the functionality needs."
    """
    query = db.query(ExamCentre).filter(func.lower(ExamCentre.centre_name) == centre_name.lower())
    if exclude_centre_id is not None:
        query = query.filter(ExamCentre.centre_id != exclude_centre_id)
    return db.query(query.exists()).scalar()


def list_centres(db: Session, page: int, page_size: int) -> tuple[list[ExamCentre], int]:
    """Stable ordering: created_at DESC, centre_id DESC as a tie-breaker."""
    total = db.query(func.count(ExamCentre.centre_id)).scalar() or 0
    items = (
        db.query(ExamCentre)
        .order_by(ExamCentre.created_at.desc(), ExamCentre.centre_id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return items, total


def get_centre_or_404(db: Session, centre_id: uuid.UUID) -> ExamCentre:
    centre = db.get(ExamCentre, centre_id)
    if centre is None:
        raise NotFoundException("The requested examination centre was not found.")
    return centre


def create_centre(db: Session, admin_user: CurrentUser, body: CentreCreateRequest) -> ExamCentre:
    """LLD API-11 (POST /admin/centres)."""
    if _duplicate_name_exists(db, body.centre_name):
        raise ConflictException("An examination centre with this name already exists.")

    centre = ExamCentre(centre_name=body.centre_name, created_by=admin_user.user_id)
    db.add(centre)
    db.commit()
    db.refresh(centre)

    record_audit_event(db, "EXAM_CENTRE_CREATED", actor_id=admin_user.user_id, outcome="SUCCESS")
    return centre


def update_centre(
    db: Session, admin_user: CurrentUser, centre_id: uuid.UUID, body: CentreUpdateRequest
) -> ExamCentre:
    """LLD API-12 (PATCH /admin/centres/{centre_id})."""
    if body.centre_name is None and body.is_active is None:
        raise ValidationFailedException(
            "At least one of centre_name or is_active must be provided."
        )

    centre = get_centre_or_404(db, centre_id)

    if body.centre_name is not None and _duplicate_name_exists(
        db, body.centre_name, exclude_centre_id=centre_id
    ):
        raise ConflictException("An examination centre with this name already exists.")

    if body.centre_name is not None:
        centre.centre_name = body.centre_name
    if body.is_active is not None:
        centre.is_active = body.is_active

    db.commit()
    db.refresh(centre)

    record_audit_event(db, "EXAM_CENTRE_UPDATED", actor_id=admin_user.user_id, outcome="SUCCESS")
    return centre
