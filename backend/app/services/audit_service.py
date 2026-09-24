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

from sqlalchemy.orm import Session

from app.models.audit_event import AuditEvent
from app.models.security_event import SecurityEvent
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
