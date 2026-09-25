"""
Phase 5E tests: blockchain-backed integrity verification during paper
RETRIEVAL (as opposed to Phase 5D's tests, which cover the
REGISTRATION-time ledger write in test_paper_blockchain_integration.py).

Scope and design note, matching that file's own convention: the HTTP
wire-protocol correctness of FabricBlockchainService.verify_paper_hash()
itself (request/response shapes, error mapping) is already exhaustively
covered by tests/test_fabric_blockchain_service.py and is NOT re-tested
here. This file tests the NEW orchestration logic added to
paper_service.py in Phase 5E:
paper_service._verify_against_blockchain_ledger() / retrieve_paper() —
does it call verify_paper_hash() at the right time, with the right
(non-secret) arguments, and does it apply the approved
FABRIC_VERIFICATION_MODE policy correctly for each of the three
possible outcomes (match=True, match=False, verification unobtainable)?

As with test_paper_blockchain_integration.py, these tests monkeypatch
`app.services.paper_service.get_blockchain_service` directly with small
fake BlockchainService-like objects — a "patch where it's used" seam,
not a live or even HTTP-mocked Fabric adapter. No claim of live Fabric
verification is made anywhere in this file.

Every test goes through the REAL FastAPI app, REAL RBAC, REAL
authentication, and a REAL (SQLite, file-based) database — same
conventions as test_paper_api.py / test_time_lock.py.
"""

import logging
import uuid

import pytest

from app.exceptions.base import (
    ConflictException,
    NotFoundException,
    ServiceUnavailableException,
    UnsupportedOperationException,
    ValidationFailedException,
)
from app.models.audit_event import AuditEvent
from app.models.paper import Paper
from app.models.security_event import SecurityEvent
from app.services.blockchain_service import StubBlockchainService
from tests.conftest import SAMPLE_PDF_BYTES, auth_header

_RECOMPUTED_HASH = None  # filled lazily via crypto_service.compute_sha256 in a fixture-free helper below


def _sha256_of_sample_pdf() -> str:
    import hashlib

    return hashlib.sha256(SAMPLE_PDF_BYTES).hexdigest()


def _register_and_authorize(client, admin_principal, exam_centre_principal, subject="Blockchain Retrieval Test"):
    """Past release_timestamp by default — these tests are not about
    time-lock (test_time_lock.py covers that)."""
    files = {"file": ("sample.pdf", SAMPLE_PDF_BYTES, "application/pdf")}
    data = {"subject": subject, "release_timestamp": "2020-01-01T00:00:00Z"}
    reg = client.post("/api/v1/papers/register", data=data, files=files, headers=auth_header(admin_principal))
    assert reg.status_code == 201, reg.text
    paper_id = reg.json()["paper_id"]

    authz = client.post(
        f"/api/v1/papers/{paper_id}/authorize",
        json={"centre_id": str(exam_centre_principal.centre_id)},
        headers=auth_header(admin_principal),
    )
    assert authz.status_code == 200, authz.text
    return paper_id


def _retrieve(client, exam_centre_principal, paper_id):
    return client.get(f"/api/v1/papers/{paper_id}/retrieve", headers=auth_header(exam_centre_principal))


class _FakeVerifyingBlockchainService:
    """Minimal stand-in exposing ONLY verify_paper_hash() — matches the
    (paper_id, candidate_hash) -> bool signature retrieve_paper() calls.
    Records every call for assertion."""

    supports_ledger_verification = True

    def __init__(self, match: bool):
        self._match = match
        self.calls: list[dict] = []

    def verify_paper_hash(self, paper_id, candidate_hash):
        self.calls.append({"paper_id": paper_id, "candidate_hash": candidate_hash})
        return self._match


class _FakeUnavailableBlockchainService:
    """Simulates an unreachable/timed-out Fabric Gateway Adapter — the
    real FabricBlockchainService raises exactly ServiceUnavailableException
    in this situation (see fabric_blockchain_service.py's _post/_get)."""

    supports_ledger_verification = True

    def __init__(self, exc: Exception | None = None):
        self._exc = exc or ServiceUnavailableException("Could not reach the Fabric Gateway Adapter (simulated).")
        self.calls: list[dict] = []

    def verify_paper_hash(self, paper_id, candidate_hash):
        self.calls.append({"paper_id": paper_id, "candidate_hash": candidate_hash})
        raise self._exc


