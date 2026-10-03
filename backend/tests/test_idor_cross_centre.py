"""
Phase 6E-3 — IDOR / cross-centre authorization regression tests.

Every test drives the REAL FastAPI app and the REAL backend
authorization logic (app/services/authorization_service.py,
app/services/paper_service.py, app/api/deps.py's require_role,
app/api/v1/*.py's RBAC wiring) — nothing here is a frontend test, and
nothing here treats a frontend route guard as a security boundary.
The objective, per the Phase 6E-3 brief: prove that Examination
Centre A can never access or manipulate a resource that legitimately
belongs only to Examination Centre B, and vice versa, purely via
backend HTTP responses.

Inspection finding (documented, not changed): app/services/
paper_service.py's get_paper_by_id_or_404() always runs BEFORE the
authorization check in get_paper_metadata()/retrieve_paper(). This
means an EXISTING paper the caller is not authorized for returns 403
(not 404) — the paper's existence as a UUID is therefore technically
distinguishable from a UUID that was never registered at all (which
returns 404). This is existing, documented, Phase 3/4 behavior, not a
Phase 6E-3 regression: it reveals only that *some* paper_id exists,
never its subject, status, hash, schedule, or content, and changing
it was explicitly out of scope for this phase ("do not automatically
modify production code" / "do not make speculative security
changes"). Test 10 below exercises and documents this exact boundary
rather than silently assuming a different, invented behavior.

Endpoint-coverage note for "IDOR TEST 9" (object access via any
client-supplied ID): the actual API surface, confirmed by direct
inspection of every router in app/api/v1/, exposes exactly five kinds
of client-supplied object IDs an authorization check could apply to:
paper_id (GET /papers/{id}, GET /papers/{id}/retrieve,
GET /papers/{id}/status, POST /papers/{id}/authorize), centre_id (as
a path param on GET/PATCH /admin/centres/{id}, and as a body/query
filter elsewhere), and the paper_id/centre_id/actor_id QUERY FILTERS
on GET /audit/logs and GET /monitoring/security-events. There is no
user_id-accepting endpoint and no session_id-accepting endpoint
exposed to any non-admin caller (logout acts on the caller's own
bearer token only — see app/api/v1/auth.py) to even attempt IDOR
against; no such endpoint was invented here. Every one of these real
cases is covered by Tests 1-8 below.
"""

import uuid

import pytest

from app.models.exam_centre import ExamCentre
from app.models.user import User
from app.security.password import hash_password
# Imported under an alias: a module-level name starting with "Test"
# makes pytest's collector emit a (harmless, but noisy) warning trying
# to collect it as a test class, since it's a dataclass with __init__.
from tests.conftest import TestPrincipal as _Principal
from tests.conftest import _get_or_create_role, _login_and_capture_token, auth_header
from tests.test_paper_api import _register_sample_paper


# ---------------------------------------------------------------------------
# Two-distinct-centre fixtures (conftest.py's exam_centre_principal only
# ever creates ONE centre — these create two GENUINELY SEPARATE ones).
# ---------------------------------------------------------------------------


