"""
papers — LLD Section 7.4.

Application-level paper metadata plus the off-chain file reference.
The SHA-256 hash and release timestamp are ALSO recorded on Hyperledger
Fabric as the tamper-evident source of truth (HLD Section 8); this
table's copy exists purely for fast application queries — it is never
the authoritative value at retrieval time (LLD Section 13, 17). NOTE:
Hyperledger Fabric is not yet integrated (Phase 3 scope is
backend/storage/crypto only — see services/blockchain_service.py), so
this PostgreSQL row is currently the ONLY recorded copy; that gap is
tracked in PROJECT_STATE.md, not silently treated as resolved.

No column here stores plaintext question-paper content (SEC-001) — the
file_reference column below points to encrypted bytes at rest, never
the original PDF.

Phase 3 addition — encryption_algorithm / file_nonce / wrapped_dek:
realises the envelope-encryption design left as NOT YET DETERMINED by
LLD Section 12 ("Key-generation mechanism ... NOT YET DETERMINED").
See app/services/crypto_service.py for the full design and the
documented deviation from LLD Section 13 regarding what the SHA-256
hash is computed over (plaintext, per this phase's explicit
instructions, not the encrypted file as LLD Section 13 originally
specified).
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.common import created_at_column, uuid_pk


class Paper(Base):
    __tablename__ = "papers"

    paper_id: Mapped[uuid.UUID] = uuid_pk()
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    file_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    sha256_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    release_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Exact value set NOT YET DETERMINED per LLD 7.4 — using a plain string
    # column (not a DB enum) so the allowed set can be finalised later
    # without a migration to change the column type.
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="registered")
    registered_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False
    )
    created_at = created_at_column()

    # --- Phase 3 encryption metadata (see crypto_service.py) ---
    encryption_algorithm: Mapped[str] = mapped_column(
        String(50), nullable=False, default="AES-256-GCM"
    )
    # base64(12-byte nonce) used to encrypt THIS file with the per-paper DEK.
    # Empty-string default (matching scripts/add_phase3_columns.py's column
    # default) exists ONLY so pre-Phase-3 code paths that construct a Paper
    # row directly without going through paper_service.register_paper()
    # (e.g. the existing, unmodified Phase 2 authorization test script,
    # tests/test_phase2_manual.py, which tests paper_authorizations
    # independently of encryption) do not fail on a NOT NULL violation.
    # Any Paper row with an empty file_nonce/wrapped_dek is NOT
    # decryptable and must be treated as invalid production data.
    file_nonce: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    # base64(12-byte wrap-nonce + wrapped-DEK-ciphertext+tag) — the raw DEK
    # itself is NEVER stored anywhere (SEC-010).
    wrapped_dek: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # Metadata only — never used to build a filesystem path (storage_service
    # always generates its own uuid4-based reference; see path-traversal
    # notes there).
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # --- Phase 5D: Hyperledger Fabric ledger transaction reference ---
    # Populated by paper_service.register_paper() AFTER the row above has
    # already been committed successfully — a best-effort blockchain write,
    # never a precondition for the row's own existence (see paper_service.py
    # for the exact failure-tolerance reasoning, which mirrors the
    # already-established pattern in audit_service.record_audit_event()/
    # AuditEvent.ledger_tx_reference). NULL means either: (a) the
    # blockchain call failed/was unreachable, or (b) this row predates
    # Phase 5D (existing rows are left NULL by the Phase 5D migration
    # script, never backfilled with a fabricated value). NULL is never
    # treated as an error condition by any caller — it is a normal,
    # expected value.
    ledger_tx_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)

    registrar: Mapped["User"] = relationship(foreign_keys=[registered_by])  # noqa: F821
