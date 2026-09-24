"""
Integration tests for the Phase 3 paper lifecycle API
(POST /papers/register, GET /papers/{id}, POST /papers/{id}/authorize,
GET /papers/{id}/retrieve, GET /papers/{id}/status).

Every test goes through the REAL FastAPI app, REAL RBAC, REAL
authentication (via conftest.py's admin_principal/exam_centre_principal
fixtures, which drive the actual /auth/login + /auth/otp/verify
endpoints), a REAL (SQLite, file-based) database, and the REAL
crypto_service/storage_service — nothing here is mocked except OTP
delivery capture (see conftest.py's docstring for why that one
exception is necessary and safe).

Covers Phase 3 test requirements 8-15.
"""

import hashlib
import os
import uuid

from app.models.audit_event import AuditEvent
from app.models.paper import Paper
from tests.conftest import SAMPLE_PDF_BYTES, auth_header


def _register_sample_paper(client, admin_principal, subject="Data Structures 2026", release_timestamp="2020-01-01T00:00:00Z"):
    """
    Default release_timestamp is deliberately in the PAST: most of this
    file's tests are about authorization/integrity, not time-lock, and
    were written (Phase 3) before time-lock enforcement existed (Phase
    4). Using a past timestamp by default keeps those tests focused on
    what they actually test. Phase 4's own time-lock tests
    (test_time_lock.py) explicitly pass future/boundary timestamps.
    """
    files = {"file": ("sample.pdf", SAMPLE_PDF_BYTES, "application/pdf")}
    data = {"subject": subject, "release_timestamp": release_timestamp}
    response = client.post(
        "/api/v1/papers/register", data=data, files=files, headers=auth_header(admin_principal)
    )
    return response


# --- 10. Paper metadata is persisted / 8. Stored encrypted file exists ---
def test_register_paper_success_persists_metadata_and_encrypted_file(
    client, db_session, admin_principal
):
    response = _register_sample_paper(client, admin_principal)
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["subject"] == "Data Structures 2026"
    assert body["status"] == "registered"
    assert body["encryption_algorithm"] == "AES-256-GCM"
    assert body["sha256_hash"] == hashlib.sha256(SAMPLE_PDF_BYTES).hexdigest()

    paper = db_session.get(Paper, uuid.UUID(body["paper_id"]))
    assert paper is not None
    assert paper.sha256_hash == hashlib.sha256(SAMPLE_PDF_BYTES).hexdigest()
    assert paper.file_reference.endswith(".enc")

    # requirement 8: the encrypted file genuinely exists on disk
    storage_path = os.path.join(os.environ["STORAGE_LOCAL_PATH"], paper.file_reference)
    assert os.path.exists(storage_path)

    # the file on disk must be CIPHERTEXT, never the original plaintext
    with open(storage_path, "rb") as f:
        on_disk_bytes = f.read()
    assert on_disk_bytes != SAMPLE_PDF_BYTES
    assert SAMPLE_PDF_BYTES not in on_disk_bytes


# --- 9. Plaintext PDF is not permanently stored ---
def test_plaintext_pdf_never_appears_anywhere_in_storage_directory(client, admin_principal):
    _register_sample_paper(client, admin_principal)

    storage_dir = os.environ["STORAGE_LOCAL_PATH"]
    for root, _dirs, filenames in os.walk(storage_dir):
        for name in filenames:
            with open(os.path.join(root, name), "rb") as f:
                content = f.read()
            assert SAMPLE_PDF_BYTES not in content, (
                f"Plaintext PDF bytes found in {name} — plaintext must never be persisted."
            )


# --- 11. Unauthorized user cannot register a paper ---
def test_examination_centre_cannot_register_paper(client, exam_centre_principal):
    response = _register_sample_paper(client, exam_centre_principal)
    assert response.status_code == 403


