"""
Phase 6C tests — GET /api/v1/monitoring/security-events
(app.services.audit_service.list_security_events).
"""

from tests.conftest import SAMPLE_PDF_BYTES, auth_header


def _register_paper(client, admin_principal, subject="Security Test Paper"):
    files = {"file": ("sample.pdf", SAMPLE_PDF_BYTES, "application/pdf")}
    data = {"subject": subject, "release_timestamp": "2020-01-01T00:00:00Z"}
    return client.post("/api/v1/papers/register", data=data, files=files, headers=auth_header(admin_principal))


def _trigger_unauthorized_access_event(client, admin_principal, exam_centre_principal):
    reg = _register_paper(client, admin_principal)
    paper_id = reg.json()["paper_id"]
    # Deliberately not authorized -> UNAUTHORIZED_ACCESS security event.
    client.get(f"/api/v1/papers/{paper_id}/retrieve", headers=auth_header(exam_centre_principal))
    return paper_id


def test_admin_can_read_security_events(client, admin_principal, exam_centre_principal):
    _trigger_unauthorized_access_event(client, admin_principal, exam_centre_principal)
    response = client.get("/api/v1/monitoring/security-events", headers=auth_header(admin_principal))
    assert response.status_code == 200, response.text
    event_types = {item["event_type"] for item in response.json()["items"]}
    assert "UNAUTHORIZED_ACCESS" in event_types


def test_auditor_can_read_security_events(client, admin_principal, exam_centre_principal, auditor_principal):
    _trigger_unauthorized_access_event(client, admin_principal, exam_centre_principal)
    response = client.get("/api/v1/monitoring/security-events", headers=auth_header(auditor_principal))
    assert response.status_code == 200


def test_examination_centre_forbidden(client, exam_centre_principal):
    response = client.get("/api/v1/monitoring/security-events", headers=auth_header(exam_centre_principal))
    assert response.status_code == 403


def test_unauthenticated_rejected(client):
    response = client.get("/api/v1/monitoring/security-events")
    assert response.status_code == 401


def test_empty_events_scoped_to_a_paper_that_was_never_created(client, admin_principal):
    """
    NOTE: tests/conftest.py's db_engine fixture is SESSION-scoped
    (pre-existing design), so security_events accumulates across the
    whole suite. Filtering by a paper_id that was never used gives an
    unconditionally, genuinely empty result.
    """
    never_used_paper_id = "00000000-0000-0000-0000-000000000000"
    response = client.get(
        f"/api/v1/monitoring/security-events?paper_id={never_used_paper_id}",
        headers=auth_header(admin_principal),
    )
    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["total"] == 0


def test_filter_by_severity(client, admin_principal, exam_centre_principal):
    _trigger_unauthorized_access_event(client, admin_principal, exam_centre_principal)
    response = client.get(
        "/api/v1/monitoring/security-events?severity=MEDIUM", headers=auth_header(admin_principal)
    )
    body = response.json()
    assert all(item["severity"] == "MEDIUM" for item in body["items"])


def test_filter_by_event_type(client, admin_principal, exam_centre_principal):
    paper_id = _trigger_unauthorized_access_event(client, admin_principal, exam_centre_principal)
    response = client.get(
        f"/api/v1/monitoring/security-events?paper_id={paper_id}&event_type=UNAUTHORIZED_ACCESS",
        headers=auth_header(admin_principal),
    )
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["event_type"] == "UNAUTHORIZED_ACCESS"


def test_filter_by_paper_id(client, admin_principal, exam_centre_principal):
    paper_id = _trigger_unauthorized_access_event(client, admin_principal, exam_centre_principal)
    response = client.get(
        f"/api/v1/monitoring/security-events?paper_id={paper_id}", headers=auth_header(admin_principal)
    )
    body = response.json()
    assert body["total"] >= 1
    assert all(item["paper_id"] == paper_id for item in body["items"])


def test_response_excludes_secrets(client, admin_principal, exam_centre_principal):
    _trigger_unauthorized_access_event(client, admin_principal, exam_centre_principal)
    response = client.get("/api/v1/monitoring/security-events", headers=auth_header(admin_principal))
    body_text = response.text.lower()
    for forbidden in ("password", "otp_hash", "wrapped_dek", "file_nonce", "bearer "):
        assert forbidden not in body_text


def test_invalid_page_rejected(client, admin_principal):
    response = client.get("/api/v1/monitoring/security-events?page=0", headers=auth_header(admin_principal))
    assert response.status_code == 422


def test_injection_style_filter_value_is_treated_as_data(client, admin_principal):
    response = client.get(
        "/api/v1/monitoring/security-events",
        params={"severity": "HIGH' OR '1'='1", "event_type": "x'; DROP TABLE security_events; --"},
        headers=auth_header(admin_principal),
    )
    assert response.status_code == 200
    assert response.json()["total"] == 0
    assert client.get("/api/v1/monitoring/security-events", headers=auth_header(admin_principal)).status_code == 200
