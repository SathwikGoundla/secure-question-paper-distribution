"""
Phase 6E-1 — automated OTP authentication regression tests.

The Phase 6E security audit found that OTP verification (SRS FR-002,
LLD API-02) was covered only by tests/test_phase2_manual.py, a
manual/live-server script that is NOT part of the normal `pytest`
run (it requires a real running uvicorn process and a real
PostgreSQL connection string — see that file's own docstring). A
regression in the OTP verification logic would therefore not have
been caught by `pytest`.

This file brings the full login -> OTP -> access-JWT chain, including
the Phase 6E-1 bounded-attempt-limiting behaviour added in
app/services/auth_service.verify_otp_step2, into the automated,
SQLite-or-PostgreSQL-backed suite (tests/conftest.py), using the same
real endpoints, real password hashing, and real JWT issuance as every
other test in this suite — nothing here mocks or bypasses application
code. The only thing captured is the OTP's plaintext value at the
point Phase 1's DevConsoleOTPProvider "delivers" it (logs it) — the
same, pre-existing, test-only technique tests/conftest.py already
uses for _login_and_capture_token, which this file's local helper
mirrors but WITHOUT auto-verifying, so each test can submit
deliberately wrong or delayed OTP guesses itself.
"""

import uuid
from datetime import datetime, timedelta, timezone

import app.services.auth_service as auth_service_module
from app.config import get_settings
from app.models.auth_session import AuthSession
from app.models.otp_code import OtpCode
from app.models.user import User
from app.security.password import hash_password
from tests.conftest import _get_or_create_role

import pytest


settings = get_settings()


# ---------------------------------------------------------------------------
# Local fixtures / helpers (deliberately NOT reusing conftest's
# admin_principal / exam_centre_principal / _login_and_capture_token,
# since those drive the OTP step to completion internally — these
# tests need to stop BEFORE that step to submit their own guesses).
# ---------------------------------------------------------------------------


@pytest.fixture()
def otp_user(db_session):
    """A single plain Admin-role user this file's tests log in as."""
    role = _get_or_create_role(db_session, "Admin")
    username = f"otpuser_{uuid.uuid4().hex[:8]}"
    password = "Test-OTP-Password-123!"
    user = User(username=username, password_hash=hash_password(password), role_id=role.role_id)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user, username, password


def _login(client, monkeypatch, username: str, password: str) -> tuple[str, str]:
    """
    Drives the real POST /auth/login and captures the OTP the
    (dev-only) provider would have delivered, WITHOUT calling
    /auth/otp/verify. Returns (pre_auth_token, correct_otp_value).
    """
    captured: dict[str, str] = {}
    original_deliver = auth_service_module._otp_provider.deliver

    def _capturing_deliver(user_identifier: str, otp: str) -> None:
        captured["otp"] = otp
        original_deliver(user_identifier, otp)

    monkeypatch.setattr(auth_service_module._otp_provider, "deliver", _capturing_deliver)

    resp = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["pre_auth_token"], captured["otp"]


def _verify(client, pre_auth_token: str, otp_code: str):
    return client.post(
        "/api/v1/auth/otp/verify",
        json={"pre_auth_token": pre_auth_token, "otp_code": otp_code},
    )


def _latest_otp_row(db_session, user_id: uuid.UUID) -> OtpCode:
    """
    Re-reads the latest OTP row for user_id through db_session. The
    row may have been committed by a DIFFERENT session object (the
    one the `client` fixture's request used) bound to the same
    engine — expire_all() forces a fresh SELECT instead of serving a
    stale in-memory copy.
    """
    db_session.expire_all()
    return (
        db_session.query(OtpCode)
        .filter(OtpCode.user_id == user_id)
        .order_by(OtpCode.created_at.desc())
        .first()
    )


WRONG_OTP = "000000"


# ---------------------------------------------------------------------------
# TEST 1 — successful OTP verification (the ordinary, happy path).
# ---------------------------------------------------------------------------


def test_successful_otp_verification_issues_access_token(client, monkeypatch, otp_user):
    user, username, password = otp_user
    pre_auth_token, otp_value = _login(client, monkeypatch, username, password)

    resp = _verify(client, pre_auth_token, otp_value)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "access_token" in body and body["access_token"]
    assert body["role"] == "Admin"

    me_resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me_resp.status_code == 200, me_resp.text
    assert me_resp.json()["username"] == username


# ---------------------------------------------------------------------------
# TEST 2 — one wrong OTP: rejected, challenge stays active, count increments.
# ---------------------------------------------------------------------------