def test_unauthenticated_request_cannot_register_paper(client):
    files = {"file": ("sample.pdf", SAMPLE_PDF_BYTES, "application/pdf")}
    data = {"subject": "No Auth Test", "release_timestamp": "2026-12-31T09:00:00Z"}
    response = client.post("/api/v1/papers/register", data=data, files=files)
    assert response.status_code == 401


# --- 12. Invalid file is rejected ---
def test_non_pdf_file_is_rejected(client, admin_principal):
    files = {"file": ("notes.txt", b"this is not a pdf at all", "text/plain")}
    data = {"subject": "Bad Upload Test", "release_timestamp": "2026-12-31T09:00:00Z"}
    response = client.post(
        "/api/v1/papers/register", data=data, files=files, headers=auth_header(admin_principal)
    )
    assert response.status_code == 400


def test_empty_file_is_rejected(client, admin_principal):
    files = {"file": ("empty.pdf", b"", "application/pdf")}
    data = {"subject": "Empty Upload Test", "release_timestamp": "2026-12-31T09:00:00Z"}
    response = client.post(
        "/api/v1/papers/register", data=data, files=files, headers=auth_header(admin_principal)
    )
    assert response.status_code == 400


# --- 13. Audit event is created ---
def test_registration_creates_audit_events(client, db_session, admin_principal):
    response = _register_sample_paper(client, admin_principal)
    paper_id = uuid.UUID(response.json()["paper_id"])

    events = db_session.query(AuditEvent).filter(AuditEvent.paper_id == paper_id).all()
    event_types = {e.event_type for e in events}
    assert "PAPER_REGISTRATION_COMPLETED" in event_types


def test_retrieval_creates_audit_events(client, db_session, admin_principal, exam_centre_principal):
    reg_response = _register_sample_paper(client, admin_principal)
    paper_id = reg_response.json()["paper_id"]

    client.post(
        f"/api/v1/papers/{paper_id}/authorize",
        json={"centre_id": str(exam_centre_principal.centre_id)},
        headers=auth_header(admin_principal),
    )
    retrieve_response = client.get(
        f"/api/v1/papers/{paper_id}/retrieve", headers=auth_header(exam_centre_principal)
    )
    assert retrieve_response.status_code == 200
    assert retrieve_response.content == SAMPLE_PDF_BYTES  # correct decryption end-to-end

    events = db_session.query(AuditEvent).filter(AuditEvent.paper_id == uuid.UUID(paper_id)).all()
    event_types = {e.event_type for e in events}
    assert "PAPER_RELEASED" in event_types
    assert "PAPER_ACCESS_ATTEMPT" in event_types


def test_retrieval_denied_for_unauthorized_centre(client, admin_principal, exam_centre_principal):
    reg_response = _register_sample_paper(client, admin_principal)
    paper_id = reg_response.json()["paper_id"]
    # deliberately NOT authorizing the centre before retrieving

    retrieve_response = client.get(
        f"/api/v1/papers/{paper_id}/retrieve", headers=auth_header(exam_centre_principal)
    )
    assert retrieve_response.status_code == 403


def test_admin_cannot_call_retrieve_endpoint(client, admin_principal):
    """RBAC (LLD Section 15): retrieval is Examination-Centre-only, even for Admin."""
    reg_response = _register_sample_paper(client, admin_principal)
    paper_id = reg_response.json()["paper_id"]

    response = client.get(f"/api/v1/papers/{paper_id}/retrieve", headers=auth_header(admin_principal))
    assert response.status_code == 403


# --- Tamper detection end-to-end (ties requirements 5/6 into the real API) ---
def test_tampered_stored_file_is_rejected_on_retrieve(
    client, db_session, admin_principal, exam_centre_principal
):
    reg_response = _register_sample_paper(client, admin_principal)
    paper_id = reg_response.json()["paper_id"]

    client.post(
        f"/api/v1/papers/{paper_id}/authorize",
        json={"centre_id": str(exam_centre_principal.centre_id)},
        headers=auth_header(admin_principal),
    )

    # Corrupt the encrypted file on disk directly, simulating tampering
    # after registration but before retrieval.
    paper = db_session.get(Paper, uuid.UUID(paper_id))
    storage_path = os.path.join(os.environ["STORAGE_LOCAL_PATH"], paper.file_reference)
    with open(storage_path, "r+b") as f:
        f.seek(0)
        first_byte = f.read(1)
        f.seek(0)
        f.write(bytes([first_byte[0] ^ 0xFF]))

    retrieve_response = client.get(
        f"/api/v1/papers/{paper_id}/retrieve", headers=auth_header(exam_centre_principal)
    )
    assert retrieve_response.status_code == 409


