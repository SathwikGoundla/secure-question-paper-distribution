"""
Phase 6C tests — GET /api/v1/papers (app.services.paper_service.list_papers).

Real FastAPI app, real RBAC, real auth (admin_principal/exam_centre_principal
fixtures), real SQLite-backed database — nothing mocked except OTP delivery
capture (see conftest.py).

IMPORTANT test-design note: tests/conftest.py's `db_engine` fixture is
SESSION-scoped (by pre-existing, unmodified design — see that file's
docstring), so every test in the ENTIRE backend suite shares one
database that accumulates rows across files. Tests below therefore
avoid asserting an absolute total count (e.g. "total == 0" or
"total == 2") unless the assertion is scoped to data this exact test
itself just created (via a fresh paper_id/centre_id, or a before/after
delta) — anything else would be flaky depending on test execution
order. This is a deliberate adaptation to the existing test
architecture, not a weakening of what is actually verified.
"""

import time

from tests.conftest import SAMPLE_PDF_BYTES, auth_header

_MAX_PAGE_SIZE = 100  # must match the Query(..., le=100) bound in app/api/v1/papers.py


def _register_paper(client, admin_principal, subject="List Test Paper", release_timestamp="2020-01-01T00:00:00Z"):
    files = {"file": ("sample.pdf", SAMPLE_PDF_BYTES, "application/pdf")}
    data = {"subject": subject, "release_timestamp": release_timestamp}
    response = client.post(
        "/api/v1/papers/register", data=data, files=files, headers=auth_header(admin_principal)
    )
    assert response.status_code == 201, response.text
    return response.json()


def _total(client, admin_principal) -> int:
    return client.get("/api/v1/papers?page_size=1", headers=auth_header(admin_principal)).json()["total"]


def test_admin_sees_newly_registered_papers(client, admin_principal):
    before = _total(client, admin_principal)
    p1 = _register_paper(client, admin_principal, subject="Paper A")
    p2 = _register_paper(client, admin_principal, subject="Paper B")

    response = client.get(
        f"/api/v1/papers?page_size={_MAX_PAGE_SIZE}", headers=auth_header(admin_principal)
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == before + 2
    ids = {item["paper_id"] for item in body["items"]}
    assert {p1["paper_id"], p2["paper_id"]} <= ids


def test_stable_ordering_newest_first(client, admin_principal):
    _register_paper(client, admin_principal, subject="Older")
    # SQLite's server-side CURRENT_TIMESTAMP has 1-second resolution, so a
    # deliberate delay guarantees a strictly later created_at for the
    # "Newer" row rather than relying on a tie-break that would otherwise
    # be arbitrary (paper_id order, not creation order) for two inserts
    # within the same second.
    time.sleep(1.1)
    newer = _register_paper(client, admin_principal, subject="Newer")

    response = client.get("/api/v1/papers", headers=auth_header(admin_principal))
    body = response.json()
    assert body["items"][0]["paper_id"] == newer["paper_id"]


def test_pagination_returns_disjoint_stable_pages(client, admin_principal):
    for i in range(5):
        _register_paper(client, admin_principal, subject=f"Pagination Paper {i}")

    page1 = client.get("/api/v1/papers?page=1&page_size=2", headers=auth_header(admin_principal)).json()
    page2 = client.get("/api/v1/papers?page=2&page_size=2", headers=auth_header(admin_principal)).json()

    assert page1["total"] == page2["total"]
    assert page1["total"] >= 5
    assert len(page1["items"]) == 2
    assert len(page2["items"]) == 2
    assert {i["paper_id"] for i in page1["items"]}.isdisjoint({i["paper_id"] for i in page2["items"]})


def test_page_beyond_last_is_empty(client, admin_principal):
    """A page number past the end of the result set returns an empty list, not an error."""
    response = client.get("/api/v1/papers?page=999999&page_size=20", headers=auth_header(admin_principal))
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_unauthenticated_request_rejected(client):
    response = client.get("/api/v1/papers")
    assert response.status_code == 401


def test_exam_centre_sees_only_authorized_papers(client, admin_principal, exam_centre_principal):
    authorized = _register_paper(client, admin_principal, subject="Authorized Paper")
    _register_paper(client, admin_principal, subject="Not Authorized Paper")

    client.post(
        f"/api/v1/papers/{authorized['paper_id']}/authorize",
        json={"centre_id": str(exam_centre_principal.centre_id)},
        headers=auth_header(admin_principal),
    )

    response = client.get("/api/v1/papers", headers=auth_header(exam_centre_principal))
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["paper_id"] == authorized["paper_id"]


def test_exam_centre_with_no_authorizations_sees_empty_list(client, exam_centre_principal):
    """A brand-new Examination-Centre fixture has zero authorizations — a genuinely, unconditionally empty list."""
    response = client.get("/api/v1/papers", headers=auth_header(exam_centre_principal))
    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["total"] == 0


def test_auditor_forbidden(client, auditor_principal):
    response = client.get("/api/v1/papers", headers=auth_header(auditor_principal))
    assert response.status_code == 403


def test_response_schema_excludes_sensitive_fields(client, admin_principal):
    _register_paper(client, admin_principal)
    response = client.get("/api/v1/papers", headers=auth_header(admin_principal))
    body_text = response.text.lower()
    for forbidden in ("wrapped_dek", "file_nonce", "master_key", "file_reference", "password"):
        assert forbidden not in body_text, f"Response leaked internal field: {forbidden}"

    allowed_keys = {
        "paper_id", "subject", "status", "sha256_hash",
        "release_timestamp", "created_at", "ledger_tx_reference",
        "lock_status",  # Phase 6H: computed release state; not a secret
    }
    for item in response.json()["items"]:
        assert set(item.keys()) <= allowed_keys


def test_status_filter_matches_only_that_status(client, admin_principal):
    reg = _register_paper(client, admin_principal, subject="Filter Test")
    paper_id = reg["paper_id"]

    response = client.get(
        f"/api/v1/papers?status=registered&page_size={_MAX_PAGE_SIZE}", headers=auth_header(admin_principal)
    )
    assert response.status_code == 200
    ids = {item["paper_id"] for item in response.json()["items"]}
    assert paper_id in ids

    response_none = client.get(
        "/api/v1/papers?status=this-status-value-never-exists", headers=auth_header(admin_principal)
    )
    assert response_none.json()["total"] == 0


def test_invalid_page_rejected(client, admin_principal):
    response = client.get("/api/v1/papers?page=0", headers=auth_header(admin_principal))
    assert response.status_code == 422


def test_page_size_upper_bound_enforced(client, admin_principal):
    response = client.get(f"/api/v1/papers?page_size={_MAX_PAGE_SIZE + 1}", headers=auth_header(admin_principal))
    assert response.status_code == 422
