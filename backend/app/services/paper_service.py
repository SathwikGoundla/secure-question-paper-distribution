"""
PaperService — Phase 3 (SRS FR-006–FR-011, FR-014; LLD Section 5.5,
API-04–API-08).

Orchestrates the paper lifecycle by composing the existing, already-
tested Phase 1/2 building blocks (StorageService, AuthorizationService,
AuditService) with the new CryptoService — no authentication or RBAC
logic is duplicated or modified here; that remains entirely in
app/api/deps.py and app/services/auth_service.py.

Explicitly OUT OF SCOPE (still, after Phase 5D) and therefore NOT
implemented here:
  - React frontend, evaluation, feedback
  - Ledger-backed retrieval verification (verify_paper_hash() is NOT
    called from retrieve_paper() — an explicit Phase 5D scope decision,
    deferred to a later, separately-planned phase; see PROJECT_STATE.md)

Phase 4 addition: time-lock enforcement (SRS FR-012/FR-016; LLD Section
16) is now implemented in retrieve_paper() below — see that function's
docstring for the exact check order and security reasoning.

Phase 5D addition: register_paper() now performs a best-effort
Hyperledger Fabric ledger write (SRS FR-018, LLD CC-01/RegisterPaper)
via the existing get_blockchain_service() abstraction, AFTER the
PostgreSQL row and encrypted file are already durably persisted. See
that function's body for the exact failure-tolerance reasoning (it
mirrors audit_service.record_audit_event()'s already-established
pattern: blockchain unavailability never fails a registration that
PostgreSQL/storage already accepted).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.api.deps import CurrentUser
from app.config import get_settings
from app.exceptions.base import (
    ConflictException,
    ForbiddenException,
    NotFoundException,
    ServiceUnavailableException,
    ValidationFailedException,
)
from app.models.exam_centre import ExamCentre
from app.models.paper import Paper
from app.models.paper_authorization import PaperAuthorization
from app.services import crypto_service
from app.services.audit_service import record_audit_event, record_security_event
from app.services.authorization_service import is_centre_authorized_for_paper
from app.services.blockchain_service import get_blockchain_service
from app.services.storage_service import StorageError, get_storage_service

logger = logging.getLogger(__name__)

_PDF_MAGIC = b"%PDF-"


def _validate_pdf_upload(filename: str | None, content_type: str | None, file_bytes: bytes) -> None:
    """
    FR-006 acceptance criteria ("Paper is recorded with validated
    metadata before protection"). Deliberately checks the actual file
    CONTENT (magic bytes), not just the filename extension or the
    client-supplied Content-Type header, since both of those are
    trivially spoofable and validating only them would be a false
    sense of security.
    """
    settings = get_settings()

    if not file_bytes:
        raise ValidationFailedException("The uploaded file is empty.")

    if len(file_bytes) > settings.PAPER_MAX_UPLOAD_SIZE_BYTES:
        max_mb = settings.PAPER_MAX_UPLOAD_SIZE_BYTES / (1024 * 1024)
        raise ValidationFailedException(f"The uploaded file exceeds the {max_mb:.0f} MB size limit.")

    if not file_bytes.startswith(_PDF_MAGIC):
        raise ValidationFailedException("The uploaded file does not appear to be a valid PDF.")


def register_paper(
    db: Session,
    admin_user: CurrentUser,
    subject: str,
    release_timestamp: datetime,
    filename: str | None,
    content_type: str | None,
    file_bytes: bytes,
) -> Paper:
    """
    LLD API-04 (POST /papers/register). Full pipeline:
    validate -> SHA-256(plaintext) -> AES-256-GCM encrypt -> store
    ciphertext -> persist metadata -> audit. See crypto_service.py for
    why the hash is computed over the plaintext (a documented deviation
    from LLD Section 13).
    """
    record_audit_event(
        db, "PAPER_UPLOAD_INITIATED", actor_id=admin_user.user_id, outcome="SUCCESS"
    )

    try:
        _validate_pdf_upload(filename, content_type, file_bytes)
    except ValidationFailedException:
        record_audit_event(
            db, "PAPER_PROCESSING_FAILURE", actor_id=admin_user.user_id, outcome="REJECTED"
        )
        raise

    try:
        result = crypto_service.encrypt_paper(file_bytes)
    except crypto_service.CryptoError as exc:
        record_audit_event(
            db, "PAPER_PROCESSING_FAILURE", actor_id=admin_user.user_id, outcome="FAILURE"
        )
        raise ServiceUnavailableException(
            "Paper encryption is not currently available. Contact the administrator."
        ) from exc

    record_audit_event(
        db, "PAPER_ENCRYPTION_COMPLETED", actor_id=admin_user.user_id, outcome="SUCCESS"
    )

    storage = get_storage_service()
    file_reference = storage.save_encrypted_file(result.ciphertext)

    paper = Paper(
        subject=subject,
        file_reference=file_reference,
        sha256_hash=result.sha256_hex,
        release_timestamp=release_timestamp,
        status="registered",
        registered_by=admin_user.user_id,
        encryption_algorithm=result.algorithm,
        file_nonce=result.file_nonce_b64,
        wrapped_dek=result.wrapped_dek_b64,
        original_filename=filename,
        file_size_bytes=len(file_bytes),
    )

    try:
        db.add(paper)
        db.commit()
        db.refresh(paper)
    except Exception:
        # DB persistence failed after a successful storage write — clean up
        # the orphaned encrypted file rather than leaving it unreferenced
        # (explicit Phase 3 requirement: "do not leave an orphaned encrypted
        # file if the architecture allows safe cleanup").
        db.rollback()
        try:
            storage.delete_encrypted_file(file_reference)
        except StorageError:
            pass  # best-effort cleanup; the original DB error is what matters to the caller
        record_audit_event(
            db, "PAPER_PROCESSING_FAILURE", actor_id=admin_user.user_id, outcome="FAILURE"
        )
        raise

    # --- Phase 5D: best-effort blockchain (Hyperledger Fabric) registration ---
    # (SRS FR-018, LLD CC-01/RegisterPaper). paper_id was generated exactly
    # once above (Paper()'s uuid_pk default) and is never regenerated — so
    # this call happens at most once per successfully-committed PostgreSQL
    # row, and a client re-POSTing after a failure creates a brand-new
    # paper_id (a genuinely new paper, not a retry of this one), which
    # cannot collide with the chaincode's DUPLICATE_PAPER rejection.
    #
    # Failure tolerance mirrors the EXISTING, already-approved pattern in
    # audit_service.record_audit_event() exactly: PostgreSQL + off-chain
    # storage are this project's primary source of truth (see
    # models/paper.py, HLD Section 8); the ledger write is a durability/
    # tamper-evidence enhancement, never a gate. A failed or unreachable
    # blockchain backend (Stub or Fabric) must never fail, roll back, or
    # otherwise invalidate a paper that PostgreSQL + storage already
    # accepted. This call goes through the SAME get_blockchain_service()
    # abstraction used everywhere else — it is not Fabric-specific code
    # here; under BLOCKCHAIN_BACKEND=stub (the default) it registers with
    # StubBlockchainService exactly as it always could have, and under
    # BLOCKCHAIN_BACKEND=fabric it reaches the real chaincode via
    # FabricBlockchainService (Phase 5C). Only paper_id, sha256_hash,
    # release_timestamp, admin_id, subject, and encryption_algorithm are
    # ever sent — never the PDF, the AES key, the wrapped DEK, or any
    # secret (SEC-001/SEC-010; unchanged from the existing architecture).
    try:
        blockchain = get_blockchain_service()
        ledger_tx_reference = blockchain.register_paper(
            paper_id=paper.paper_id,
            sha256_hash=paper.sha256_hash,
            release_timestamp=paper.release_timestamp,
            metadata={
                "admin_id": str(admin_user.user_id),
                "subject": paper.subject,
                "encryption_algorithm": paper.encryption_algorithm,
            },
        )
    except Exception:  # noqa: BLE001 — deliberately broad: ledger unavailability
        # must never fail an already-successful PostgreSQL/storage
        # registration. Logged (safely — no secrets, no key material,
        # no PDF content, only the paper_id) rather than silently
        # swallowed, so operators can see it happened.
        logger.warning(
            "Blockchain registration failed for paper_id=%s; PostgreSQL/storage "
            "registration remains valid. ledger_tx_reference will be recorded as None.",
            paper.paper_id,
        )
    else:
        try:
            paper.ledger_tx_reference = ledger_tx_reference
            db.commit()
            db.refresh(paper)
        except Exception:  # noqa: BLE001 — same reasoning: a failure to persist the
            # tx reference locally must not invalidate the paper itself,
            # which was already durably committed above.
            db.rollback()
            logger.warning(
                "Blockchain registration for paper_id=%s succeeded (tx=%s) but "
                "persisting ledger_tx_reference to PostgreSQL failed; the paper "
                "registration itself remains valid.",
                paper.paper_id,
                ledger_tx_reference,
            )
            db.refresh(paper)

    record_audit_event(
        db,
        "PAPER_REGISTRATION_COMPLETED",
        actor_id=admin_user.user_id,
        outcome="SUCCESS",
        paper_id=paper.paper_id,
    )

    return paper


def get_paper_by_id_or_404(db: Session, paper_id: uuid.UUID) -> Paper:
    paper = db.get(Paper, paper_id)
    if paper is None:
        raise NotFoundException("The requested resource was not found.")
    return paper


def get_paper_metadata(db: Session, current_user: CurrentUser, paper_id: uuid.UUID) -> Paper:
    """LLD API-05. Admin: any paper. Examination Centre: only an authorized paper."""
    paper = get_paper_by_id_or_404(db, paper_id)

    if current_user.role_name == "Examination Centre":
        if current_user.centre_id is None or not is_centre_authorized_for_paper(
            db, current_user.centre_id, paper_id
        ):
            record_security_event(
                db, "UNAUTHORIZED_ACCESS", actor_id=current_user.user_id, paper_id=paper_id
            )
            raise ForbiddenException("You are not authorized to access this paper.")

    return paper


def authorize_centre(
    db: Session, admin_user: CurrentUser, paper_id: uuid.UUID, centre_id: uuid.UUID
) -> PaperAuthorization:
    """LLD API-06 (POST /papers/{paper_id}/authorize). Admin-only."""
    get_paper_by_id_or_404(db, paper_id)  # 404 if the paper itself doesn't exist

    centre = db.get(ExamCentre, centre_id)
    if centre is None:
        raise ValidationFailedException("Unknown centre_id.")

    existing = (
        db.query(PaperAuthorization)
        .filter(
            PaperAuthorization.paper_id == paper_id,
            PaperAuthorization.centre_id == centre_id,
            PaperAuthorization.is_revoked == False,  # noqa: E712
        )
        .first()
    )
    if existing is not None:
        return existing  # idempotent: authorizing an already-authorized centre is not an error

    authorization = PaperAuthorization(
        paper_id=paper_id,
        centre_id=centre_id,
        authorized_by=admin_user.user_id,
        authorized_at=datetime.now(timezone.utc),
        is_revoked=False,
    )
    db.add(authorization)
    db.commit()
    db.refresh(authorization)

    record_audit_event(
        db,
        "CENTRE_AUTHORIZATION_GRANTED",
        actor_id=admin_user.user_id,
        outcome="SUCCESS",
        paper_id=paper_id,
    )

    return authorization


def retrieve_paper(db: Session, current_user: CurrentUser, paper_id: uuid.UUID) -> bytes:
    """
    LLD API-07 (GET /papers/{paper_id}/retrieve). Implements, in order
    (LLD Section 16's TimeLockCheck algorithm, Section 17's
    RetrievePaper algorithm):

      1. Identify the paper (404 if unknown).
      2. Verify examination-centre authorization (403 if not authorized
         for THIS paper).
      3. Check the time-lock: current backend UTC time >=
         paper.release_timestamp (403 if not yet released — Phase 4).
      4. Retrieve ciphertext, AES-256-GCM decrypt (first tamper-
         detection gate, via the GCM auth tag), then a SHA-256 re-check
         over the recovered plaintext (second, independent integrity
         confirmation — see crypto_service.py's module docstring for
         why the check order differs from LLD Section 17's original
         pseudocode, which hashed the ciphertext).

    SECURITY REASONING for checking authorization BEFORE time-lock
    (matching LLD Section 16 Step 2 before Steps 3-6, not the reverse):
    a centre with no legitimate claim on a paper at all should get a
    uniform 403 "not authorized" WITHOUT ever learning whether that
    paper is time-locked, already released, or even fully registered —
    revealing release-schedule information to an unauthorized party is
    itself a minor information leak this ordering avoids.

    PHASE 4 NOTE: the "PAPER_ACCESS_ATTEMPT" / outcome="PERMITTED"
    audit event (unchanged event TYPE from Phase 3) is now recorded
    only once BOTH authorization and the time-lock check succeed —
    Phase 3 recorded it immediately after authorization alone, which
    did not quite match LLD Section 16 (there, the "permitted" access-
    attempt record is the LAST step, after the time check, not the
    first). This is a sequencing correction, not a new event type, and
    does not change what Phase 3's existing tests assert (that the
    event exists at all after a successful end-to-end retrieval).
    """
    paper = get_paper_by_id_or_404(db, paper_id)

    if current_user.centre_id is None or not is_centre_authorized_for_paper(
        db, current_user.centre_id, paper_id
    ):
        record_audit_event(
            db, "PAPER_ACCESS_ATTEMPT", actor_id=current_user.user_id, outcome="DENIED", paper_id=paper_id
        )
        record_security_event(
            db, "UNAUTHORIZED_ACCESS", actor_id=current_user.user_id, paper_id=paper_id
        )
        raise ForbiddenException("You are not authorized to access this paper.")

    # --- Phase 4: time-lock enforcement (SRS FR-012/FR-016; LLD Section 16) ---
    # Trusted BACKEND clock only — never a client-supplied value (SEC-006).
    # release_timestamp is a DateTime(timezone=True) column; on the real
    # target database (PostgreSQL) this always round-trips tz-aware. (A
    # SQLite-only round-trip quirk — SQLite silently drops tzinfo on such
    # columns — is compensated for at the TEST level only, in
    # tests/conftest.py; see that file's docstring. No defensive
    # naive/aware normalization is added here in application code, by
    # the same reasoning already applied to auth_service.py in Phase 3:
    # don't paper over a test-harness artifact in code that is correct
    # for the actual production database.)
    current_time = datetime.now(timezone.utc)
    if current_time < paper.release_timestamp:
        record_security_event(
            db, "PRE_RELEASE_ATTEMPT", actor_id=current_user.user_id, paper_id=paper_id, severity="MEDIUM"
        )
        record_audit_event(
            db, "PRE_RELEASE_ATTEMPT", actor_id=current_user.user_id, outcome="DENIED", paper_id=paper_id
        )
        raise ForbiddenException("This paper is not yet available.")

    record_audit_event(
        db, "PAPER_ACCESS_ATTEMPT", actor_id=current_user.user_id, outcome="PERMITTED", paper_id=paper_id
    )

    storage = get_storage_service()
    ciphertext = storage.retrieve_encrypted_file(paper.file_reference)
    if ciphertext is None:
        record_audit_event(
            db, "PAPER_PROCESSING_FAILURE", actor_id=current_user.user_id, outcome="FAILURE", paper_id=paper_id
        )
        # LLD Section 18 marks "missing encrypted file" behaviour as NOT YET
        # DETERMINED; this Phase 3 decision maps it to 503 (a dependency —
        # storage — failed to produce an expected artifact), distinct from
        # 404 (which means the paper_id itself is unknown).
        raise ServiceUnavailableException("The encrypted paper file could not be located in storage.")

    try:
        plaintext = crypto_service.decrypt_paper(ciphertext, paper.file_nonce, paper.wrapped_dek)
    except crypto_service.CryptoError:
        record_security_event(
            db, "HASH_MISMATCH", actor_id=current_user.user_id, paper_id=paper_id, severity="HIGH"
        )
        record_audit_event(
            db, "TAMPER_DETECTED", actor_id=current_user.user_id, outcome="REJECTED", paper_id=paper_id
        )
        raise ConflictException(
            "This paper failed integrity verification and cannot be released."
        )

    recomputed_hash = crypto_service.compute_sha256(plaintext)
    if recomputed_hash != paper.sha256_hash:
        # Should be unreachable if AES-GCM authentication above already
        # passed (the ciphertext was proven authentic) — kept as a second,
        # independent check per the explicit Phase 3 requirement rather
        # than assuming the GCM tag alone is sufficient.
        record_security_event(
            db, "HASH_MISMATCH", actor_id=current_user.user_id, paper_id=paper_id, severity="HIGH"
        )
        record_audit_event(
            db, "TAMPER_DETECTED", actor_id=current_user.user_id, outcome="REJECTED", paper_id=paper_id
        )
        raise ConflictException(
            "This paper failed integrity verification and cannot be released."
        )

    record_audit_event(
        db, "PAPER_RELEASED", actor_id=current_user.user_id, outcome="SUCCESS", paper_id=paper_id
    )

    return plaintext
