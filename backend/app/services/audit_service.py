"""
AuditService — LLD Section 5.11, 19 (generic, cross-cutting audit
logging), CC-08 RecordAuditEvent.

Phase 2 built this logic privately inside auth_service.py because, at
that point, only the authentication flow needed it (see auth_service.py
module docstring, which explicitly called this out as a scoping
decision to be lifted out later). Phase 3 is that "later": the paper
lifecycle now also needs audit/security events, so this logic is
pulled out into one shared module rather than duplicated.

auth_service.py is updated to call these same functions (via a
paper_id=None default) instead of keeping its own private copies —
behaviour for authentication events is unchanged.
"""

import logging
import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.audit_event import AuditEvent
from app.models.security_event import SecurityEvent
from app.models.user import User
from app.services.blockchain_service import get_blockchain_service

logger = logging.getLogger(__name__)


def record_security_event(
    db: Session,
    event_type: str,
    actor_id: uuid.UUID | None,
    paper_id: uuid.UUID | None = None,
    severity: str = "MEDIUM",
) -> None:
    """security_events (LLD 7.7) — failed logins, invalid OTP, hash
    mismatches, unauthorized access attempts (FR-019, FR-020)."""
    db.add(
        SecurityEvent(
            event_type=event_type,
            actor_id=actor_id,
            paper_id=paper_id,
            severity=severity,
        )
    )
    db.commit()


def record_audit_event(
    db: Session,
    event_type: str,
    actor_id: uuid.UUID | None,
    outcome: str,
    paper_id: uuid.UUID | None = None,
) -> None:
    """
    audit_events (LLD 7.6) operational copy + Hyperledger Fabric
    immutable copy (CC-08 RecordAuditEvent), per FR-017.

    Blockchain failure handling here uses the same "NOT YET DETERMINED
    retry policy" as elsewhere (LLD Section 18) — this prototype does
    not retry; the operational DB row is still written even if the
    stub ledger call fails or raises. Never logs paper contents, keys,
    or secrets — only IDs and short string labels.
    """
    ledger_tx_reference = None
    try:
        blockchain = get_blockchain_service()
        ledger_tx_reference = blockchain.record_audit_event(
            event_type=event_type, actor_id=actor_id, paper_id=paper_id, outcome=outcome
        )
    except Exception:  # noqa: BLE001 — deliberately broad: ledger unavailability must never block the audit write
        logger.warning("Blockchain audit write failed for event_type=%s; recording operational copy only.", event_type)
        ledger_tx_reference = None

    db.add(
        AuditEvent(
            event_type=event_type,
            actor_id=actor_id,
            paper_id=paper_id,
            outcome=outcome,
            ledger_tx_reference=ledger_tx_reference,
        )
    )
    db.commit()


# ---------------------------------------------------------------------------
# Phase 6C additions — read-side queries for LLD API-09 (GET /audit/logs) and
# API-10 (GET /monitoring/security-events). Deliberately added to THIS module
# (not a second/duplicate audit system) since this is already the one place
# that owns both audit_events and security_events persistence.
#
# Both functions return (rows, total) where each row is a
# (ModelInstance, actor_username_or_None) tuple from an outer join against
# users — a username is safe to expose (unlike password_hash) and turns an
# opaque actor_id UUID into something a human reviewer can actually read.
# The join is LEFT OUTER because actor_id is nullable (system-generated
# events with no specific human actor) and because a user row could in
# principle be missing (should not happen in practice; a left join makes
# that a None username rather than dropping the whole audit row).
# ---------------------------------------------------------------------------


def list_audit_events(
    db: Session,
    page: int,
    page_size: int,
    paper_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    event_type: str | None = None,
    outcome: str | None = None,
    centre_id: uuid.UUID | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
) -> tuple[list[tuple[AuditEvent, str | None]], int]:
    """
    LLD API-09. Filters are all optional and additive (AND-combined).
    centre_id is resolved via the acting user's own centre_id (users.
    centre_id, LLD 7.1) — audit_events itself has no centre_id column
    (LLD 7.6 does not define one), so this filter only ever matches
    events whose ACTOR is a member of that centre; it does not attempt
    to infer a centre from paper_authorizations, which would be a
    different (and weaker) notion of "this event relates to centre X."

    Pagination is offset/limit-based (page, page_size), matching the
    same pattern used by app.services.paper_service.list_papers (Phase
    6C) and app.services.centre_service.list_centres — no new
    pagination convention is introduced.
    """
    query = db.query(AuditEvent, User.username).outerjoin(User, AuditEvent.actor_id == User.user_id)

    if paper_id is not None:
        query = query.filter(AuditEvent.paper_id == paper_id)
    if actor_id is not None:
        query = query.filter(AuditEvent.actor_id == actor_id)
    if event_type is not None:
        query = query.filter(AuditEvent.event_type == event_type)
    if outcome is not None:
        query = query.filter(AuditEvent.outcome == outcome)
    if centre_id is not None:
        query = query.filter(User.centre_id == centre_id)
    if start_date is not None:
        query = query.filter(AuditEvent.created_at >= start_date)
    if end_date is not None:
        query = query.filter(AuditEvent.created_at <= end_date)

    total = query.count()
    rows = (
        query.order_by(AuditEvent.created_at.desc(), AuditEvent.event_id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return rows, total


def list_security_events(
    db: Session,
    page: int,
    page_size: int,
    severity: str | None = None,
    event_type: str | None = None,
    paper_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    centre_id: uuid.UUID | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
) -> tuple[list[tuple[SecurityEvent, str | None]], int]:
    """LLD API-10. Same filtering/pagination/centre-resolution approach as list_audit_events()."""
    query = db.query(SecurityEvent, User.username).outerjoin(User, SecurityEvent.actor_id == User.user_id)

    if severity is not None:
        query = query.filter(SecurityEvent.severity == severity)
    if event_type is not None:
        query = query.filter(SecurityEvent.event_type == event_type)
    if paper_id is not None:
        query = query.filter(SecurityEvent.paper_id == paper_id)
    if actor_id is not None:
        query = query.filter(SecurityEvent.actor_id == actor_id)
    if centre_id is not None:
        query = query.filter(User.centre_id == centre_id)
    if start_date is not None:
        query = query.filter(SecurityEvent.created_at >= start_date)
    if end_date is not None:
        query = query.filter(SecurityEvent.created_at <= end_date)

    total = query.count()
    rows = (
        query.order_by(SecurityEvent.created_at.desc(), SecurityEvent.security_event_id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return rows, total