class _FakeUnsupportedBlockchainService:
    """Simulates the Branch-1 defense-in-depth path: a backend that
    CLAIMS support (supports_ledger_verification=True) but still raises
    UnsupportedOperationException when actually called — an internal
    inconsistency no shipped backend exhibits today, but one
    paper_service.py deliberately still handles gracefully rather than
    trusting the flag blindly all the way through."""

    supports_ledger_verification = True

    def __init__(self):
        self.calls: list[dict] = []

    def verify_paper_hash(self, paper_id, candidate_hash):
        self.calls.append({"paper_id": paper_id, "candidate_hash": candidate_hash})
        raise UnsupportedOperationException("simulated: this backend does not support verify_paper_hash().")


class _FakeUnexpectedErrorBlockchainService:
    """A backend that raises something OTHER than ServiceUnavailableException
    / NotFoundException / UnsupportedOperationException — must NOT be
    silently swallowed by the best_effort policy (per the explicit
    instruction not to catch every exception)."""

    supports_ledger_verification = True

    def __init__(self, exc: Exception):
        self._exc = exc

    def verify_paper_hash(self, paper_id, candidate_hash):
        raise self._exc


# ---------------------------------------------------------------------------
# 1 & 2. Default Stub retrieval still succeeds; verify_paper_hash never called
# ---------------------------------------------------------------------------
def test_stub_backend_retrieval_succeeds_unchanged(client, admin_principal, exam_centre_principal):
    """
    Uses the REAL, unmocked StubBlockchainService (the test environment's
    default BLOCKCHAIN_BACKEND). Proves retrieval behaves EXACTLY as it
    did before Phase 5E: 200 + byte-exact PDF, no 501 anywhere.
    """
    paper_id = _register_and_authorize(client, admin_principal, exam_centre_principal)
    response = _retrieve(client, exam_centre_principal, paper_id)
    assert response.status_code == 200
    assert response.content == SAMPLE_PDF_BYTES


def test_stub_backend_has_ledger_verification_capability_disabled():
    """
    The capability flag paper_service.py's retrieval logic checks BEFORE
    ever calling verify_paper_hash() (blockchain_service.py's
    `supports_ledger_verification`) is False for StubBlockchainService
    and True only for FabricBlockchainService — asserted directly here
    against the real classes, independent of any monkeypatching.
    """
    from app.services.fabric_blockchain_service import FabricBlockchainService

    assert StubBlockchainService().supports_ledger_verification is False
    assert (
        FabricBlockchainService(base_url="http://127.0.0.1:8081").supports_ledger_verification
        is True
    )


def test_stub_backend_verify_paper_hash_is_never_called(
    client, admin_principal, exam_centre_principal, monkeypatch
):
    """
    Spies on the REAL StubBlockchainService's verify_paper_hash to prove
    paper_service never even ATTEMPTS the call for a backend whose
    supports_ledger_verification flag is False — this is a genuine
    "never called" guarantee (a capability check before the call), not
    "called and its exception is caught every time".
    """
    call_count = {"n": 0}
    original = StubBlockchainService.verify_paper_hash  # the inherited base-class default

    def _spy(self, paper_id, candidate_hash):
        call_count["n"] += 1
        return original(self, paper_id, candidate_hash)

    # Patching the method itself would be moot if it's never even
    # reached — this spy exists purely to make "never called" an
    # observable, failing-loudly assertion rather than an assumption.
    monkeypatch.setattr(StubBlockchainService, "verify_paper_hash", _spy)

    paper_id = _register_and_authorize(client, admin_principal, exam_centre_principal)
    response = _retrieve(client, exam_centre_principal, paper_id)

    assert response.status_code == 200
    assert response.content == SAMPLE_PDF_BYTES
    assert call_count["n"] == 0


# ---------------------------------------------------------------------------
# 3 & 4. Existing local SHA-256 success / mismatch behaviour is unaffected
# ---------------------------------------------------------------------------
def test_local_integrity_success_path_unaffected_by_phase_5e(client, admin_principal, exam_centre_principal):
    paper_id = _register_and_authorize(client, admin_principal, exam_centre_principal)
    response = _retrieve(client, exam_centre_principal, paper_id)
    assert response.status_code == 200
    assert response.content == SAMPLE_PDF_BYTES