def test_wrong_otp_is_rejected_and_increments_failed_attempts(client, db_session, monkeypatch, otp_user):
    user, username, password = otp_user
    pre_auth_token, otp_value = _login(client, monkeypatch, username, password)

    resp = _verify(client, pre_auth_token, WRONG_OTP)

    assert resp.status_code == 401, resp.text
    assert "access_token" not in resp.json()

    otp_row = _latest_otp_row(db_session, user.user_id)
    assert otp_row.is_used is False  # challenge remains active
    assert otp_row.failed_attempts == 1

    # The challenge is still genuinely usable with the CORRECT code —
    # proves one wrong guess alone does not lock anything out.
    resp2 = _verify(client, pre_auth_token, otp_value)
    assert resp2.status_code == 200, resp2.text


# ---------------------------------------------------------------------------
# TEST 3 — several wrong attempts below the max: all rejected, counted.
# ---------------------------------------------------------------------------


def test_multiple_wrong_attempts_are_each_rejected_and_counted(client, db_session, monkeypatch, otp_user):
    user, username, password = otp_user
    pre_auth_token, _otp_value = _login(client, monkeypatch, username, password)

    assert settings.OTP_MAX_ATTEMPTS >= 3, "test assumes at least 3 attempts are tolerated"

    for expected_count in (1, 2, 3):
        resp = _verify(client, pre_auth_token, WRONG_OTP)
        assert resp.status_code == 401, resp.text
        otp_row = _latest_otp_row(db_session, user.user_id)
        assert otp_row.failed_attempts == expected_count
        assert otp_row.is_used is False


# ---------------------------------------------------------------------------
# TEST 4 — reaching the configured maximum locks the challenge, even
# for the objectively CORRECT code.
# ---------------------------------------------------------------------------


def test_max_attempts_locks_the_challenge(client, db_session, monkeypatch, otp_user):
    user, username, password = otp_user
    pre_auth_token, otp_value = _login(client, monkeypatch, username, password)

    max_attempts = settings.OTP_MAX_ATTEMPTS
    for _ in range(max_attempts):
        resp = _verify(client, pre_auth_token, WRONG_OTP)
        assert resp.status_code == 401, resp.text

    otp_row = _latest_otp_row(db_session, user.user_id)
    assert otp_row.failed_attempts == max_attempts
    assert otp_row.is_used is False  # never legitimately used

    # The critical assertion: the CORRECT code, submitted AFTER the
    # challenge is exhausted, must still be rejected.
    resp = _verify(client, pre_auth_token, otp_value)
    assert resp.status_code == 401, resp.text
    assert "access_token" not in resp.json()


# ---------------------------------------------------------------------------
# TEST 5 — further attempts after lockout stay rejected; the counter
# does not become a bypass vector by growing without bound.
# ---------------------------------------------------------------------------


def test_attempts_after_lockout_remain_rejected(client, db_session, monkeypatch, otp_user):
    user, username, password = otp_user
    pre_auth_token, otp_value = _login(client, monkeypatch, username, password)

    max_attempts = settings.OTP_MAX_ATTEMPTS
    for _ in range(max_attempts):
        _verify(client, pre_auth_token, WRONG_OTP)

    # Several more attempts, mixing wrong and (the actually) correct codes.
    for code in (WRONG_OTP, otp_value, WRONG_OTP):
        resp = _verify(client, pre_auth_token, code)
        assert resp.status_code == 401, resp.text

    otp_row = _latest_otp_row(db_session, user.user_id)
    assert otp_row.is_used is False
    # The counter must not keep climbing forever once already locked —
    # it stays pinned at the configured maximum (see auth_service.py).
    assert otp_row.failed_attempts == max_attempts


# ---------------------------------------------------------------------------
# TEST 6 — the correct code, submitted BEFORE the max is reached,
# still authenticates normally. Proves the limiter does not break
# legitimate users who mistype once or twice.
# ---------------------------------------------------------------------------


def test_correct_otp_before_max_still_succeeds(client, db_session, monkeypatch, otp_user):
    user, username, password = otp_user
    pre_auth_token, otp_value = _login(client, monkeypatch, username, password)

    assert settings.OTP_MAX_ATTEMPTS >= 2, "test assumes room for at least one wrong guess"

    wrong_resp = _verify(client, pre_auth_token, WRONG_OTP)
    assert wrong_resp.status_code == 401, wrong_resp.text

    correct_resp = _verify(client, pre_auth_token, otp_value)
    assert correct_resp.status_code == 200, correct_resp.text
    body = correct_resp.json()
    assert "access_token" in body and body["access_token"]

    otp_row = _latest_otp_row(db_session, user.user_id)
    assert otp_row.is_used is True
    assert otp_row.failed_attempts == 1  # the one prior wrong guess, no more

    session_row = (
        db_session.query(AuthSession)
        .filter(AuthSession.user_id == user.user_id, AuthSession.revoked_at.is_(None))
        .first()
    )
    assert session_row is not None


