"""
Phase 6C tests — /api/v1/admin/centres (list/create/get/update).
Real FastAPI app, real RBAC, real auth, real SQLite-backed database.
"""

import uuid

from tests.conftest import auth_header


def test_admin_create_centre_success(client, admin_principal):
    response = client.post(
        "/api/v1/admin/centres",
        json={"centre_name": "Greenview Examination Centre"},
        headers=auth_header(admin_principal),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["centre_name"] == "Greenview Examination Centre"
    assert body["is_active"] is True
    assert "centre_id" in body


def test_create_centre_validation_failure_blank_name(client, admin_principal):
    response = client.post(
        "/api/v1/admin/centres", json={"centre_name": "   "}, headers=auth_header(admin_principal)
    )
    assert response.status_code == 422


def test_create_centre_duplicate_name_conflict(client, admin_principal):
    client.post(
        "/api/v1/admin/centres", json={"centre_name": "Riverside Centre"}, headers=auth_header(admin_principal)
    )
    response = client.post(
        "/api/v1/admin/centres", json={"centre_name": "riverside centre"}, headers=auth_header(admin_principal)
    )
    assert response.status_code == 409


def test_create_centre_requires_admin_role(client, exam_centre_principal):
    response = client.post(
        "/api/v1/admin/centres",
        json={"centre_name": "Should Not Be Created"},
        headers=auth_header(exam_centre_principal),
    )
    assert response.status_code == 403


def test_create_centre_auditor_forbidden(client, auditor_principal):
    response = client.post(
        "/api/v1/admin/centres",
        json={"centre_name": "Should Not Be Created Either"},
        headers=auth_header(auditor_principal),
    )
    assert response.status_code == 403


def test_create_centre_unauthenticated(client):
    response = client.post("/api/v1/admin/centres", json={"centre_name": "No Auth"})
    assert response.status_code == 401


def test_admin_can_list_centres(client, admin_principal):
    client.post("/api/v1/admin/centres", json={"centre_name": "Centre One"}, headers=auth_header(admin_principal))
    client.post("/api/v1/admin/centres", json={"centre_name": "Centre Two"}, headers=auth_header(admin_principal))

    response = client.get("/api/v1/admin/centres", headers=auth_header(admin_principal))
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 2
    names = {c["centre_name"] for c in body["items"]}
    assert {"Centre One", "Centre Two"} <= names


def test_list_centres_page_beyond_last_is_empty(client, admin_principal):
    """
    NOTE: tests/conftest.py's db_engine fixture is SESSION-scoped (pre-
    existing design), so the exam_centres table accumulates rows across
    the whole backend test suite (e.g. every exam_centre_principal
    fixture used elsewhere creates one) — asserting an absolute
    "total == 0" here would be flaky depending on test execution order.
    A page number past the end of the result set returning an empty
    list is an unconditionally true "empty list" behaviour instead.
    """
    client.post("/api/v1/admin/centres", json={"centre_name": "At Least One Centre"}, headers=auth_header(admin_principal))
    response = client.get("/api/v1/admin/centres?page=999999&page_size=20", headers=auth_header(admin_principal))
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_list_centres_requires_admin(client, exam_centre_principal):
    response = client.get("/api/v1/admin/centres", headers=auth_header(exam_centre_principal))
    assert response.status_code == 403


def test_list_centres_auditor_forbidden(client, auditor_principal):
    """Per LLD Section 15, centre MANAGEMENT (including listing) is Admin-only, not Auditor read-only."""
    response = client.get("/api/v1/admin/centres", headers=auth_header(auditor_principal))
    assert response.status_code == 403


def test_get_centre_by_id(client, admin_principal):
    create_resp = client.post(
        "/api/v1/admin/centres", json={"centre_name": "Lookup Centre"}, headers=auth_header(admin_principal)
    )
    centre_id = create_resp.json()["centre_id"]

    response = client.get(f"/api/v1/admin/centres/{centre_id}", headers=auth_header(admin_principal))
    assert response.status_code == 200
    assert response.json()["centre_id"] == centre_id


def test_get_unknown_centre_returns_404(client, admin_principal):
    response = client.get(f"/api/v1/admin/centres/{uuid.uuid4()}", headers=auth_header(admin_principal))
    assert response.status_code == 404


def test_update_centre_rename(client, admin_principal):
    create_resp = client.post(
        "/api/v1/admin/centres", json={"centre_name": "Old Name"}, headers=auth_header(admin_principal)
    )
    centre_id = create_resp.json()["centre_id"]

    response = client.patch(
        f"/api/v1/admin/centres/{centre_id}",
        json={"centre_name": "New Name"},
        headers=auth_header(admin_principal),
    )
    assert response.status_code == 200
    assert response.json()["centre_name"] == "New Name"


def test_update_centre_deactivate(client, admin_principal):
    create_resp = client.post(
        "/api/v1/admin/centres", json={"centre_name": "Deactivate Me"}, headers=auth_header(admin_principal)
    )
    centre_id = create_resp.json()["centre_id"]

    response = client.patch(
        f"/api/v1/admin/centres/{centre_id}",
        json={"is_active": False},
        headers=auth_header(admin_principal),
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is False


def test_update_centre_no_fields_rejected(client, admin_principal):
    create_resp = client.post(
        "/api/v1/admin/centres", json={"centre_name": "No Fields"}, headers=auth_header(admin_principal)
    )
    centre_id = create_resp.json()["centre_id"]

    response = client.patch(f"/api/v1/admin/centres/{centre_id}", json={}, headers=auth_header(admin_principal))
    assert response.status_code == 400


def test_update_unknown_centre_returns_404(client, admin_principal):
    response = client.patch(
        f"/api/v1/admin/centres/{uuid.uuid4()}",
        json={"centre_name": "Doesn't Matter"},
        headers=auth_header(admin_principal),
    )
    assert response.status_code == 404


def test_update_centre_name_conflict(client, admin_principal):
    client.post("/api/v1/admin/centres", json={"centre_name": "Existing Centre"}, headers=auth_header(admin_principal))
    create_resp = client.post(
        "/api/v1/admin/centres", json={"centre_name": "Renameable Centre"}, headers=auth_header(admin_principal)
    )
    centre_id = create_resp.json()["centre_id"]

    response = client.patch(
        f"/api/v1/admin/centres/{centre_id}",
        json={"centre_name": "Existing Centre"},
        headers=auth_header(admin_principal),
    )
    assert response.status_code == 409


def test_update_centre_requires_admin(client, admin_principal, exam_centre_principal):
    create_resp = client.post(
        "/api/v1/admin/centres", json={"centre_name": "Protected Centre"}, headers=auth_header(admin_principal)
    )
    centre_id = create_resp.json()["centre_id"]

    response = client.patch(
        f"/api/v1/admin/centres/{centre_id}",
        json={"centre_name": "Hacked Name"},
        headers=auth_header(exam_centre_principal),
    )
    assert response.status_code == 403


def test_centre_response_never_exposes_credentials(client, admin_principal):
    response = client.post(
        "/api/v1/admin/centres", json={"centre_name": "Safe Centre"}, headers=auth_header(admin_principal)
    )
    body_text = response.text.lower()
    for forbidden in ("password", "password_hash", "otp", "jwt"):
        assert forbidden not in body_text