def test_local_sha256_mismatch_still_returns_409_and_never_reaches_blockchain_check(
    client, db_session, admin_principal, exam_centre_principal, monkeypatch
):
    """
    If the recomputed local SHA-256 disagrees with paper.sha256_hash
    (kept reachable today only via direct DB manipulation, since the
    normal pipeline always keeps them consistent — matching the
    existing "should be unreachable" comment in paper_service.py), the
    request must still be rejected with 409 BEFORE any blockchain call
    is attempted.
    """
    fake = _FakeVerifyingBlockchainService(match=True)
    monkeypatch.setattr("app.services.paper_service.get_blockchain_service", lambda: fake)

    paper_id = _register_and_authorize(client, admin_principal, exam_centre_principal)
    paper = db_session.get(Paper, uuid.UUID(paper_id))
    paper.sha256_hash = "0" * 64  # deliberately wrong
    db_session.commit()

    response = _retrieve(client, exam_centre_principal, paper_id)
    assert response.status_code == 409
    assert len(fake.calls) == 0  # local gate rejected first — blockchain never consulted


# ---------------------------------------------------------------------------
# 5. AES-GCM tampering still rejects BEFORE blockchain verification
# ---------------------------------------------------------------------------
def test_aes_gcm_tamper_detection_rejects_before_blockchain_verification(
    client, db_session, admin_principal, exam_centre_principal, monkeypatch
):
    import os

    fake = _FakeVerifyingBlockchainService(match=True)
    monkeypatch.setattr("app.services.paper_service.get_blockchain_service", lambda: fake)

    paper_id = _register_and_authorize(client, admin_principal, exam_centre_principal)
    paper = db_session.get(Paper, uuid.UUID(paper_id))
    storage_path = os.path.join(os.environ["STORAGE_LOCAL_PATH"], paper.file_reference)
    with open(storage_path, "r+b") as f:
        f.seek(0)
        first_byte = f.read(1)
        f.seek(0)
        f.write(bytes([first_byte[0] ^ 0xFF]))

    response = _retrieve(client, exam_centre_principal, paper_id)
    assert response.status_code == 409
    assert len(fake.calls) == 0  # AES-GCM auth-tag gate rejected first, before decryption ever succeeded


# ---------------------------------------------------------------------------
# 6, 7, 15. Fabric called with exact paper_id + exact recomputed hash; match=True succeeds
# ---------------------------------------------------------------------------
def test_fabric_backend_called_with_exact_paper_id_and_hash_match_true_succeeds(
    client, admin_principal, exam_centre_principal, monkeypatch
):
    fake = _FakeVerifyingBlockchainService(match=True)
    monkeypatch.setattr("app.services.paper_service.get_blockchain_service", lambda: fake)

    paper_id = _register_and_authorize(client, admin_principal, exam_centre_principal)
    response = _retrieve(client, exam_centre_principal, paper_id)

    assert response.status_code == 200
    assert response.content == SAMPLE_PDF_BYTES

    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert str(call["paper_id"]) == paper_id
    assert call["candidate_hash"] == _sha256_of_sample_pdf()

    # --- 15. Only paper_id and hash are passed — no other keys at all ---
    assert set(call.keys()) == {"paper_id", "candidate_hash"}
    call_text = str(call)
    for forbidden in ("wrapped_dek", "file_nonce", "%PDF", "master_key", "otp", "jwt", "password"):
        assert forbidden not in call_text.lower()


# ---------------------------------------------------------------------------
# 8, 9, 10. Fabric match=False -> 409 + LEDGER_HASH_MISMATCH + TAMPER_DETECTED/REJECTED
# ---------------------------------------------------------------------------
def test_fabric_match_false_rejects_with_409_and_records_expected_events(
    client, db_session, admin_principal, exam_centre_principal, monkeypatch
):
    fake = _FakeVerifyingBlockchainService(match=False)
    monkeypatch.setattr("app.services.paper_service.get_blockchain_service", lambda: fake)

    paper_id = _register_and_authorize(client, admin_principal, exam_centre_principal)
    response = _retrieve(client, exam_centre_principal, paper_id)

    assert response.status_code == 409
    assert "blockchain-backed integrity verification" in response.json()["error"]["message"].lower()

    pid = uuid.UUID(paper_id)
    security_events = (
        db_session.query(SecurityEvent)
        .filter(SecurityEvent.paper_id == pid, SecurityEvent.event_type == "LEDGER_HASH_MISMATCH")
        .all()
    )
    assert len(security_events) == 1
    assert security_events[0].severity == "HIGH"

    audit_events = (
        db_session.query(AuditEvent)
        .filter(
            AuditEvent.paper_id == pid,
            AuditEvent.event_type == "TAMPER_DETECTED",
            AuditEvent.outcome == "REJECTED",
        )
        .all()
    )
    assert len(audit_events) == 1

    # No PAPER_RELEASED/SUCCESS event was ever recorded for this paper.
    released = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.paper_id == pid, AuditEvent.event_type == "PAPER_RELEASED")
        .all()
    )
    assert released == []


