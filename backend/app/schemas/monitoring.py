"""
Response schemas for security-event / monitoring retrieval (LLD
API-10, FR-019, FR-020). Same narrow-response, safe-field-only
convention as schemas/audit.py.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel


class SecurityEventResponse(BaseModel):
    security_event_id: uuid.UUID
    event_type: str
    actor_id: uuid.UUID | None
    actor_username: str | None
    paper_id: uuid.UUID | None
    severity: str
    created_at: datetime


class SecurityEventListResponse(BaseModel):
    items: list[SecurityEventResponse]
    total: int
    page: int
    page_size: int
