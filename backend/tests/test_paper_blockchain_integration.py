"""
Phase 5D integration/regression tests: paper_service.register_paper()'s
best-effort blockchain (Hyperledger Fabric) ledger write.

Scope and design note: the HTTP wire-protocol correctness of
FabricBlockchainService itself (request shapes, error mapping, the 6
unsupported operations, the backend-selection factory) is already
exhaustively covered by tests/test_fabric_blockchain_service.py (29
tests, httpx.MockTransport-based) and is NOT re-tested here. This file
instead tests the NEW orchestration logic added to paper_service.py in
Phase 5D: does register_paper() call the configured blockchain backend
at the right time, does it persist a successful transaction reference,
and — most importantly — does it tolerate blockchain failure/
unavailability WITHOUT failing an otherwise-successful PostgreSQL +
storage registration?

To isolate this orchestration logic from the HTTP layer, these tests
monkeypatch `app.services.paper_service.get_blockchain_service`
directly (the name as imported into paper_service.py) with small fake
BlockchainService-like callables — a standard "patch where it's used"
seam, not a live or even HTTP-mocked Fabric adapter. This is
deliberate: it proves paper_service's own logic is correct regardless
of which concrete backend is selected, without duplicating
test_fabric_blockchain_service.py's already-thorough HTTP-layer
coverage.

Every test here goes through the REAL FastAPI app, REAL RBAC, REAL
authentication, and a REAL (SQLite, file-based) database — same
conventions as test_paper_api.py — so this also serves as an
end-to-end regression check for the paper-registration endpoint,
including under the STUB backend which is exercised UNMOCKED (real
StubBlockchainService) in test 1 below.

Live Fabric network / live Gateway Adapter process: NOT used anywhere
in this file. No claim of live Fabric verification is made by any test
here — see PROJECT_STATE.md Phase 5D section for what live/manual
verification (if any) was actually performed this session.
"""

import hashlib
import uuid

import pytest

from app.exceptions.base import ServiceUnavailableException
from app.models.paper import Paper
from tests.conftest import SAMPLE_PDF_BYTES, auth_header


def _register_sample_paper(client, admin_principal, subject="Blockchain Integration Test", release_timestamp="2020-01-01T00:00:00Z"):
    """Same pattern as test_paper_api.py's helper — past release_timestamp
    by default since these tests are not about time-lock (test_time_lock.py
    covers that)."""
    files = {"file": ("sample.pdf", SAMPLE_PDF_BYTES, "application/pdf")}
    data = {"subject": subject, "release_timestamp": release_timestamp}
    return client.post(
        "/api/v1/papers/register", data=data, files=files, headers=auth_header(admin_principal)
    )


class _FakeSucceedingBlockchainService:
    """Minimal stand-in for a BlockchainService whose register_paper()
    call succeeds, returning a deliberately non-stub-shaped transaction
    id so a test can unambiguously prove THIS fake (not the real
    StubBlockchainService) is what produced the value."""

    def __init__(self, tx_id: str = "fabric-tx-mocked-0001"):
        self.tx_id = tx_id
        self.calls: list[dict] = []

    def register_paper(self, paper_id, sha256_hash, release_timestamp, metadata):
        self.calls.append(
            {
                "paper_id": paper_id,
                "sha256_hash": sha256_hash,
                "release_timestamp": release_timestamp,
                "metadata": metadata,
            }
        )
        return self.tx_id


class _FakeFailingBlockchainService:
    """Minimal stand-in for a BlockchainService whose register_paper()
    call always fails, simulating an unreachable/misconfigured Fabric
    Gateway Adapter (the real FabricBlockchainService would raise
    ServiceUnavailableException in exactly this situation — see
    fabric_blockchain_service.py's _post/_get error mapping)."""

    def __init__(self):
        self.calls: list[dict] = []

    def register_paper(self, paper_id, sha256_hash, release_timestamp, metadata):
        self.calls.append({"paper_id": paper_id})
        raise ServiceUnavailableException(
            "Could not reach the Fabric Gateway Adapter (simulated failure for this test)."
        )