def test_fabric_match_false_response_body_never_contains_pdf_bytes(
    client, admin_principal, exam_centre_principal, monkeypatch
):
    fake = _FakeVerifyingBlockchainService(match=False)
    monkeypatch.setattr("app.services.paper_service.get_blockchain_service", lambda: fake)

    paper_id = _register_and_authorize(client, admin_principal, exam_centre_principal)
    response = _retrieve(client, exam_centre_principal, paper_id)

    assert response.status_code == 409
    assert SAMPLE_PDF_BYTES not in response.content


# ---------------------------------------------------------------------------
# 11, 12. Fabric unavailable + best_effort (default) -> succeeds, DEGRADED recorded
# ---------------------------------------------------------------------------
def test_fabric_unavailable_best_effort_default_succeeds_with_degraded_event(
    client, db_session, admin_principal, exam_centre_principal, monkeypatch
):
    """No FABRIC_VERIFICATION_MODE override here at all — proves
    "best_effort" really is the default (app/config.py), not something
    a test has to opt into."""
    from app.config import get_settings

    assert get_settings().FABRIC_VERIFICATION_MODE == "best_effort"

    fake = _FakeUnavailableBlockchainService()
    monkeypatch.setattr("app.services.paper_service.get_blockchain_service", lambda: fake)

    paper_id = _register_and_authorize(client, admin_principal, exam_centre_principal)
    response = _retrieve(client, exam_centre_principal, paper_id)

    assert response.status_code == 200
    assert response.content == SAMPLE_PDF_BYTES
    assert len(fake.calls) == 1

    pid = uuid.UUID(paper_id)
    degraded_events = (
        db_session.query(AuditEvent)
        .filter(
            AuditEvent.paper_id == pid,
            AuditEvent.event_type == "BLOCKCHAIN_VERIFICATION_UNAVAILABLE",
            AuditEvent.outcome == "DEGRADED",
        )
        .all()
    )
    assert len(degraded_events) == 1

    # Retrieval still completed successfully end-to-end.
    released = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.paper_id == pid, AuditEvent.event_type == "PAPER_RELEASED", AuditEvent.outcome == "SUCCESS")
        .all()
    )
    assert len(released) == 1


def test_fabric_paper_not_registered_on_ledger_is_treated_as_unavailable_under_best_effort(
    client, admin_principal, exam_centre_principal, monkeypatch
):
    """
    NotFoundException (the ledger has no record for this paper_id at
    all — a real, legitimate possibility today, since Phase 5D's own
    registration-time ledger write is itself best-effort and can fail)
    is treated the same as an availability failure, NOT as a positive
    tamper signal — see paper_service.py's
    _verify_against_blockchain_ledger docstring, Branch 2.
    """
    fake = _FakeUnavailableBlockchainService(exc=NotFoundException("paper_id not found on the ledger (simulated)."))
    monkeypatch.setattr("app.services.paper_service.get_blockchain_service", lambda: fake)

    paper_id = _register_and_authorize(client, admin_principal, exam_centre_principal)
    response = _retrieve(client, exam_centre_principal, paper_id)
    assert response.status_code == 200
    assert response.content == SAMPLE_PDF_BYTES


