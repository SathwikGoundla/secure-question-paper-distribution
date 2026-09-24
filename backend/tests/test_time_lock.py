"""
Phase 4 tests — time-lock enforcement on GET /papers/{paper_id}/retrieve
(SRS FR-012/FR-016; LLD Section 16).

Uses FROZEN/controlled time via monkeypatching app.services.paper_service's
imported `datetime` name — never real wall-clock sleeps (as required).
"""

import uuid
from datetime import datetime, timedelta, timezone

from app.models.audit_event import AuditEvent
from app.models.security_event import SecurityEvent
from tests.conftest import SAMPLE_PDF_BYTES, auth_header


def _register_paper_with_release_timestamp(client, admin_principal, release_timestamp_iso, subject="Time-Lock Test Paper"):
    files = {"file": ("sample.pdf", SAMPLE_PDF_BYTES, "application/pdf")}
    data = {"subject": subject, "release_timestamp": release_timestamp_iso}
    return client.post(
        "/api/v1/papers/register", data=data, files=files, headers=auth_header(admin_principal)
    )


def _freeze_paper_service_time(monkeypatch, frozen_instant: datetime):
    """
    Monkeypatches the `datetime` name as imported inside
    app.services.paper_service (NOT the global datetime module), so
    `datetime.now(timezone.utc)` inside retrieve_paper() returns exactly
    frozen_instant. This is the standard, dependency-free way to freeze
    time for a single module under test without adding a library like
    freezegun (explicitly avoided per "do not introduce unnecessary
    dependencies").
    """
    import app.services.paper_service as paper_service_module

    class _FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen_instant if tz is not None else frozen_instant.replace(tzinfo=None)

    monkeypatch.setattr(paper_service_module, "datetime", _FrozenDateTime)


def _authorize(client, admin_principal, paper_id, centre_id):
    return client.post(
        f"/api/v1/papers/{paper_id}/authorize",
        json={"centre_id": str(centre_id)},
        headers=auth_header(admin_principal),
    )


# --- 1. Retrieval before release time is rejected ---
def test_retrieval_before_release_time_is_rejected(client, admin_principal, exam_centre_principal):
    future = (datetime.now(timezone.utc) + timedelta(days=365)).isoformat()
    reg = _register_paper_with_release_timestamp(client, admin_principal, future)
    paper_id = reg.json()["paper_id"]
    _authorize(client, admin_principal, paper_id, exam_centre_principal.centre_id)

    response = client.get(f"/api/v1/papers/{paper_id}/retrieve", headers=auth_header(exam_centre_principal))
    assert response.status_code == 403
    assert "not yet available" in response.json()["error"]["message"].lower()


# --- 3. Retrieval after release time is allowed ---
def test_retrieval_after_release_time_is_allowed(client, admin_principal, exam_centre_principal):
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    reg = _register_paper_with_release_timestamp(client, admin_principal, past)
    paper_id = reg.json()["paper_id"]
    _authorize(client, admin_principal, paper_id, exam_centre_principal.centre_id)

    response = client.get(f"/api/v1/papers/{paper_id}/retrieve", headers=auth_header(exam_centre_principal))
    assert response.status_code == 200
    assert response.content == SAMPLE_PDF_BYTES


# --- 2. Retrieval exactly AT release_timestamp is allowed (boundary condition) ---
def test_retrieval_exactly_at_release_timestamp_is_allowed(
    client, db_session, admin_principal, exam_centre_principal, monkeypatch
):
    future = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
    reg = _register_paper_with_release_timestamp(client, admin_principal, future)
    paper_id = reg.json()["paper_id"]
    _authorize(client, admin_principal, paper_id, exam_centre_principal.centre_id)

    # Read back the EXACT persisted release_timestamp (avoids any
    # precision/round-trip mismatch between the ISO string we sent and
    # what the database actually stored) and freeze "now" to that exact
    # instant.
    from app.models.paper import Paper

    paper = db_session.get(Paper, uuid.UUID(paper_id))
    exact_release_instant = paper.release_timestamp
    if exact_release_instant.tzinfo is None:
        exact_release_instant = exact_release_instant.replace(tzinfo=timezone.utc)

    _freeze_paper_service_time(monkeypatch, exact_release_instant)

    response = client.get(f"/api/v1/papers/{paper_id}/retrieve", headers=auth_header(exam_centre_principal))
    assert response.status_code == 200, response.text
    assert response.content == SAMPLE_PDF_BYTES


def test_retrieval_one_second_before_boundary_is_still_denied(
    client, db_session, admin_principal, exam_centre_principal, monkeypatch
):
    """Companion to the boundary test above: one second earlier must still deny."""
    future = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
    reg = _register_paper_with_release_timestamp(client, admin_principal, future)
    paper_id = reg.json()["paper_id"]
    _authorize(client, admin_principal, paper_id, exam_centre_principal.centre_id)

    from app.models.paper import Paper

    paper = db_session.get(Paper, uuid.UUID(paper_id))
    exact_release_instant = paper.release_timestamp
    if exact_release_instant.tzinfo is None:
        exact_release_instant = exact_release_instant.replace(tzinfo=timezone.utc)

    one_second_before = exact_release_instant - timedelta(seconds=1)
    _freeze_paper_service_time(monkeypatch, one_second_before)

    response = client.get(f"/api/v1/papers/{paper_id}/retrieve", headers=auth_header(exam_centre_principal))
    assert response.status_code == 403