# --- 1. Stub backend registration remains successful (REAL StubBlockchainService, unmocked) ---
def test_stub_backend_registration_succeeds_and_populates_ledger_tx_reference(
    client, db_session, admin_principal
):
    """
    Regression + new-behavior check in one: the test environment's
    default BLOCKCHAIN_BACKEND is "stub" (conftest.py), and this test
    does NOT monkeypatch get_blockchain_service — so this exercises
    the REAL StubBlockchainService.register_paper() call added to
    paper_service.py in Phase 5D. Proves the stub path (a) still
    succeeds (no regression) and (b) now legitimately populates
    ledger_tx_reference via the SAME get_blockchain_service()
    abstraction used everywhere else in the app (not special-cased for
    Fabric).
    """
    response = _register_sample_paper(client, admin_principal)
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["ledger_tx_reference"] is not None
    assert body["ledger_tx_reference"].startswith("stub-tx-")

    paper = db_session.get(Paper, uuid.UUID(body["paper_id"]))
    assert paper is not None
    assert paper.ledger_tx_reference == body["ledger_tx_reference"]


# --- 2. Fabric backend (mocked) + successful registration ---
def test_fabric_backend_successful_registration_persists_transaction_id(
    client, db_session, admin_principal, monkeypatch
):
    fake = _FakeSucceedingBlockchainService(tx_id="fabric-tx-mocked-0001")
    monkeypatch.setattr("app.services.paper_service.get_blockchain_service", lambda: fake)

    response = _register_sample_paper(client, admin_principal, subject="Fabric Success Test")
    assert response.status_code == 201, response.text
    body = response.json()

    # --- 7. API response correctly exposes ledger_tx_reference when available ---
    assert body["ledger_tx_reference"] == "fabric-tx-mocked-0001"

    # --- 4. Successful registration persists the returned ledger reference ---
    paper = db_session.get(Paper, uuid.UUID(body["paper_id"]))
    assert paper is not None
    assert paper.ledger_tx_reference == "fabric-tx-mocked-0001"

    # Confirm the fake was actually called with the right, non-secret data
    # (paper_id/hash/timestamp/metadata) — and nothing resembling key
    # material or PDF content.
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["paper_id"] == paper.paper_id
    assert call["sha256_hash"] == hashlib.sha256(SAMPLE_PDF_BYTES).hexdigest()
    assert call["metadata"]["subject"] == "Fabric Success Test"
    assert call["metadata"]["encryption_algorithm"] == "AES-256-GCM"
    assert "admin_id" in call["metadata"]
    # Never sent: PDF bytes, AES key, wrapped DEK, nonce, password, OTP, JWT.
    call_text = str(call)
    for forbidden in ("wrapped_dek", "file_nonce", "%PDF", "master_key"):
        assert forbidden not in call_text


# --- 3. Fabric backend + unavailable/failing adapter ---
def test_fabric_backend_unavailable_does_not_fail_registration(
    client, db_session, admin_principal, monkeypatch
):
    fake = _FakeFailingBlockchainService()
    monkeypatch.setattr("app.services.paper_service.get_blockchain_service", lambda: fake)

    response = _register_sample_paper(client, admin_principal, subject="Fabric Failure Test")

    # PostgreSQL registration remains successful per the approved
    # best-effort design — NOT a 500, NOT a 503; the client sees a
    # completely normal, successful registration.
    assert response.status_code == 201, response.text
    body = response.json()

    # --- 8. API response returns null when Fabric registration did not produce a reference ---
    assert body["ledger_tx_reference"] is None

    paper = db_session.get(Paper, uuid.UUID(body["paper_id"]))
    assert paper is not None
    assert paper.ledger_tx_reference is None
    # The rest of the paper's data is completely intact — the failure did
    # not corrupt or partially-write the row.
    assert paper.sha256_hash == hashlib.sha256(SAMPLE_PDF_BYTES).hexdigest()
    assert paper.subject == "Fabric Failure Test"
    assert paper.status == "registered"

    assert len(fake.calls) == 1  # the call was attempted exactly once, not retried/looped