# ---------------------------------------------------------------------------
# 13. Fabric unavailable + strict -> 503
# ---------------------------------------------------------------------------
def test_fabric_unavailable_strict_mode_rejects_with_503(
    client, db_session, admin_principal, exam_centre_principal, monkeypatch
):
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("FABRIC_VERIFICATION_MODE", "strict")
    get_settings.cache_clear()
    try:
        fake = _FakeUnavailableBlockchainService()
        monkeypatch.setattr("app.services.paper_service.get_blockchain_service", lambda: fake)

        paper_id = _register_and_authorize(client, admin_principal, exam_centre_principal)
        response = _retrieve(client, exam_centre_principal, paper_id)

        assert response.status_code == 503
        assert "unavailable" in response.json()["error"]["message"].lower()

        pid = uuid.UUID(paper_id)
        failure_events = (
            db_session.query(AuditEvent)
            .filter(
                AuditEvent.paper_id == pid,
                AuditEvent.event_type == "BLOCKCHAIN_VERIFICATION_UNAVAILABLE",
                AuditEvent.outcome == "FAILURE",
            )
            .all()
        )
        assert len(failure_events) == 1

        # No PDF content was ever returned.
        assert SAMPLE_PDF_BYTES not in response.content
    finally:
        # Restore the process-wide cached settings singleton so this test
        # cannot leak "strict" into any other test in the suite regardless
        # of run order (same discipline as test_fabric_blockchain_service.py's
        # factory-selection tests).
        get_settings.cache_clear()


def test_fabric_match_false_always_wins_over_strict_mode_too(
    client, admin_principal, exam_centre_principal, monkeypatch
):
    """
    Confirms the instruction "a genuine match=False must NEVER be
    swallowed" holds in BOTH modes, not just best_effort — i.e. strict
    mode does not accidentally change how an explicit mismatch (as
    opposed to an availability failure) is handled.
    """
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("FABRIC_VERIFICATION_MODE", "strict")
    get_settings.cache_clear()
    try:
        fake = _FakeVerifyingBlockchainService(match=False)
        monkeypatch.setattr("app.services.paper_service.get_blockchain_service", lambda: fake)

        paper_id = _register_and_authorize(client, admin_principal, exam_centre_principal)
        response = _retrieve(client, exam_centre_principal, paper_id)

        assert response.status_code == 409  # NOT 503 — a real mismatch, not an availability issue
    finally:
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# 14. Unsupported backend/capability never surfaces a 501 to the client
# ---------------------------------------------------------------------------
def test_unsupported_backend_never_surfaces_501_to_client(
    client, admin_principal, exam_centre_principal, monkeypatch
):
    fake = _FakeUnsupportedBlockchainService()
    monkeypatch.setattr("app.services.paper_service.get_blockchain_service", lambda: fake)

    paper_id = _register_and_authorize(client, admin_principal, exam_centre_principal)
    response = _retrieve(client, exam_centre_principal, paper_id)

    assert response.status_code == 200
    assert response.content == SAMPLE_PDF_BYTES
    assert len(fake.calls) == 1  # the call WAS attempted (unlike the real Stub, which never overrides
    # the method at all) — this fake proves that even when the ATTEMPT is
    # made and UnsupportedOperationException genuinely comes back, it is
    # still handled gracefully and never reaches the HTTP layer as a 501.


# ---------------------------------------------------------------------------
# Unexpected exception types are NOT silently swallowed by best_effort
# ---------------------------------------------------------------------------
def test_unexpected_exception_type_is_not_swallowed_by_best_effort_policy(
    client, admin_principal, exam_centre_principal, monkeypatch
):
    """
    Per the explicit instruction "do not catch every exception and
    silently continue" — only ServiceUnavailableException and
    NotFoundException are treated as "verification unobtainable".
    Anything else (here, a ValidationFailedException that would
    indicate a genuine bug in how the request was built) must propagate
    as its own distinct error, not be reinterpreted as
    BLOCKCHAIN_VERIFICATION_UNAVAILABLE.
    """
    fake = _FakeUnexpectedErrorBlockchainService(
        ValidationFailedException("simulated: malformed request (should never happen in practice).")
    )
    monkeypatch.setattr("app.services.paper_service.get_blockchain_service", lambda: fake)

    paper_id = _register_and_authorize(client, admin_principal, exam_centre_principal)
    response = _retrieve(client, exam_centre_principal, paper_id)

    # Propagates as its own AppException (400), NOT swallowed into a 200
    # and NOT reinterpreted as a 503/DEGRADED best-effort case.
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------
def test_invalid_fabric_verification_mode_is_rejected_at_settings_construction():
    import pydantic

    from app.config import Settings

    with pytest.raises(pydantic.ValidationError):
        Settings(
            DATABASE_URL="sqlite:///:memory:",
            JWT_SECRET_KEY="test",
            FABRIC_VERIFICATION_MODE="not_a_real_mode",
        )


