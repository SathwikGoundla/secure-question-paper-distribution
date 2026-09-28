"""
Response schemas for audit-log retrieval (LLD API-09, FR-017, FR-022).

actor_username is included because it is safe (a username is not a
secret, unlike password_hash) and materially improves the usefulness
of an audit record for a human reviewer, who otherwise only sees an
opaque UUID. No password, OTP, JWT, or key material is ever included.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel


class AuditEventResponse(BaseModel):
    event_id: uuid.UUID
    event_type: str
    actor_id: uuid.UUID | None
    actor_username: str | None
    paper_id: uuid.UUID | None
    outcome: str
    ledger_tx_reference: str | None
    created_at: datetime


class AuditLogListResponse(BaseModel):
    items: list[AuditEventResponse]
    total: int
    page: int
    page_size: int
