"""
Phase 6C tests — GET /api/v1/audit/logs
(app.services.audit_service.list_audit_events).
"""

from tests.conftest import SAMPLE_PDF_BYTES, auth_header


def _register_paper(client, admin_principal, subject="Audit Test Paper"):
    files = {"file": ("sample.pdf", SAMPLE_PDF_BYTES, "application/pdf")}
    data = {"subject": subject, "release_timestamp": "2020-01-01T00:00:00Z"}
    return client.post("/api/v1/papers/register", data=data, files=files, headers=auth_header(admin_principal))


def test_admin_can_read_audit_logs(client, admin_principal):
    _register_paper(client, admin_principal)
    response = client.get("/api/v1/audit/logs", headers=auth_header(admin_principal))
    assert response.status_code == 200, response.text
    body = response.json()
    event_types = {item["event_type"] for item in body["items"]}
    assert "PAPER_REGISTRATION_COMPLETED" in event_types


def test_auditor_can_read_audit_logs(client, admin_principal, auditor_principal):
    _register_paper(client, admin_principal)
    response = client.get("/api/v1/audit/logs", headers=auth_header(auditor_principal))
    assert response.status_code == 200


def test_examination_centre_forbidden(client, exam_centre_principal):
    response = client.get("/api/v1/audit/logs", headers=auth_header(exam_centre_principal))
    assert response.status_code == 403


def test_unauthenticated_rejected(client):
    response = client.get("/api/v1/audit/logs")
    assert response.status_code == 401


def test_empty_logs_scoped_to_a_paper_that_was_never_created(client, admin_principal):
    """
    NOTE: tests/conftest.py's db_engine fixture is SESSION-scoped
    (pre-existing design), so audit_events accumulates across the
    whole suite (including from admin_principal's own login). Filtering
    by a freshly-generated paper_id that has never been used gives an
    unconditionally, genuinely empty result.
    """
    never_used_paper_id = "00000000-0000-0000-0000-000000000000"
    response = client.get(
        f"/api/v1/audit/logs?paper_id={never_used_paper_id}", headers=auth_header(admin_principal)
    )
    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["total"] == 0


def test_filter_by_paper_id(client, admin_principal):
    reg1 = _register_paper(client, admin_principal, subject="Paper One")
    reg2 = _register_paper(client, admin_principal, subject="Paper Two")
    paper_id_1 = reg1.json()["paper_id"]

    response = client.get(f"/api/v1/audit/logs?paper_id={paper_id_1}", headers=auth_header(admin_principal))
    body = response.json()
    assert body["total"] > 0
    assert all(item["paper_id"] == paper_id_1 for item in body["items"])


def test_filter_by_event_type(client, admin_principal):
    reg = _register_paper(client, admin_principal)
    paper_id = reg.json()["paper_id"]
    response = client.get(
        f"/api/v1/audit/logs?paper_id={paper_id}&event_type=PAPER_REGISTRATION_COMPLETED",
        headers=auth_header(admin_principal),
    )
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["event_type"] == "PAPER_REGISTRATION_COMPLETED"


def test_filter_by_outcome(client, admin_principal):
    _register_paper(client, admin_principal)
    response = client.get("/api/v1/audit/logs?outcome=SUCCESS", headers=auth_header(admin_principal))
    body = response.json()
    assert body["total"] > 0
    assert all(item["outcome"] == "SUCCESS" for item in body["items"])


def test_pagination(client, admin_principal):
    for i in range(3):
        _register_paper(client, admin_principal, subject=f"Pagination Paper {i}")

    page1 = client.get("/api/v1/audit/logs?page=1&page_size=2", headers=auth_header(admin_principal)).json()
    assert len(page1["items"]) == 2
    assert page1["total"] >= 3


def test_response_includes_actor_username_and_excludes_secrets(client, admin_principal):
    _register_paper(client, admin_principal)
    response = client.get("/api/v1/audit/logs?page_size=200", headers=auth_header(admin_principal))
    body = response.json()
    matching = [i for i in body["items"] if i["event_type"] == "PAPER_REGISTRATION_COMPLETED"]
    assert matching
    assert matching[0]["actor_username"] == admin_principal.username

    body_text = response.text.lower()
    for forbidden in ("password", "otp", "wrapped_dek", "file_nonce", "bearer "):
        assert forbidden not in body_text


def test_invalid_page_size_rejected(client, admin_principal):
    response = client.get("/api/v1/audit/logs?page_size=99999", headers=auth_header(admin_principal))
    assert response.status_code == 422


def test_injection_style_filter_value_is_treated_as_data(client, admin_principal):
    """Filters go through SQLAlchemy bound parameters — a SQL-looking value matches nothing and errors nothing."""
    response = client.get(
        "/api/v1/audit/logs",
        params={"event_type": "' OR '1'='1' --", "outcome": "SUCCESS'; DROP TABLE audit_events; --"},
        headers=auth_header(admin_principal),
    )
    assert response.status_code == 200
    assert response.json()["total"] == 0
    # The table must still be intact and queryable afterwards.
    assert client.get("/api/v1/audit/logs", headers=auth_header(admin_principal)).status_code == 200


def test_filter_by_centre_id_matches_only_that_centres_actors(client, admin_principal, exam_centre_principal):
    response = client.get(
        f"/api/v1/audit/logs?centre_id={exam_centre_principal.centre_id}&page_size=200",
        headers=auth_header(admin_principal),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1
    assert all(item["actor_id"] == str(exam_centre_principal.user_id) for item in body["items"])