def test_fabric_backend_unavailable_via_generic_exception_still_does_not_fail_registration(
    client, db_session, admin_principal, monkeypatch
):
    """
    Same as the test above, but with a generic (non-AppException)
    exception — e.g. a raw httpx.ConnectError-style failure that
    somehow escaped FabricBlockchainService's own mapping, or any other
    unexpected error from a future/alternate BlockchainService
    implementation. paper_service.py's except clause is deliberately
    broad (Exception, not AppException) specifically to cover this
    case — confirmed here rather than assumed.
    """

    class _FakeExplodingBlockchainService:
        def register_paper(self, *args, **kwargs):
            raise RuntimeError("simulated unexpected low-level failure")

    monkeypatch.setattr(
        "app.services.paper_service.get_blockchain_service", lambda: _FakeExplodingBlockchainService()
    )

    response = _register_sample_paper(client, admin_principal, subject="Generic Exception Test")
    assert response.status_code == 201, response.text
    assert response.json()["ledger_tx_reference"] is None


# --- 6. Duplicate paper behavior remains correct ---
def test_two_registrations_get_distinct_paper_ids_and_distinct_ledger_references(
    client, db_session, admin_principal
):
    """
    Uses the REAL (unmocked) StubBlockchainService, whose in-memory
    ledger genuinely rejects a re-used paper_id (ValueError) — see
    StubBlockchainService.register_paper() in blockchain_service.py.
    Each POST generates a fresh, server-side UUID paper_id (Paper()'s
    uuid_pk default), so two ordinary registrations must never collide
    on that ledger, proving Phase 5D's wiring did not introduce any
    accidental paper_id reuse or duplicate-suppression behavior.
    """
    first = _register_sample_paper(client, admin_principal, subject="Duplicate Check A")
    second = _register_sample_paper(client, admin_principal, subject="Duplicate Check B")

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text

    first_body, second_body = first.json(), second.json()
    assert first_body["paper_id"] != second_body["paper_id"]
    assert first_body["ledger_tx_reference"] != second_body["ledger_tx_reference"]
    assert first_body["ledger_tx_reference"] is not None
    assert second_body["ledger_tx_reference"] is not None


# --- 5. Existing paper registration tests remain passing (explicit smoke check here too) ---
def test_registration_response_schema_still_only_exposes_safe_fields(client, admin_principal):
    """
    Companion to test_paper_api.py's own
    test_register_response_schema_only_exposes_safe_fields — re-asserted
    here specifically WITH a populated ledger_tx_reference (the other
    file's version always sees ledger_tx_reference=None, since it never
    exercised the Phase 5D code path). Confirms no new field leaked into
    the response beyond what was already allowed.
    """
    response = _register_sample_paper(client, admin_principal, subject="Schema Check")
    assert response.status_code == 201, response.text
    body = response.json()
    allowed_keys = {
        "paper_id", "subject", "status", "sha256_hash", "encryption_algorithm",
        "release_timestamp", "created_at", "ledger_tx_reference",
        "lock_status",  # Phase 6H: computed release state; not a secret
    }
    assert set(body.keys()) <= allowed_keys
    assert body["ledger_tx_reference"] is not None  # stub backend — real value this time


def test_fabric_failure_is_logged_without_leaking_secrets(
    client, admin_principal, monkeypatch, caplog
):
    """Log-safety check for the new warning log line in paper_service.py —
    same discipline test_paper_api.py already applies to the register
    endpoint's own logging."""
    import logging

    fake = _FakeFailingBlockchainService()
    monkeypatch.setattr("app.services.paper_service.get_blockchain_service", lambda: fake)

    with caplog.at_level(logging.DEBUG):
        response = _register_sample_paper(client, admin_principal, subject="Log Safety Test")
    assert response.status_code == 201, response.text

    log_text = caplog.text
    assert SAMPLE_PDF_BYTES.decode("latin-1") not in log_text
    for forbidden in ("wrapped_dek", "file_nonce", "master_key"):
        assert forbidden not in log_text.lower()
    # The warning line itself should be present and should reference the
    # paper_id (useful for operators) without any secret material.
    assert "Blockchain registration failed" in log_text
