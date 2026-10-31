"""
Phase 6I — one consistent paper-existence disclosure policy.

Policy (threat model: a legitimate-but-curious or compromised examination
centre must not be able to learn which paper_ids exist, because a
confirmed paper_id is a target and its existence/timing is exam-sensitive):

  For an Examination Centre, on GET /papers/{id}, /papers/{id}/status and
  /papers/{id}/retrieve:
      unknown paper_id            -> 404, body B
      paper exists, NOT authorized -> 404, body B        (same status, same body)
      paper exists, authorization revoked -> 404, body B
  where B is the generic {"error": {"message": "The requested resource was not found."...}}.
  Nothing about the paper (subject, hash, schedule, content) is returned.
  Authorization is still enforced first and in full; the UNAUTHORIZED_ACCESS
  security event (and, for retrieval, the DENIED access-attempt audit event)
  are still recorded when the paper exists.

Deliberately unchanged:
  * Authenticated + authorized centre, paper still locked -> 403 "not yet
    available": that centre is entitled to know the paper exists.
  * Admin: 200 for an existing paper, 404 for an unknown one.
  * Unauthenticated -> 401 whether or not the paper exists.
  * Role-based 403s (e.g. a centre calling an Admin-only route) happen at
    the router BEFORE any lookup, so they do not depend on paper existence.
  * Unrelated server errors are NOT converted to 404.

Known residual (documented, not fixed): the denied path performs extra
audit/security-event writes that the unknown path does not, so response
TIMING could in principle differ. Not mitigated here.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.database import get_db
from app.main import app
from app.models.audit_event import AuditEvent
from app.models.security_event import SecurityEvent
from app.services import paper_service
from tests.conftest import SAMPLE_PDF_BYTES, auth_header
from tests.test_idor_cross_centre import centre_a, centre_b, two_papers  # noqa: F401 (fixtures)
from tests.test_paper_api import _register_sample_paper

NOT_FOUND_MESSAGE = "The requested resource was not found."
PATHS = ["", "/status", "/retrieve"]


def _get(client, principal, paper_id, suffix):
    return client.get(f"/api/v1/papers/{paper_id}{suffix}", headers=auth_header(principal))


def _count(db_session, model, **filters) -> int:
    db_session.expire_all()
    return db_session.query(model).filter_by(**filters).count()


# ---------------------------------------------------------------------------
# The core property: indistinguishable
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("suffix", PATHS)
def test_unauthorized_existing_paper_is_indistinguishable_from_an_unknown_paper(client, two_papers, centre_a, suffix):  # noqa: F811
    _paper_a, paper_b = two_papers
    existing_unauthorized = _get(client, centre_a, paper_b, suffix)
    unknown = _get(client, centre_a, uuid.uuid4(), suffix)

    assert existing_unauthorized.status_code == unknown.status_code == 404
    assert existing_unauthorized.json() == unknown.json()
    assert existing_unauthorized.json()["error"]["message"] == NOT_FOUND_MESSAGE
    # Same content type, and no header that could differ by existence.
    assert existing_unauthorized.headers["content-type"] == unknown.headers["content-type"]
    assert set(existing_unauthorized.headers) == set(unknown.headers)


@pytest.mark.parametrize("suffix", PATHS)
def test_denial_body_discloses_nothing_about_the_paper(client, two_papers, centre_a, suffix):  # noqa: F811
    _paper_a, paper_b = two_papers
    resp = _get(client, centre_a, paper_b, suffix)
    raw = resp.text.lower()
    for leaked in ("idor paper b", "sha256", "release_timestamp", "lock_status", "registered", "subject", "created_at", "authorized"):
        assert leaked not in raw, leaked
    assert paper_b not in resp.text  # the id the caller supplied is not echoed back
    assert b"%PDF" not in resp.content


@pytest.mark.parametrize("suffix", PATHS)
def test_revoked_centre_is_indistinguishable_from_never_authorized(client, admin_principal, two_papers, centre_a, centre_b, suffix):  # noqa: F811
    paper_a, _paper_b = two_papers
    revoke = client.post(
        f"/api/v1/papers/{paper_a}/revoke",
        json={"centre_id": str(centre_a.centre_id)},
        headers=auth_header(admin_principal),
    )
    assert revoke.status_code == 200, revoke.text

    revoked = _get(client, centre_a, paper_a, suffix)
    never = _get(client, centre_b, paper_a, suffix)  # centre B was never authorized for paper A
    unknown = _get(client, centre_a, uuid.uuid4(), suffix)
    assert revoked.status_code == never.status_code == unknown.status_code == 404
    assert revoked.json() == never.json() == unknown.json()


# ---------------------------------------------------------------------------
# Authorization is still enforced; legitimate access still works
# ---------------------------------------------------------------------------


def test_authorized_centre_still_gets_everything(client, two_papers, centre_a):  # noqa: F811
    paper_a, _ = two_papers
    detail = _get(client, centre_a, paper_a, "")
    status = _get(client, centre_a, paper_a, "/status")
    retrieve = _get(client, centre_a, paper_a, "/retrieve")
    assert detail.status_code == 200 and detail.json()["subject"] == "IDOR Paper A"
    assert status.status_code == 200 and status.json()["lock_status"] == "released"
    assert retrieve.status_code == 200 and retrieve.content == SAMPLE_PDF_BYTES


def test_authorized_centre_on_a_locked_paper_still_gets_403_not_yet_available(client, admin_principal, centre_a):  # noqa: F811
    reg = _register_sample_paper(client, admin_principal, subject="Locked", release_timestamp="2099-01-01T00:00:00Z")
    paper_id = reg.json()["paper_id"]
    client.post(
        f"/api/v1/papers/{paper_id}/authorize",
        json={"centre_id": str(centre_a.centre_id)},
        headers=auth_header(admin_principal),
    )
    resp = _get(client, centre_a, paper_id, "/retrieve")
    assert resp.status_code == 403
    assert resp.json()["error"]["message"] == "This paper is not yet available."


def test_unauthorized_centre_never_receives_the_pdf_even_for_a_released_paper(client, two_papers, centre_a):  # noqa: F811
    _a, paper_b = two_papers
    resp = _get(client, centre_a, paper_b, "/retrieve")
    assert resp.status_code == 404
    assert b"%PDF" not in resp.content and resp.content != SAMPLE_PDF_BYTES


def test_admin_is_unaffected(client, admin_principal, two_papers):
    paper_a, _ = two_papers
    assert _get(client, admin_principal, paper_a, "").status_code == 200
    assert _get(client, admin_principal, paper_a, "/status").status_code == 200
    unknown = _get(client, admin_principal, uuid.uuid4(), "")
    assert unknown.status_code == 404 and unknown.json()["error"]["message"] == NOT_FOUND_MESSAGE
    assert _get(client, admin_principal, uuid.uuid4(), "/status").status_code == 404


def test_unauthenticated_gets_401_for_existing_and_unknown_alike(client, two_papers):
    paper_a, _ = two_papers
    for suffix in PATHS:
        existing = client.get(f"/api/v1/papers/{paper_a}{suffix}")
        unknown = client.get(f"/api/v1/papers/{uuid.uuid4()}{suffix}")
        assert existing.status_code == unknown.status_code == 401
        assert existing.json() == unknown.json()


def test_invalid_uuid_is_still_a_validation_error_not_a_disguised_404(client, centre_a):  # noqa: F811
    assert _get(client, centre_a, "not-a-uuid", "").status_code == 422


# ---------------------------------------------------------------------------
# Audit / security recording is intact
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("suffix", ["", "/status", "/retrieve"])
def test_denied_access_to_an_existing_paper_still_records_a_security_event(client, db_session, two_papers, centre_a, suffix):  # noqa: F811
    _a, paper_b = two_papers
    before = _count(db_session, SecurityEvent, event_type="UNAUTHORIZED_ACCESS", paper_id=uuid.UUID(paper_b))
    resp = _get(client, centre_a, paper_b, suffix)
    assert resp.status_code == 404
    after = _count(db_session, SecurityEvent, event_type="UNAUTHORIZED_ACCESS", paper_id=uuid.UUID(paper_b))
    assert after == before + 1


def test_denied_retrieval_still_records_the_denied_audit_event(client, db_session, two_papers, centre_a):  # noqa: F811
    _a, paper_b = two_papers
    pid = uuid.UUID(paper_b)
    before = _count(db_session, AuditEvent, event_type="PAPER_ACCESS_ATTEMPT", outcome="DENIED", paper_id=pid)
    assert _get(client, centre_a, paper_b, "/retrieve").status_code == 404
    assert _count(db_session, AuditEvent, event_type="PAPER_ACCESS_ATTEMPT", outcome="DENIED", paper_id=pid) == before + 1


def test_unknown_paper_records_nothing_against_any_paper(client, db_session, centre_a):  # noqa: F811
    db_session.expire_all()
    sec_before = db_session.query(SecurityEvent).count()
    aud_before = db_session.query(AuditEvent).count()
    for suffix in PATHS:
        assert _get(client, centre_a, uuid.uuid4(), suffix).status_code == 404
    db_session.expire_all()
    assert db_session.query(SecurityEvent).count() == sec_before
    assert db_session.query(AuditEvent).count() == aud_before


# ---------------------------------------------------------------------------
# Consistency across the other paper endpoints
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,suffix,body",
    [
        ("patch", "/schedule", {"release_timestamp": "2099-01-01T00:00:00Z"}),
        ("get", "/schedule-history", None),
        ("post", "/authorize", {"centre_id": str(uuid.uuid4())}),
        ("post", "/revoke", {"centre_id": str(uuid.uuid4())}),
    ],
)
def test_admin_only_endpoints_give_a_centre_the_same_403_for_existing_and_unknown_papers(
    client, two_papers, centre_a, method, suffix, body  # noqa: F811
):
    """The role check runs at the router before any lookup, so these endpoints
    already could not be used as an existence oracle by a centre."""
    paper_a, _ = two_papers
    kwargs = {"headers": auth_header(centre_a)}
    if body is not None:
        kwargs["json"] = body
    existing = getattr(client, method)(f"/api/v1/papers/{paper_a}{suffix}", **kwargs)
    unknown = getattr(client, method)(f"/api/v1/papers/{uuid.uuid4()}{suffix}", **kwargs)
    assert existing.status_code == unknown.status_code == 403
    assert existing.json() == unknown.json()


def test_centre_paper_list_only_ever_contains_authorized_papers(client, two_papers, centre_a):  # noqa: F811
    paper_a, paper_b = two_papers
    ids = {i["paper_id"] for i in client.get("/api/v1/papers", headers=auth_header(centre_a)).json()["items"]}
    assert paper_a in ids and paper_b not in ids


# ---------------------------------------------------------------------------
# No blanket exception handling
# ---------------------------------------------------------------------------


def test_unrelated_server_errors_are_not_disguised_as_404(db_engine, two_papers, centre_a, monkeypatch):  # noqa: F811
    paper_a, _ = two_papers

    def boom(*args, **kwargs):
        raise RuntimeError("database exploded")

    monkeypatch.setattr(paper_service, "is_centre_authorized_for_paper", boom)
    SessionLocal = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)

    def _override():
        s = SessionLocal()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _override
    try:
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get(f"/api/v1/papers/{paper_a}", headers=auth_header(centre_a))
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 500
    assert "database exploded" not in resp.text
