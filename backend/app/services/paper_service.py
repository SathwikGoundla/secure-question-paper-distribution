"""
PaperService — Phase 3 (SRS FR-006–FR-011, FR-014; LLD Section 5.5,
API-04–API-08).

Orchestrates the paper lifecycle by composing the existing, already-
tested Phase 1/2 building blocks (StorageService, AuthorizationService,
AuditService) with the new CryptoService — no authentication or RBAC
logic is duplicated or modified here; that remains entirely in
app/api/deps.py and app/services/auth_service.py.

Explicitly OUT OF SCOPE (still, after Phase 5E) and therefore NOT
implemented here:
  - React frontend, evaluation, feedback

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

Phase 5E addition: retrieve_paper() now ALSO calls
get_blockchain_service().verify_paper_hash(paper_id, recomputed_hash)
as a THIRD, independent integrity gate, after the two existing local
gates (AES-256-GCM auth tag, then SHA-256-of-plaintext vs
paper.sha256_hash) both already succeed. This is deliberately additive,
never a replacement:
  - Under BLOCKCHAIN_BACKEND=stub, verify_paper_hash() is never called
    at all — guarded by BlockchainService.supports_ledger_verification,
    an explicit capability flag (False for StubBlockchainService, True
    only for FabricBlockchainService; see blockchain_service.py) checked
    BEFORE any call is attempted — so retrieval behaves EXACTLY as it
    did before Phase 5E under the default backend. This is a hard
    backward-compatibility requirement, not an incidental detail.
  - Under BLOCKCHAIN_BACKEND=fabric, an explicit ledger match=False is a
    genuine, positive integrity disagreement from an INDEPENDENT source
    (Fabric's own copy of the hash, recorded at registration and never
    touched by anything that could also have touched PostgreSQL) and
    ALWAYS rejects the paper (409) — this is never swallowed by any
    failure-tolerance policy, in either best_effort or strict mode
    (FABRIC_VERIFICATION_MODE, app/config.py).
  - Only when a comparison could not be OBTAINED AT ALL (Fabric/adapter
    unreachable or timed out, or this specific paper has no ledger
    record — e.g. its Phase 5D registration-time ledger write itself
    failed) does FABRIC_VERIFICATION_MODE decide the outcome:
    "best_effort" (default) proceeds on the two local checks alone and
    records BLOCKCHAIN_VERIFICATION_UNAVAILABLE/DEGRADED;
    "strict" rejects with 503 instead. See that setting's docstring in
    app/config.py, and PROJECT_STATE.md's Phase 5E section, for the
    full trade-off reasoning behind defaulting to best_effort.
  - The hash sent to Fabric for comparison is the SAME
    SHA256(plaintext) value already computed for the existing local
    check (Section "Hashing design" below) — no second, incompatible
    hash definition is introduced.
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
    UnsupportedOperationException,
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


def list_papers(
    db: Session,
    current_user: CurrentUser,
    page: int,
    page_size: int,
    status_filter: str | None = None,
) -> tuple[list[Paper], int]:
    """
    Phase 6C addition — GET /papers. Not a numbered LLD API, but
    required for the Admin Portal to show a real paper catalogue
    (PROJECT_STATE.md Phase 6B Section 17.20 documented this exact
    gap). Scoping mirrors the already-approved pattern from
    get_paper_metadata()/retrieve_paper():

      - Admin sees every paper (LLD API-05's "Admin (any paper)").
      - Examination Centre sees ONLY papers it is currently, non-
        revoked-ly authorized for (LLD API-05's "Examination Centre
        (only if authorized for this paper)", generalised from a
        single paper to the list case) — never a full catalogue, so
        this endpoint cannot be used to enumerate papers a centre has
        no legitimate claim on.
      - Any other role is rejected. In practice this branch is
        unreachable via the API today because the router's own
        require_role("Admin", "Examination Centre") dependency already
        rejects every other role before this function is called; kept
        here as defense-in-depth in case this function is ever called
        from a second caller that forgets to apply that same RBAC.

    Ordering is stable (created_at DESC, paper_id DESC as a tie-
    breaker for rows with an identical timestamp), so repeated calls
    with the same filters return pages in a consistent order.
    """
    query = db.query(Paper)

    if current_user.role_name == "Examination Centre":
        if current_user.centre_id is None:
            return [], 0
        query = query.join(
            PaperAuthorization, PaperAuthorization.paper_id == Paper.paper_id
        ).filter(
            PaperAuthorization.centre_id == current_user.centre_id,
            PaperAuthorization.is_revoked == False,  # noqa: E712
        )
    elif current_user.role_name != "Admin":
        raise ForbiddenException("You do not have permission to list question papers.")

    if status_filter is not None:
        query = query.filter(Paper.status == status_filter)

    total = query.count()
    items = (
        query.order_by(Paper.created_at.desc(), Paper.paper_id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return items, total


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
      5. (Phase 5E) Blockchain-backed ledger verification — a THIRD,
         independent integrity gate, only when the configured backend
         supports it (see _verify_against_blockchain_ledger()'s
         docstring below for the full three-outcome handling and the
         module docstring above for the security rationale).

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

    # --- Phase 5E: blockchain-backed integrity verification (SRS FR-010/
    # FR-011 extended; see module docstring above and PROJECT_STATE.md's
    # Phase 5E section for the full design). This is a THIRD, independent
    # gate — it never replaces the two local checks above, which have
    # already both succeeded by this point.
    _verify_against_blockchain_ledger(db, current_user, paper, recomputed_hash)

    record_audit_event(
        db, "PAPER_RELEASED", actor_id=current_user.user_id, outcome="SUCCESS", paper_id=paper_id
    )

    return plaintext


def _verify_against_blockchain_ledger(
    db: Session, current_user: CurrentUser, paper: Paper, recomputed_hash: str
) -> None:
    """
    Phase 5E. Calls get_blockchain_service().verify_paper_hash() with the
    SAME SHA256(plaintext) value the local check just used (no second,
    incompatible hash definition — see crypto_service.py / module
    docstring). Raises ConflictException (409) on a genuine ledger
    disagreement; otherwise returns None (paper may proceed).

    Exactly three outcomes are possible, and they are handled by three
    separate, non-overlapping branches below — this function does NOT
    use one broad `except Exception: continue` (that would silently
    swallow a genuine match=False along with real unavailability, which
    is explicitly forbidden):

      1. The configured backend does not implement ledger verification
         at all (BlockchainService.supports_ledger_verification is
         False — the PERMANENT, EXPECTED state for BLOCKCHAIN_BACKEND=
         stub; only FabricBlockchainService sets this True — see
         blockchain_service.py). Checked via this explicit capability
         flag BEFORE calling verify_paper_hash() at all, so an
         unsupporting backend is never actually invoked for it (not
         "invoked and its UnsupportedOperationException is caught every
         time" — literally never called). Not a failure of any kind:
         skip silently, no audit event (an audit event for "stub
         doesn't support this" on every single retrieval would be
         noise, not signal).

      2. Verification COULD NOT BE OBTAINED (ServiceUnavailableException —
         Fabric/adapter unreachable, timed out, or returned an unexpected
         error; or NotFoundException — this specific paper_id has no
         ledger record at all, which can legitimately happen today
         because Phase 5D's own registration-time ledger write is itself
         best-effort and can fail/be skipped). Governed by
         FABRIC_VERIFICATION_MODE:
           - "best_effort" (default): record
             BLOCKCHAIN_VERIFICATION_UNAVAILABLE/DEGRADED and return
             (the two already-passed local checks are sufficient).
           - "strict": record the same event with outcome FAILURE and
             raise ServiceUnavailableException (503).

      3. Verification WAS obtained and disagrees (match is False). This
         is a genuine, positive integrity signal from a source
         independent of PostgreSQL (see module docstring's security
         rationale) and is NEVER treated as "unavailable" — it always
         raises ConflictException (409), in BOTH best_effort and strict
         mode, regardless of FABRIC_VERIFICATION_MODE.

    match is True falls through with no new audit event — PAPER_RELEASED/
    SUCCESS (recorded by the caller immediately after this returns)
    already covers "everything passed."
    """
    settings = get_settings()
    blockchain = get_blockchain_service()

    if not getattr(blockchain, "supports_ledger_verification", False):
        # Branch 1 — see docstring. verify_paper_hash() is deliberately
        # NEVER CALLED here (this is a capability check, not a
        # call-and-catch) — this is what keeps BLOCKCHAIN_BACKEND=stub
        # retrieval byte-for-byte unchanged from before Phase 5E.
        return

    try:
        match = blockchain.verify_paper_hash(paper_id=paper.paper_id, candidate_hash=recomputed_hash)
    except UnsupportedOperationException:
        # Defense-in-depth only: a backend that claims support via the
        # flag above but still raises this would be an internal
        # inconsistency in that backend, not an expected path today (no
        # shipped backend does this) — handled the same as Branch 1
        # rather than crashing the retrieval.
        return
    except (ServiceUnavailableException, NotFoundException) as exc:
        # Branch 2 — see docstring. Deliberately narrow: only these two
        # exception types are treated as "verification could not be
        # obtained." Any other exception type (e.g. a ValidationFailedException
        # or ConflictException from the adapter itself, which would indicate
        # an unexpected bug in the request this code builds, not an
        # availability problem) is NOT caught here and propagates as-is,
        # per the explicit instruction not to catch every exception.
        logger.warning(
            "Blockchain-backed integrity verification could not be completed for "
            "paper_id=%s (%s: %s); FABRIC_VERIFICATION_MODE=%s.",
            paper.paper_id,
            type(exc).__name__,
            exc.message,
            settings.FABRIC_VERIFICATION_MODE,
        )
        if settings.FABRIC_VERIFICATION_MODE == "strict":
            record_audit_event(
                db,
                "BLOCKCHAIN_VERIFICATION_UNAVAILABLE",
                actor_id=current_user.user_id,
                outcome="FAILURE",
                paper_id=paper.paper_id,
            )
            raise ServiceUnavailableException(
                "Blockchain-backed integrity verification is currently unavailable "
                "and FABRIC_VERIFICATION_MODE=strict requires it to succeed before "
                "this paper can be released."
            ) from exc
        record_audit_event(
            db,
            "BLOCKCHAIN_VERIFICATION_UNAVAILABLE",
            actor_id=current_user.user_id,
            outcome="DEGRADED",
            paper_id=paper.paper_id,
        )
        return

    if match is False:
        # Branch 3 — see docstring. Always fails closed, in both modes.
        record_security_event(
            db, "LEDGER_HASH_MISMATCH", actor_id=current_user.user_id, paper_id=paper.paper_id, severity="HIGH"
        )
        record_audit_event(
            db, "TAMPER_DETECTED", actor_id=current_user.user_id, outcome="REJECTED", paper_id=paper.paper_id
        )
        raise ConflictException(
            "This paper failed blockchain-backed integrity verification and cannot be released."
        )
    # match is True: fall through, no new event (see docstring).