# ---------------------------------------------------------------------------
# 16-19. Authentication / OTP / RBAC / time-lock remain unaffected (smoke checks;
# full coverage already exists in test_phase2_manual.py, test_time_lock.py)
# ---------------------------------------------------------------------------
def test_examination_centre_role_still_required_for_retrieve(client, admin_principal):
    """RBAC unaffected: Admin still cannot call the retrieve endpoint."""
    files = {"file": ("sample.pdf", SAMPLE_PDF_BYTES, "application/pdf")}
    data = {"subject": "RBAC Smoke Test", "release_timestamp": "2020-01-01T00:00:00Z"}
    reg = client.post("/api/v1/papers/register", data=data, files=files, headers=auth_header(admin_principal))
    paper_id = reg.json()["paper_id"]

    response = client.get(f"/api/v1/papers/{paper_id}/retrieve", headers=auth_header(admin_principal))
    assert response.status_code == 403


def test_time_lock_still_enforced_ahead_of_any_blockchain_check(
    client, admin_principal, exam_centre_principal, monkeypatch
):
    """A future-dated paper is still denied at the time-lock gate — the
    blockchain fake here would raise loudly (AssertionError via pytest.fail)
    if it were ever reached, proving time-lock still runs first."""
    from datetime import datetime, timedelta, timezone

    class _ExplodingIfCalled:
        def verify_paper_hash(self, paper_id, candidate_hash):
            pytest.fail("verify_paper_hash() must not be called before the time-lock check passes.")

    monkeypatch.setattr("app.services.paper_service.get_blockchain_service", lambda: _ExplodingIfCalled())

    future = (datetime.now(timezone.utc) + timedelta(days=365)).isoformat()
    files = {"file": ("sample.pdf", SAMPLE_PDF_BYTES, "application/pdf")}
    data = {"subject": "Time-Lock Smoke Test", "release_timestamp": future}
    reg = client.post("/api/v1/papers/register", data=data, files=files, headers=auth_header(admin_principal))
    paper_id = reg.json()["paper_id"]
    client.post(
        f"/api/v1/papers/{paper_id}/authorize",
        json={"centre_id": str(exam_centre_principal.centre_id)},
        headers=auth_header(admin_principal),
    )

    response = _retrieve(client, exam_centre_principal, paper_id)
    assert response.status_code == 403
    assert "not yet available" in response.json()["error"]["message"].lower()


# ---------------------------------------------------------------------------
# 20. Existing registration behaviour remains unaffected by Phase 5E
# ---------------------------------------------------------------------------
def test_registration_endpoint_completely_unaffected_by_phase_5e(client, admin_principal):
    """Phase 5E touches ONLY retrieve_paper() — register_paper() (Phase 5D)
    is untouched. Smoke check; full coverage remains in
    test_paper_blockchain_integration.py."""
    files = {"file": ("sample.pdf", SAMPLE_PDF_BYTES, "application/pdf")}
    data = {"subject": "Registration Unaffected Check", "release_timestamp": "2020-01-01T00:00:00Z"}
    response = client.post("/api/v1/papers/register", data=data, files=files, headers=auth_header(admin_principal))
    assert response.status_code == 201, response.text
    assert response.json()["ledger_tx_reference"] is not None  # unchanged Phase 5D stub behaviour


# ---------------------------------------------------------------------------
# Log-safety check (matches the discipline already applied to Phase 5D's logging)
# ---------------------------------------------------------------------------
def test_blockchain_unavailable_warning_log_never_leaks_secrets(
    client, admin_principal, exam_centre_principal, monkeypatch, caplog
):
    fake = _FakeUnavailableBlockchainService()
    monkeypatch.setattr("app.services.paper_service.get_blockchain_service", lambda: fake)

    paper_id = _register_and_authorize(client, admin_principal, exam_centre_principal)
    with caplog.at_level(logging.DEBUG):
        response = _retrieve(client, exam_centre_principal, paper_id)
    assert response.status_code == 200

    log_text = caplog.text
    assert SAMPLE_PDF_BYTES.decode("latin-1") not in log_text
    for forbidden in ("wrapped_dek", "file_nonce", "master_key"):
        assert forbidden not in log_text.lower()
    assert "could not be completed" in log_text.lower()