# --- Authorization endpoint ---
def test_authorize_centre_success(client, db_session, admin_principal, exam_centre_principal):
    reg_response = _register_sample_paper(client, admin_principal)
    paper_id = reg_response.json()["paper_id"]

    response = client.post(
        f"/api/v1/papers/{paper_id}/authorize",
        json={"centre_id": str(exam_centre_principal.centre_id)},
        headers=auth_header(admin_principal),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["paper_id"] == paper_id
    assert body["centre_id"] == str(exam_centre_principal.centre_id)


def test_authorize_centre_requires_admin_role(client, admin_principal, exam_centre_principal):
    reg_response = _register_sample_paper(client, admin_principal)
    paper_id = reg_response.json()["paper_id"]

    response = client.post(
        f"/api/v1/papers/{paper_id}/authorize",
        json={"centre_id": str(exam_centre_principal.centre_id)},
        headers=auth_header(exam_centre_principal),
    )
    assert response.status_code == 403


def test_authorize_unknown_centre_id_rejected(client, admin_principal):
    reg_response = _register_sample_paper(client, admin_principal)
    paper_id = reg_response.json()["paper_id"]

    response = client.post(
        f"/api/v1/papers/{paper_id}/authorize",
        json={"centre_id": str(uuid.uuid4())},
        headers=auth_header(admin_principal),
    )
    assert response.status_code == 400


# --- Status / metadata endpoints ---
def test_paper_status_endpoint(client, admin_principal):
    reg_response = _register_sample_paper(client, admin_principal)
    paper_id = reg_response.json()["paper_id"]

    response = client.get(f"/api/v1/papers/{paper_id}/status", headers=auth_header(admin_principal))
    assert response.status_code == 200
    assert response.json()["status"] == "registered"


def test_get_metadata_unknown_paper_returns_404(client, admin_principal):
    response = client.get(
        f"/api/v1/papers/{uuid.uuid4()}", headers=auth_header(admin_principal)
    )
    assert response.status_code == 404


# --- 15. Secrets are not exposed in API responses ---
def test_register_response_never_contains_key_material(client, admin_principal):
    response = _register_sample_paper(client, admin_principal)
    body_text = response.text.lower()
    for forbidden in ("wrapped_dek", "file_nonce", "master_key", "dek"):
        assert forbidden not in body_text, f"Response leaked internal field: {forbidden}"


def test_register_response_schema_only_exposes_safe_fields(client, admin_principal):
    response = _register_sample_paper(client, admin_principal)
    body = response.json()
    allowed_keys = {
        "paper_id",
        "subject",
        "status",
        "sha256_hash",
        "encryption_algorithm",
        "release_timestamp",
        "created_at",
        "ledger_tx_reference",
    }
    assert set(body.keys()) <= allowed_keys


def test_no_key_material_appears_in_application_logs(client, admin_principal, caplog):
    import logging

    with caplog.at_level(logging.DEBUG):
        response = _register_sample_paper(client, admin_principal, subject="Log Safety Test")
    assert response.status_code == 201
    paper_id = response.json()["paper_id"]

    from app.database import Base  # noqa: F401  (import kept local to avoid unused-import lint noise)

    log_text = caplog.text
    assert SAMPLE_PDF_BYTES.decode("latin-1") not in log_text
    # The wrapped DEK / nonce values themselves must never be logged either.
    assert "wrapped_dek" not in log_text.lower()