# --- 4. PRE_RELEASE_ATTEMPT security event is created / audit event ---
def test_pre_release_attempt_creates_security_and_audit_events(
    client, db_session, admin_principal, exam_centre_principal
):
    future = (datetime.now(timezone.utc) + timedelta(days=365)).isoformat()
    reg = _register_paper_with_release_timestamp(client, admin_principal, future)
    paper_id_str = reg.json()["paper_id"]
    paper_id = uuid.UUID(paper_id_str)
    _authorize(client, admin_principal, paper_id_str, exam_centre_principal.centre_id)

    response = client.get(f"/api/v1/papers/{paper_id_str}/retrieve", headers=auth_header(exam_centre_principal))
    assert response.status_code == 403

    security_events = (
        db_session.query(SecurityEvent)
        .filter(SecurityEvent.paper_id == paper_id, SecurityEvent.event_type == "PRE_RELEASE_ATTEMPT")
        .all()
    )
    assert len(security_events) == 1
    assert security_events[0].actor_id == exam_centre_principal.user_id

    audit_events = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.paper_id == paper_id, AuditEvent.event_type == "PRE_RELEASE_ATTEMPT")
        .all()
    )
    assert len(audit_events) == 1
    assert audit_events[0].outcome == "DENIED"
    assert audit_events[0].actor_id == exam_centre_principal.user_id


# --- 5. Pre-release attempt does not decrypt the paper ---
def test_pre_release_attempt_never_returns_pdf_content(client, admin_principal, exam_centre_principal):
    future = (datetime.now(timezone.utc) + timedelta(days=365)).isoformat()
    reg = _register_paper_with_release_timestamp(client, admin_principal, future)
    paper_id = reg.json()["paper_id"]
    _authorize(client, admin_principal, paper_id, exam_centre_principal.centre_id)

    response = client.get(f"/api/v1/papers/{paper_id}/retrieve", headers=auth_header(exam_centre_principal))
    assert response.status_code == 403
    # The response body must be the JSON error, never the PDF bytes.
    assert SAMPLE_PDF_BYTES not in response.content
    assert response.headers["content-type"].startswith("application/json")


# --- 6. Unauthorized centre remains denied (regardless of time-lock) ---
def test_unauthorized_centre_still_denied_even_after_release_time(
    client, admin_principal, exam_centre_principal
):
    """
    Authorization must be checked (and must fail) BEFORE time-lock is
    even evaluated — an unauthorized centre gets 403 "not authorized"
    even for an ALREADY-RELEASED paper it was never granted access to.
    """
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    reg = _register_paper_with_release_timestamp(client, admin_principal, past)
    paper_id = reg.json()["paper_id"]
    # Deliberately NOT authorizing the centre.

    response = client.get(f"/api/v1/papers/{paper_id}/retrieve", headers=auth_header(exam_centre_principal))
    assert response.status_code == 403
    assert "not authorized" in response.json()["error"]["message"].lower()


# --- 7. Authorized centre CAN retrieve after release (end-to-end) ---
def test_authorized_centre_can_retrieve_after_release(client, admin_principal, exam_centre_principal):
    past = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
    reg = _register_paper_with_release_timestamp(client, admin_principal, past)
    paper_id = reg.json()["paper_id"]
    _authorize(client, admin_principal, paper_id, exam_centre_principal.centre_id)

    response = client.get(f"/api/v1/papers/{paper_id}/retrieve", headers=auth_header(exam_centre_principal))
    assert response.status_code == 200
    assert response.content == SAMPLE_PDF_BYTES


# --- 8. Existing AES-GCM tamper detection still works (post-release) ---
def test_tamper_detection_still_works_after_release_time_has_passed(
    client, db_session, admin_principal, exam_centre_principal
):
    import os

    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    reg = _register_paper_with_release_timestamp(client, admin_principal, past)
    paper_id = reg.json()["paper_id"]
    _authorize(client, admin_principal, paper_id, exam_centre_principal.centre_id)

    from app.models.paper import Paper

    paper = db_session.get(Paper, uuid.UUID(paper_id))
    storage_path = os.path.join(os.environ["STORAGE_LOCAL_PATH"], paper.file_reference)
    with open(storage_path, "r+b") as f:
        first_byte = f.read(1)
        f.seek(0)
        f.write(bytes([first_byte[0] ^ 0xFF]))

    response = client.get(f"/api/v1/papers/{paper_id}/retrieve", headers=auth_header(exam_centre_principal))
    assert response.status_code == 409  # tamper detection, unchanged from Phase 3


# --- 9. Existing SHA-256 verification still works / 10 covered by full-suite run ---
def test_register_response_unaffected_by_time_lock_changes(client, admin_principal):
    """Sanity check: registration itself (Phase 3 behaviour) is untouched by Phase 4."""
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    reg = _register_paper_with_release_timestamp(client, admin_principal, future)
    assert reg.status_code == 201
    body = reg.json()
    assert body["sha256_hash"] == __import__("hashlib").sha256(SAMPLE_PDF_BYTES).hexdigest()
    assert body["encryption_algorithm"] == "AES-256-GCM"
