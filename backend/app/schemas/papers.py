"""
Request/response schemas for the paper lifecycle (LLD API-04–API-08).

Response models are deliberately narrow, mirroring schemas/auth.py's
existing convention: encryption keys (wrapped or otherwise), nonces,
and internal storage references are NEVER included (SEC-010 — "never
expose secrets in API responses"). file_nonce/wrapped_dek are not
secrets in the cryptographic sense (a nonce is not confidential), but
they are internal implementation detail with no legitimate use by an
API client, so they are excluded on the same "narrow response" principle
already established by schemas/auth.py.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Phase 6H — the two fields below deliberately mean different things and
# must not be conflated (full definitions in PROJECT_STATE.md Phase 6H):
#   status       = REGISTRATION status, persisted. Today always "registered".
#   lock_status  = RELEASE state, computed by the server clock from
#                  release_timestamp on every response ("released" only
#                  means the scheduled time has been reached).
# Neither says whether any centre has opened the paper; that is access
# history and lives in the audit log (PAPER_RELEASED events).
_STATUS_DESC = (
    "Registration status of the paper (persisted). Not a release or access indicator; "
    "see lock_status for release state."
)
_LOCK_DESC = (
    "Release state computed by the server clock: 'released' once release_timestamp has "
    "been reached, otherwise 'locked'. Does not indicate that any centre has retrieved the paper."
)


class PaperRegisterResponse(BaseModel):
    """LLD API-04 response: "paper_id, registration status, ledger transaction reference." """

    paper_id: uuid.UUID
    subject: str
    status: str = Field(description=_STATUS_DESC)
    sha256_hash: str
    encryption_algorithm: str
    release_timestamp: datetime
    created_at: datetime
    ledger_tx_reference: str | None = None
    lock_status: Literal["locked", "released"] = Field(description=_LOCK_DESC)


class PaperMetadataResponse(BaseModel):
    """LLD API-05 response: "Paper metadata (excludes encrypted file and plaintext)." """

    paper_id: uuid.UUID
    subject: str
    status: str = Field(description=_STATUS_DESC)
    sha256_hash: str
    release_timestamp: datetime
    created_at: datetime
    lock_status: Literal["locked", "released"] = Field(description=_LOCK_DESC)


class PaperStatusResponse(BaseModel):
    """LLD API-08 response: "lock_status (locked/released), last_integrity_check_result." """

    paper_id: uuid.UUID
    status: str = Field(description=_STATUS_DESC)
    release_timestamp: datetime
    # Phase 6G: computed by the backend clock at request time from
    # release_timestamp (see paper_service.is_released) — NOT stored,
    # so it can never drift from the time-lock that actually governs
    # retrieval. Informational only; retrieve_paper re-checks on its own.
    lock_status: Literal["locked", "released"]


class PaperRescheduleRequest(BaseModel):
    """Phase 6G: PATCH /papers/{paper_id}/schedule request body. The
    timestamp MUST carry a timezone (validated in paper_service)."""

    release_timestamp: datetime


class PaperScheduleResponse(BaseModel):
    """Phase 6G: PATCH /papers/{paper_id}/schedule response."""

    paper_id: uuid.UUID
    release_timestamp: datetime
    lock_status: Literal["locked", "released"]


class PaperListItemResponse(BaseModel):
    """
    Phase 6C addition — one row of GET /papers (list). Field set is
    deliberately identical to PaperMetadataResponse PLUS
    ledger_tx_reference, which is safe to expose (it is a public-style
    ledger transaction identifier, not a secret — see PaperRegisterResponse,
    which already exposes it) and is explicitly called out as allowed
    for the paper list by the Phase 6C brief (Section 11). Never
    file_nonce, wrapped_dek, or file_reference (internal storage path).
    """

    model_config = ConfigDict(from_attributes=True)

    paper_id: uuid.UUID
    subject: str
    status: str = Field(description=_STATUS_DESC)
    sha256_hash: str
    release_timestamp: datetime
    created_at: datetime
    ledger_tx_reference: str | None = None
    # Phase 6H: not an ORM attribute — the list route supplies it via
    # paper_service.lock_status_for (single source of release state).
    lock_status: Literal["locked", "released"] = Field(description=_LOCK_DESC)


class PaperListResponse(BaseModel):
    """Phase 6C addition — paginated envelope for GET /papers."""

    items: list[PaperListItemResponse]
    total: int
    page: int
    page_size: int


class PaperAuthorizeRequest(BaseModel):
    """LLD API-06 request body: centre_id."""

    centre_id: uuid.UUID


class PaperAuthorizeResponse(BaseModel):
    """LLD API-06 response: "Authorization confirmation, ledger transaction reference." """

    authorization_id: uuid.UUID
    paper_id: uuid.UUID
    centre_id: uuid.UUID
    authorized_at: datetime


class PaperScheduleHistoryItem(BaseModel):
    """
    Phase 6H: one successful release-time change. Narrow on purpose:
    only the paper, who/what/when, and the old/new instants (UTC).
    actor_username is a human-readable convenience (same as the audit-log
    API); no secrets or unrelated audit metadata are included.
    """

    history_id: uuid.UUID
    paper_id: uuid.UUID
    action: str
    previous_release_timestamp: datetime
    new_release_timestamp: datetime
    actor_id: uuid.UUID
    actor_username: str | None = None
    created_at: datetime


class PaperScheduleHistoryResponse(BaseModel):
    """Phase 6H: paginated envelope (same shape as GET /papers), oldest first."""

    items: list[PaperScheduleHistoryItem]
    total: int
    page: int
    page_size: int
