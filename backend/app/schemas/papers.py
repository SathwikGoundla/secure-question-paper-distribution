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


class PaperRegisterResponse(BaseModel):
    """LLD API-04 response: "paper_id, registration status, ledger transaction reference." """

    paper_id: uuid.UUID
    subject: str
    status: str
    sha256_hash: str
    encryption_algorithm: str
    release_timestamp: datetime
    created_at: datetime
    ledger_tx_reference: str | None = None


class PaperMetadataResponse(BaseModel):
    """LLD API-05 response: "Paper metadata (excludes encrypted file and plaintext)." """

    paper_id: uuid.UUID
    subject: str
    status: str
    sha256_hash: str
    release_timestamp: datetime
    created_at: datetime


class PaperStatusResponse(BaseModel):
    """LLD API-08 response: "lock_status (locked/released), last_integrity_check_result." """

    paper_id: uuid.UUID
    status: str
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
    status: str
    sha256_hash: str
    release_timestamp: datetime
    created_at: datetime
    ledger_tx_reference: str | None = None


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