# ---------------------------------------------------------------------------
# TEST 7 — an expired OTP remains rejected; attempt-limiting does not
# weaken or bypass the pre-existing expiry check.
# ---------------------------------------------------------------------------


def test_expired_otp_remains_rejected(client, db_session, monkeypatch, otp_user):
    user, username, password = otp_user
    pre_auth_token, otp_value = _login(client, monkeypatch, username, password)

    otp_row = _latest_otp_row(db_session, user.user_id)
    otp_row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()

    resp = _verify(client, pre_auth_token, otp_value)  # objectively correct code
    assert resp.status_code == 401, resp.text
    assert "access_token" not in resp.json()


# ---------------------------------------------------------------------------
# TEST 8 — an already-used OTP remains rejected on a second attempt;
# attempt-limiting does not weaken single-use enforcement.
# ---------------------------------------------------------------------------


def test_reused_otp_remains_rejected(client, monkeypatch, otp_user):
    user, username, password = otp_user
    pre_auth_token, otp_value = _login(client, monkeypatch, username, password)

    first = _verify(client, pre_auth_token, otp_value)
    assert first.status_code == 200, first.text

    second = _verify(client, pre_auth_token, otp_value)
    assert second.status_code == 401, second.text
    assert "access_token" not in second.json()


# ---------------------------------------------------------------------------
# TEST 9 — starting a new login after one challenge is exhausted
# issues a genuinely fresh, independently-usable challenge; the old,
# locked challenge stays dead.
# ---------------------------------------------------------------------------


def test_new_login_after_lockout_creates_a_fresh_usable_challenge(client, db_session, monkeypatch, otp_user):
    user, username, password = otp_user

    old_pre_auth_token, old_otp_value = _login(client, monkeypatch, username, password)
    max_attempts = settings.OTP_MAX_ATTEMPTS
    for _ in range(max_attempts):
        _verify(client, old_pre_auth_token, WRONG_OTP)

    # Old challenge really is dead now.
    dead_resp = _verify(client, old_pre_auth_token, old_otp_value)
    assert dead_resp.status_code == 401, dead_resp.text

    new_pre_auth_token, new_otp_value = _login(client, monkeypatch, username, password)
    assert new_pre_auth_token != old_pre_auth_token
    assert new_otp_value != old_otp_value or True  # values CAN coincide by chance; token difference is what matters

    fresh_resp = _verify(client, new_pre_auth_token, new_otp_value)
    assert fresh_resp.status_code == 200, fresh_resp.text
    assert "access_token" in fresh_resp.json()

    # The old, exhausted challenge still cannot be resurrected afterwards.
    still_dead_resp = _verify(client, old_pre_auth_token, old_otp_value)
    assert still_dead_resp.status_code == 401, still_dead_resp.text


# ---------------------------------------------------------------------------
# TEST 10 — a failed OTP verification response never leaks the
# correct code, its hash, a token, or internal error detail.
# ---------------------------------------------------------------------------


def test_invalid_otp_response_does_not_leak_secrets(client, db_session, monkeypatch, otp_user):
    user, username, password = otp_user
    pre_auth_token, otp_value = _login(client, monkeypatch, username, password)

    resp = _verify(client, pre_auth_token, WRONG_OTP)
    assert resp.status_code == 401

    body = resp.json()
    # Exact, minimal, documented shape (app/exceptions/handlers.py) —
    # nothing beyond a generic message and status code.
    assert body == {"error": {"message": "Invalid or expired OTP.", "status_code": 401}}

    raw_text = resp.text
    otp_row = _latest_otp_row(db_session, user.user_id)

    assert otp_value not in raw_text  # the correct OTP itself
    assert otp_row.otp_hash not in raw_text  # the stored hash
    assert password not in raw_text
    assert pre_auth_token not in raw_text
    # No JWT-shaped token (three dot-separated segments) anywhere in the body.
    assert raw_text.count(".") < 2 or "." not in body.get("error", {}).get("message", "")

    # The lockout path (exhausted-challenge rejection) must be exactly
    # as quiet — same message, same shape, no "you are locked out"
    # oracle that would tell an attacker they are on the right track.
    max_attempts = settings.OTP_MAX_ATTEMPTS
    for _ in range(max_attempts - 1):
        _verify(client, pre_auth_token, WRONG_OTP)
    locked_resp = _verify(client, pre_auth_token, otp_value)  # now exhausted
    assert locked_resp.status_code == 401
    assert locked_resp.json() == {"error": {"message": "Invalid or expired OTP.", "status_code": 401}}