def _make_centre_principal(client, db_session, monkeypatch, label: str) -> _Principal:
    """Mirrors conftest.py's exam_centre_principal fixture body exactly
    (same FK-provisioning-admin pattern, same two-factor login), just
    parametrized so two independent centres can be created in one test."""
    role = _get_or_create_role(db_session, "Examination Centre")
    admin_role = _get_or_create_role(db_session, "Admin")

    provisioning_admin = User(
        username=f"prov_admin_{label}_{uuid.uuid4().hex[:6]}",
        password_hash=hash_password("not-used-in-this-fixture"),
        role_id=admin_role.role_id,
    )
    db_session.add(provisioning_admin)
    db_session.commit()
    db_session.refresh(provisioning_admin)

    centre = ExamCentre(
        centre_name=f"IDOR Centre {label} {uuid.uuid4().hex[:6]}",
        created_by=provisioning_admin.user_id,
    )
    db_session.add(centre)
    db_session.commit()
    db_session.refresh(centre)

    username = f"idor_{label.lower()}_{uuid.uuid4().hex[:8]}"
    password = f"Test-IDOR-{label}-Password-123!"
    user = User(
        username=username,
        password_hash=hash_password(password),
        role_id=role.role_id,
        centre_id=centre.centre_id,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    token = _login_and_capture_token(client, monkeypatch, username, password)
    return _Principal(
        user_id=user.user_id,
        username=username,
        password=password,
        access_token=token,
        centre_id=centre.centre_id,
    )


@pytest.fixture()
def centre_a(client, db_session, monkeypatch) -> _Principal:
    return _make_centre_principal(client, db_session, monkeypatch, "A")


@pytest.fixture()
def centre_b(client, db_session, monkeypatch) -> _Principal:
    return _make_centre_principal(client, db_session, monkeypatch, "B")


@pytest.fixture()
def two_papers(client, admin_principal, centre_a, centre_b):
    """
    Paper A -> authorized ONLY to Centre A.
    Paper B -> authorized ONLY to Centre B.
    Both already released (past release_timestamp, matching
    _register_sample_paper's default) so AUTHORIZATION — never
    time-lock — is what every test below is isolating. Returns
    (paper_a_id, paper_b_id) as strings.
    """
    reg_a = _register_sample_paper(client, admin_principal, subject="IDOR Paper A")
    assert reg_a.status_code == 201, reg_a.text
    paper_a_id = reg_a.json()["paper_id"]

    reg_b = _register_sample_paper(client, admin_principal, subject="IDOR Paper B")
    assert reg_b.status_code == 201, reg_b.text
    paper_b_id = reg_b.json()["paper_id"]

    auth_a = client.post(
        f"/api/v1/papers/{paper_a_id}/authorize",
        json={"centre_id": str(centre_a.centre_id)},
        headers=auth_header(admin_principal),
    )
    assert auth_a.status_code == 200, auth_a.text

    auth_b = client.post(
        f"/api/v1/papers/{paper_b_id}/authorize",
        json={"centre_id": str(centre_b.centre_id)},
        headers=auth_header(admin_principal),
    )
    assert auth_b.status_code == 200, auth_b.text

    return paper_a_id, paper_b_id


# ===========================================================================
# IDOR TEST 1 — paper list is centre-scoped
# ===========================================================================


def test_paper_list_is_centre_scoped(client, two_papers, centre_a, centre_b):
    paper_a_id, paper_b_id = two_papers

    resp_a = client.get("/api/v1/papers", headers=auth_header(centre_a))
    assert resp_a.status_code == 200
    ids_a = {item["paper_id"] for item in resp_a.json()["items"]}
    assert paper_a_id in ids_a
    assert paper_b_id not in ids_a

    resp_b = client.get("/api/v1/papers", headers=auth_header(centre_b))
    assert resp_b.status_code == 200
    ids_b = {item["paper_id"] for item in resp_b.json()["items"]}
    assert paper_b_id in ids_b
    assert paper_a_id not in ids_b


# ===========================================================================
# IDOR TEST 2 — paper detail
# ===========================================================================


def test_centre_a_cannot_view_centre_b_paper_detail(client, two_papers, centre_a):
    _paper_a_id, paper_b_id = two_papers

    resp = client.get(f"/api/v1/papers/{paper_b_id}", headers=auth_header(centre_a))

    assert resp.status_code == 403
    body = resp.json()
    assert body["error"]["message"] == "You are not authorized to access this paper."
    # No paper metadata of any kind leaked in the rejection body.
    raw = resp.text
    assert "IDOR Paper B" not in raw  # the subject
    assert "sha256_hash" not in raw
    assert "release_timestamp" not in raw


def test_centre_b_cannot_view_centre_a_paper_detail(client, two_papers, centre_b):
    paper_a_id, _paper_b_id = two_papers

    resp = client.get(f"/api/v1/papers/{paper_a_id}", headers=auth_header(centre_b))

    assert resp.status_code == 403
    assert resp.json()["error"]["message"] == "You are not authorized to access this paper."
    assert "IDOR Paper A" not in resp.text


# ===========================================================================
# IDOR TEST 3 — paper retrieval
# ===========================================================================


def test_centre_a_cannot_retrieve_centre_b_paper(client, two_papers, centre_a):
    _paper_a_id, paper_b_id = two_papers

    resp = client.get(f"/api/v1/papers/{paper_b_id}/retrieve", headers=auth_header(centre_a))

    assert resp.status_code == 403
    assert resp.json()["error"]["message"] == "You are not authorized to access this paper."
    # Never the PDF, nor any fragment of it, nor its content-type.
    assert resp.headers.get("content-type", "").startswith("application/json")
    assert b"%PDF" not in resp.content


def test_centre_b_cannot_retrieve_centre_a_paper(client, two_papers, centre_b):
    paper_a_id, _paper_b_id = two_papers

    resp = client.get(f"/api/v1/papers/{paper_a_id}/retrieve", headers=auth_header(centre_b))

    assert resp.status_code == 403
    assert resp.json()["error"]["message"] == "You are not authorized to access this paper."
    assert resp.headers.get("content-type", "").startswith("application/json")
    assert b"%PDF" not in resp.content


def test_cross_centre_retrieval_denial_does_not_weaken_time_lock_or_integrity(
    client, admin_principal, centre_a, centre_b
):
    """
    Explicit regression guard (per the Phase 6E-3 brief's warning not
    to weaken time-lock/integrity logic to make IDOR tests pass): a
    paper that is BOTH unauthorized for Centre A AND still time-locked
    (future release_timestamp) must still be rejected for the
    AUTHORIZATION reason, with the SAME generic message/shape as the
    already-released cross-centre cases above — proving authorization
    is checked (and fails) independently of, and before, time-lock,
    exactly as paper_service.retrieve_paper's documented check order
    requires.
    """
    reg = _register_sample_paper(
        client, admin_principal, subject="IDOR Future Paper", release_timestamp="2099-01-01T00:00:00Z"
    )
    assert reg.status_code == 201, reg.text
    paper_id = reg.json()["paper_id"]

    auth_resp = client.post(
        f"/api/v1/papers/{paper_id}/authorize",
        json={"centre_id": str(centre_b.centre_id)},
        headers=auth_header(admin_principal),
    )
    assert auth_resp.status_code == 200, auth_resp.text

    # Centre A was never authorized for this paper at all.
    resp = client.get(f"/api/v1/papers/{paper_id}/retrieve", headers=auth_header(centre_a))
    assert resp.status_code == 403
    assert resp.json()["error"]["message"] == "You are not authorized to access this paper."


# ===========================================================================
# IDOR TEST 4 — paper authorization is Admin-only
# ===========================================================================


def test_centre_user_cannot_call_authorize_endpoint(client, two_papers, centre_a, centre_b):
    paper_a_id, _paper_b_id = two_papers

    resp = client.post(
        f"/api/v1/papers/{paper_a_id}/authorize",
        json={"centre_id": str(centre_b.centre_id)},
        headers=auth_header(centre_a),
    )

    assert resp.status_code == 403
    assert resp.json()["error"]["message"] == "You do not have permission to perform this action."


def test_auditor_cannot_call_authorize_endpoint(client, two_papers, auditor_principal, centre_b):
    paper_a_id, _paper_b_id = two_papers

    resp = client.post(
        f"/api/v1/papers/{paper_a_id}/authorize",
        json={"centre_id": str(centre_b.centre_id)},
        headers=auth_header(auditor_principal),
    )

    assert resp.status_code == 403
    assert resp.json()["error"]["message"] == "You do not have permission to perform this action."


# ===========================================================================
# IDOR TEST 5 — exam-centre management is Admin-only
# ===========================================================================


@pytest.mark.parametrize(
    "method,path_suffix,body",
    [
        ("get", "/admin/centres", None),
        ("post", "/admin/centres", {"centre_name": "Should Not Be Created"}),
    ],
)
def test_centre_user_denied_centre_management(client, centre_a, method, path_suffix, body):
    call = getattr(client, method)
    kwargs = {"headers": auth_header(centre_a)}
    if body is not None:
        kwargs["json"] = body
    resp = call(f"/api/v1{path_suffix}", **kwargs)
    assert resp.status_code == 403


@pytest.mark.parametrize(
    "method,path_suffix,body",
    [
        ("get", "/admin/centres", None),
        ("post", "/admin/centres", {"centre_name": "Should Not Be Created"}),
    ],
)
def test_auditor_denied_centre_management(client, auditor_principal, method, path_suffix, body):
    call = getattr(client, method)
    kwargs = {"headers": auth_header(auditor_principal)}
    if body is not None:
        kwargs["json"] = body
    resp = call(f"/api/v1{path_suffix}", **kwargs)
    assert resp.status_code == 403


def test_centre_user_denied_get_single_centre(client, centre_a, centre_b):
    resp = client.get(f"/api/v1/admin/centres/{centre_b.centre_id}", headers=auth_header(centre_a))
    assert resp.status_code == 403


def test_centre_user_denied_update_centre(client, centre_a, centre_b):
    resp = client.patch(
        f"/api/v1/admin/centres/{centre_b.centre_id}",
        json={"centre_name": "Renamed By Attacker"},
        headers=auth_header(centre_a),
    )
    assert resp.status_code == 403


def test_auditor_denied_update_centre(client, auditor_principal, centre_b):
    resp = client.patch(
        f"/api/v1/admin/centres/{centre_b.centre_id}",
        json={"centre_name": "Renamed By Auditor"},
        headers=auth_header(auditor_principal),
    )
    assert resp.status_code == 403


# ===========================================================================
# IDOR TEST 6 — admin dashboard
# ===========================================================================


def test_dashboard_denied_to_centre_and_auditor_allowed_to_admin(
    client, admin_principal, auditor_principal, centre_a
):
    admin_resp = client.get("/api/v1/admin/dashboard/summary", headers=auth_header(admin_principal))
    assert admin_resp.status_code == 200

    auditor_resp = client.get("/api/v1/admin/dashboard/summary", headers=auth_header(auditor_principal))
    assert auditor_resp.status_code == 403

    centre_resp = client.get("/api/v1/admin/dashboard/summary", headers=auth_header(centre_a))
    assert centre_resp.status_code == 403


# ===========================================================================
# IDOR TEST 7 — audit logs
# ===========================================================================


def test_audit_logs_denied_to_centre_even_with_filters(client, centre_a, centre_b):
    """Confirms the RBAC gate runs regardless of (and before) any
    query-string filter is evaluated — a centre cannot use a filter
    (e.g. targeting a DIFFERENT centre's audit trail) to coax any data
    out of an endpoint it has no role-level access to at all."""
    resp = client.get(
        f"/api/v1/audit/logs?centre_id={centre_b.centre_id}",
        headers=auth_header(centre_a),
    )
    assert resp.status_code == 403
    assert "items" not in resp.json()


def test_audit_logs_allowed_to_admin_and_auditor(client, admin_principal, auditor_principal):
    admin_resp = client.get("/api/v1/audit/logs", headers=auth_header(admin_principal))
    assert admin_resp.status_code == 200
    auditor_resp = client.get("/api/v1/audit/logs", headers=auth_header(auditor_principal))
    assert auditor_resp.status_code == 200


# ===========================================================================
# IDOR TEST 8 — security/monitoring events
# ===========================================================================


def test_security_events_denied_to_centre_even_with_filters(client, centre_a, centre_b):
    resp = client.get(
        f"/api/v1/monitoring/security-events?centre_id={centre_b.centre_id}",
        headers=auth_header(centre_a),
    )
    assert resp.status_code == 403
    assert "items" not in resp.json()


def test_security_events_allowed_to_admin_and_auditor(client, admin_principal, auditor_principal):
    admin_resp = client.get("/api/v1/monitoring/security-events", headers=auth_header(admin_principal))
    assert admin_resp.status_code == 200
    auditor_resp = client.get("/api/v1/monitoring/security-events", headers=auth_header(auditor_principal))
    assert auditor_resp.status_code == 200


# ===========================================================================
# IDOR TEST 9 — see module docstring: every real client-supplied-ID
# endpoint discovered by inspection is already covered by Tests 1-8
# above (paper_id: Tests 1-3, 10; centre_id as a path param: Test 5;
# centre_id as a query filter: Tests 7-8). No endpoint was invented.
# ===========================================================================


# ===========================================================================
# IDOR TEST 10 — explicit UUID substitution, including a truly unknown ID
# ===========================================================================


def test_uuid_substitution_centre_a_token_with_centre_b_paper_id(client, two_papers, centre_a):
    """The canonical IDOR pattern: a VALID, authenticated token for one
    principal (Centre A), combined with another principal's (Centre
    B's) real resource ID. Exercised across every paper_id-accepting
    endpoint in one place for a single, unambiguous assertion set."""
    _paper_a_id, paper_b_id = two_papers
    headers = auth_header(centre_a)

    detail_resp = client.get(f"/api/v1/papers/{paper_b_id}", headers=headers)
    assert detail_resp.status_code == 403

    retrieve_resp = client.get(f"/api/v1/papers/{paper_b_id}/retrieve", headers=headers)
    assert retrieve_resp.status_code == 403

    status_resp = client.get(f"/api/v1/papers/{paper_b_id}/status", headers=headers)
    assert status_resp.status_code == 403


def test_unknown_paper_id_returns_404_not_403(client, centre_a):
    """
    Documents the existing, EXACT boundary (see module docstring):
    substituting a REAL other-centre paper ID yields 403 (Tests 2-3,
    above); substituting a UUID that was never registered as ANY
    paper at all yields 404 instead — the normal, pre-existing
    not-found path, which discloses only that the queried UUID does
    not correspond to a known paper (never a paper's subject, hash,
    schedule, or any other metadata). This is unchanged, documented
    Phase 3/4 behavior, not a Phase 6E-3 regression.
    """
    nonexistent_paper_id = str(uuid.uuid4())
    resp = client.get(f"/api/v1/papers/{nonexistent_paper_id}", headers=auth_header(centre_a))
    assert resp.status_code == 404


def test_centre_cannot_self_authorize_via_id_substitution(client, two_papers, centre_a, centre_b):
    """Even with a real, valid token, Centre A cannot call the
    authorize endpoint at all (Test 4) — confirmed again here using
    Centre B's own paper_id/centre_id pair specifically, to rule out
    any path where the endpoint might behave differently for an
    already-known pair vs. an unknown one."""
    _paper_a_id, paper_b_id = two_papers
    resp = client.post(
        f"/api/v1/papers/{paper_b_id}/authorize",
        json={"centre_id": str(centre_a.centre_id)},
        headers=auth_header(centre_a),
    )
    assert resp.status_code == 403
