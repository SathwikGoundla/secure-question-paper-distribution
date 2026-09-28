"""
Audit and monitoring endpoints (SRS FR-017, FR-022, FR-019, FR-020;
LLD API-09, API-10).

Phase 2: RBAC protection wired on (Admin or Auditor, per LLD Section
15 — Examination Centre denied). Business logic deferred (501 stubs).

Phase 6C: real business logic, backed entirely by the existing
app.services.audit_service query functions (list_audit_events /
list_security_events) — no second/duplicate audit system was created.
RBAC is UNCHANGED from Phase 2.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.database import get_db
from app.schemas.audit import AuditEventResponse, AuditLogListResponse
from app.schemas.monitoring import SecurityEventListResponse, SecurityEventResponse
from app.services import audit_service

router = APIRouter(tags=["audit"])


@router.get(
    "/audit/logs",
    response_model=AuditLogListResponse,
    dependencies=[Depends(require_role("Admin", "Auditor"))],
)
def get_audit_logs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    paper_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    event_type: str | None = None,
    outcome: str | None = None,
    centre_id: uuid.UUID | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    db: Session = Depends(get_db),
) -> AuditLogListResponse:
    """
    LLD API-09. Admin or Auditor (read-only). All filters are optional
    and AND-combined; see app.services.audit_service.list_audit_events
    for exactly what each one matches (in particular, centre_id filters
    by the ACTOR's centre, since audit_events has no centre_id column
    of its own).
    """
    rows, total = audit_service.list_audit_events(
        db,
        page=page,
        page_size=page_size,
        paper_id=paper_id,
        actor_id=actor_id,
        event_type=event_type,
        outcome=outcome,
        centre_id=centre_id,
        start_date=start_date,
        end_date=end_date,
    )
    items = [
        AuditEventResponse(
            event_id=event.event_id,
            event_type=event.event_type,
            actor_id=event.actor_id,
            actor_username=username,
            paper_id=event.paper_id,
            outcome=event.outcome,
            ledger_tx_reference=event.ledger_tx_reference,
            created_at=event.created_at,
        )
        for event, username in rows
    ]
    return AuditLogListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get(
    "/monitoring/security-events",
    response_model=SecurityEventListResponse,
    dependencies=[Depends(require_role("Admin", "Auditor"))],
)
def get_security_events(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    severity: str | None = None,
    event_type: str | None = None,
    paper_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    centre_id: uuid.UUID | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    db: Session = Depends(get_db),
) -> SecurityEventListResponse:
    """LLD API-10. Admin or Auditor (read-only). Same filtering approach as get_audit_logs()."""
    rows, total = audit_service.list_security_events(
        db,
        page=page,
        page_size=page_size,
        severity=severity,
        event_type=event_type,
        paper_id=paper_id,
        actor_id=actor_id,
        centre_id=centre_id,
        start_date=start_date,
        end_date=end_date,
    )
    items = [
        SecurityEventResponse(
            security_event_id=event.security_event_id,
            event_type=event.event_type,
            actor_id=event.actor_id,
            actor_username=username,
            paper_id=event.paper_id,
            severity=event.severity,
            created_at=event.created_at,
        )
        for event, username in rows
    ]
    return SecurityEventListResponse(items=items, total=total, page=page, page_size=page_size)
