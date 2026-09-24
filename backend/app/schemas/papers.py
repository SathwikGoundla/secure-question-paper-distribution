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

from pydantic import BaseModel, Field


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


class PaperAuthorizeRequest(BaseModel):
    """LLD API-06 request body: centre_id."""

    centre_id: uuid.UUID


class PaperAuthorizeResponse(BaseModel):
    """LLD API-06 response: "Authorization confirmation, ledger transaction reference." """

    authorization_id: uuid.UUID
    paper_id: uuid.UUID
    centre_id: uuid.UUID
    authorized_at: datetime
