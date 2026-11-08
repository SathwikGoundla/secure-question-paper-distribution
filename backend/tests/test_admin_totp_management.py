"""
Phase 7B — Admin TOTP enrollment management API.

GET /admin/totp/users (new, read-only) plus the unchanged Phase 7A POST /admin/totp/enrollment-codes.
Admin-only; shows enrollment STATE only; never secrets, codes, hashes, tokens or recovery-code material.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.audit_event import AuditEvent
from app.models.user import User
from app.models.user_totp import UserTotp
from app.services import totp_service
from tests.conftest import auth_header
from tests.test_idor_cross_centre import centre_a  # noqa: F401
from tests.test_totp_auth import API, _enroll, _events, _make_user, clock, totp_mode  # noqa: F401

URL = f"{API}/admin/totp/users"
ITEM_KEYS = {
    "user_id", "username", "role", "centre_name", "totp_status",
    "confirmed_at", "code_issued_at", "code_expires_at", "is_self",
}


def _list(client, principal, **params):
    return client.get(URL, params=params, headers=auth_header(principal))


def _by_name(body):
    return {i["username"]: i for i in body["items"]}


# ===========================================================================
# Authorization
# ===========================================================================


def test_only_admins_can_list_enrollment_status(client, admin_principal, auditor_principal, exam_centre_principal):
    assert client.get(URL).status_code == 401
    assert client.get(URL, headers={"Authorization": "Bearer not-a-token"}).status_code == 401
    assert _list(client, exam_centre_principal).status_code == 403
    assert _list(client, auditor_principal).status_code == 403
    assert _list(client, admin_principal).status_code == 200


def test_pre_auth_and_enrollment_tokens_are_not_accepted(client, admin_principal):
    from app.security.jwt_handler import create_enrollment_token, create_pre_auth_token

    for token in (create_pre_auth_token(admin_principal.user_id), create_enrollment_token(admin_principal.user_id)):
        assert client.get(URL, headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_centre_users_cannot_use_the_issue_endpoint_either(client, db_session, exam_centre_principal):
    target = _make_user(db_session)
    resp = client.post(f"{API}/admin/totp/enrollment-codes", json={"username": target.username}, headers=auth_header(exam_centre_principal))
    assert resp.status_code == 403
    assert db_session.get(UserTotp, target.user_id) is None


# ===========================================================================
# Content: statuses, minimal fields, no secrets
# ===========================================================================


def test_every_enrollment_state_is_reported(client, db_session, admin_principal, clock, totp_mode, monkeypatch):
    never = _make_user(db_session)
    issued = _make_user(db_session)
    totp_service.issue_enrollment_code(db_session, issued, issued_by=admin_principal.user_id)
    in_progress = _make_user(db_session)
    code, _ = totp_service.issue_enrollment_code(db_session, in_progress, issued_by=None)
    started = client.post(
        f"{API}/auth/totp/enroll/start", json={"username": in_progress.username, "password": "Totp-Test-Password-123!", "enrollment_code": code}
    )
    assert started.status_code == 200
    expired = _make_user(db_session)
    totp_service.issue_enrollment_code(db_session, expired, issued_by=None)
    row = db_session.get(UserTotp, expired.user_id)
    row.enrollment_code_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()
    locked = _make_user(db_session)
    totp_service.issue_enrollment_code(db_session, locked, issued_by=None)
    row = db_session.get(UserTotp, locked.user_id)
    row.enrollment_code_hash = None
    row.enrollment_code_expires_at = None
    db_session.commit()
    active = _make_user(db_session)
    _enroll(client, db_session, clock, active)

    body = _list(client, admin_principal, page_size=100).json()
    got = _by_name(body)
    assert got[never.username]["totp_status"] == "not_enrolled"
    assert got[issued.username]["totp_status"] == "code_issued"
    assert got[issued.username]["code_expires_at"] is not None and got[issued.username]["code_issued_at"] is not None
    assert got[in_progress.username]["totp_status"] == "enrollment_in_progress"
    assert got[expired.username]["totp_status"] == "code_expired"
    assert got[locked.username]["totp_status"] == "needs_new_code"
    assert got[active.username]["totp_status"] == "active"
    assert got[active.username]["confirmed_at"] is not None and got[active.username]["code_expires_at"] is None


def test_response_is_minimal_and_never_contains_secrets_or_hashes(client, db_session, admin_principal, clock, totp_mode):
    user = _make_user(db_session)
    secret = _enroll(client, db_session, clock, user)
    issued = _make_user(db_session)
    code, _ = totp_service.issue_enrollment_code(db_session, issued, issued_by=admin_principal.user_id)
    resp = _list(client, admin_principal, page_size=100)
    assert resp.status_code == 200
    for item in resp.json()["items"]:
        assert set(item) == ITEM_KEYS
    raw = resp.text
    row = db_session.get(UserTotp, issued.user_id)
    row2 = db_session.get(UserTotp, user.user_id)
    for forbidden in (secret, code, code.replace("-", ""), row.enrollment_code_hash, "password", "secret_encrypted", "recovery", "pre_auth", "$2b$"):
        assert forbidden not in raw, forbidden
    assert row2.secret_encrypted.hex() not in raw


def test_caller_is_flagged_and_roles_and_centres_are_shown(client, db_session, admin_principal, exam_centre_principal):
    body = _list(client, admin_principal, page_size=100).json()
    got = _by_name(body)
    assert got[admin_principal.username]["is_self"] is True
    assert got[admin_principal.username]["role"] == "Admin"
    assert got[exam_centre_principal.username]["is_self"] is False
    assert got[exam_centre_principal.username]["role"] == "Examination Centre"
    assert got[exam_centre_principal.username]["centre_name"]  # centre users carry their centre's name


def test_inactive_users_are_not_listed(client, db_session, admin_principal):
    gone = _make_user(db_session)
    db_session.query(User).filter(User.user_id == gone.user_id).update({"is_active": False})
    db_session.commit()
    assert gone.username not in _by_name(_list(client, admin_principal, page_size=100).json())


def test_ordering_pagination_and_filter(client, db_session, admin_principal):
    tag = uuid.uuid4().hex[:6]
    names = []
    for i in range(5):
        u = _make_user(db_session)
        db_session.query(User).filter(User.user_id == u.user_id).update({"username": f"zz_{tag}_{i}"})
        names.append(f"zz_{tag}_{i}")
    db_session.commit()
    full = _list(client, admin_principal, q=f"zz_{tag}", page_size=100).json()
    assert [i["username"] for i in full["items"]] == names and full["total"] == 5
    p1 = _list(client, admin_principal, q=f"zz_{tag}", page=1, page_size=2).json()
    p3 = _list(client, admin_principal, q=f"zz_{tag}", page=3, page_size=2).json()
    assert [i["username"] for i in p1["items"]] == names[:2] and p1["total"] == 5 and len(p3["items"]) == 1
    # LIKE wildcards in the filter are literal characters, not patterns.
    assert _list(client, admin_principal, q="%").json()["total"] == 0
    assert _list(client, admin_principal, page_size=101).status_code == 422
    assert _list(client, admin_principal, page=0).status_code == 422


# ===========================================================================
# Issuing codes (Phase 7A endpoint, now driven from the UI) — behaviour and audit
# ===========================================================================


def test_reissue_resets_an_active_user_and_is_attributed_to_the_admin(client, db_session, admin_principal, clock, totp_mode):
    user = _make_user(db_session)
    _enroll(client, db_session, clock, user)
    assert _by_name(_list(client, admin_principal, q=user.username).json())[user.username]["totp_status"] == "active"

    resp = client.post(f"{API}/admin/totp/enrollment-codes", json={"username": user.username}, headers=auth_header(admin_principal))
    assert resp.status_code == 201
    assert set(resp.json()) == {"username", "enrollment_code", "expires_at"}

    again = _by_name(_list(client, admin_principal, q=user.username).json())[user.username]
    assert again["totp_status"] == "code_issued" and again["confirmed_at"] is None
    db_session.expire_all()
    assert db_session.get(UserTotp, user.user_id).code_issued_by == admin_principal.user_id
    assert _events(db_session, AuditEvent, "TOTP_ENROLLMENT_CODE_ISSUED", admin_principal.user_id) == 1

    # The status list never shows the code that was just issued.
    assert resp.json()["enrollment_code"] not in _list(client, admin_principal, q=user.username).text


def test_admin_cannot_issue_for_self_and_unknown_users_are_generic(client, admin_principal):
    me = client.post(f"{API}/admin/totp/enrollment-codes", json={"username": admin_principal.username}, headers=auth_header(admin_principal))
    assert me.status_code == 403
    unknown = client.post(f"{API}/admin/totp/enrollment-codes", json={"username": "nobody_" + uuid.uuid4().hex[:6]}, headers=auth_header(admin_principal))
    assert unknown.status_code == 404
    assert unknown.json()["error"]["message"] == "The requested resource was not found."


def test_openapi_documents_the_new_endpoint(client):
    spec = client.get("/openapi.json").json()
    op = spec["paths"]["/api/v1/admin/totp/users"]["get"]
    assert op["summary"] and {"401", "403"} <= set(op["responses"])
    assert "AdminTotpUserItem" in spec["components"]["schemas"]
    assert "/api/v1/auth/recovery-code/verify" in spec["paths"]
    assert "/api/v1/auth/recovery-codes/regenerate" in spec["paths"]
