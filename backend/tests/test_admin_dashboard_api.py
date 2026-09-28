"""
Phase 6C tests — GET /api/v1/admin/dashboard/summary
(app.services.dashboard_service). Verifies the response is real,
deterministic, database-derived data — never fabricated.

IMPORTANT test-design note: tests/conftest.py's `db_engine` fixture is
SESSION-scoped (pre-existing, unmodified design), so every table in
this database accumulates rows across the ENTIRE backend test suite.
A true "empty database" state cannot be independently observed by any
single test here. Instead, these tests capture a BEFORE snapshot,
perform a real action, and assert the AFTER snapshot moved by exactly
the expected delta — this proves the numbers are genuinely
database-derived (they change in lock-step with real writes) without
depending on global test-execution order.
"""

from tests.conftest import SAMPLE_PDF_BYTES, auth_header


def _register_paper(client, admin_principal, subject="Dashboard Test Paper"):
    files = {"file": ("sample.pdf", SAMPLE_PDF_BYTES, "application/pdf")}
    data = {"subject": subject, "release_timestamp": "2020-01-01T00:00:00Z"}
    return client.post("/api/v1/papers/register", data=data, files=files, headers=auth_header(admin_principal))


def _summary(client, admin_principal) -> dict:
    response = client.get("/api/v1/admin/dashboard/summary", headers=auth_header(admin_principal))
    assert response.status_code == 200, response.text
    return response.json()


def test_dashboard_requires_admin_role(client, exam_centre_principal):
    response = client.get("/api/v1/admin/dashboard/summary", headers=auth_header(exam_centre_principal))
    assert response.status_code == 403


def test_dashboard_auditor_forbidden(client, auditor_principal):
    """Per LLD Section 15, the dashboard is Admin-only, not Auditor read-only."""
    response = client.get("/api/v1/admin/dashboard/summary", headers=auth_header(auditor_principal))
    assert response.status_code == 403


def test_dashboard_unauthenticated(client):
    response = client.get("/api/v1/admin/dashboard/summary")
    assert response.status_code == 401


def test_dashboard_response_shape_and_internal_consistency(client, admin_principal):
    """
    Structural + invariant checks that hold true regardless of how much
    data already exists: every count is a non-negative integer, and the
    per-status / per-severity breakdowns always sum to their matching
    total (this would NOT hold for fabricated or randomly-generated
    numbers, only for a genuine GROUP BY against the same table).
    """
    body = _summary(client, admin_principal)

    for key in (
        "total_papers", "total_exam_centres", "active_exam_centres",
        "total_paper_authorizations", "total_audit_events", "total_security_events",
    ):
        assert isinstance(body[key], int) and body[key] >= 0

    assert sum(body["papers_by_status"].values()) == body["total_papers"]
    assert sum(body["security_events_by_severity"].values()) == body["total_security_events"]
    assert body["active_exam_centres"] <= body["total_exam_centres"]


def test_dashboard_reflects_new_paper_registration(client, admin_principal):
    before = _summary(client, admin_principal)
    _register_paper(client, admin_principal, subject="Delta Paper 1")
    _register_paper(client, admin_principal, subject="Delta Paper 2")
    after = _summary(client, admin_principal)

    assert after["total_papers"] == before["total_papers"] + 2
    before_registered = before["papers_by_status"].get("registered", 0)
    assert after["papers_by_status"].get("registered", 0) == before_registered + 2


def test_dashboard_reflects_new_exam_centre(client, admin_principal):
    before = _summary(client, admin_principal)
    client.post(
        "/api/v1/admin/centres", json={"centre_name": "Delta Dashboard Centre"}, headers=auth_header(admin_principal)
    )
    after = _summary(client, admin_principal)

    assert after["total_exam_centres"] == before["total_exam_centres"] + 1
    assert after["active_exam_centres"] == before["active_exam_centres"] + 1


def test_dashboard_reflects_new_paper_authorization(client, admin_principal, exam_centre_principal):
    before = _summary(client, admin_principal)
    reg = _register_paper(client, admin_principal, subject="Auth Delta Paper")
    paper_id = reg.json()["paper_id"]

    client.post(
        f"/api/v1/papers/{paper_id}/authorize",
        json={"centre_id": str(exam_centre_principal.centre_id)},
        headers=auth_header(admin_principal),
    )

    after = _summary(client, admin_principal)
    assert after["total_paper_authorizations"] == before["total_paper_authorizations"] + 1


def test_dashboard_reflects_new_security_event(client, admin_principal, exam_centre_principal):
    before = _summary(client, admin_principal)
    reg = _register_paper(client, admin_principal, subject="Security Delta Paper")
    paper_id = reg.json()["paper_id"]
    # Deliberately NOT authorized -> a real UNAUTHORIZED_ACCESS security event.
    client.get(f"/api/v1/papers/{paper_id}/retrieve", headers=auth_header(exam_centre_principal))

    after = _summary(client, admin_principal)
    assert after["total_security_events"] == before["total_security_events"] + 1


def test_dashboard_is_deterministic_across_repeated_calls(client, admin_principal):
    first = _summary(client, admin_principal)
    second = _summary(client, admin_principal)
    assert first == second
