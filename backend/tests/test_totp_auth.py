"""
Phase 7A — TOTP second factor (RFC 6238 via pyotp), enrollment and recovery.

The legacy suite runs with AUTH_SECOND_FACTOR=dev_console (tests/conftest.py).
These tests switch to "totp" per test with monkeypatch on the cached Settings
object (every new code path reads get_settings() at call time).

Time is controlled through app.security.totp.current_time so replay, window
and expiry behaviour are deterministic; codes are computed with pyotp from
the secret returned by the enrollment endpoint, exactly as an authenticator
app would.
"""

import base64
import logging
import os
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

import pyotp
import pytest
from pydantic import ValidationError
from sqlalchemy.orm import sessionmaker

import app.api.v1.auth as auth_router
import app.services.auth_service as auth_service_module
from app.config import Settings, get_settings
from app.models.audit_event import AuditEvent
from app.models.auth_session import AuthSession
from app.models.otp_code import OtpCode
from app.models.role import Role
from app.models.security_event import SecurityEvent
from app.models.user import User
from app.models.user_totp import UserTotp
from app.security import totp as totp_lib
from app.security.password import hash_password
from app.services import totp_service
from tests.conftest import _get_or_create_role, auth_header

API = "/api/v1"
PASSWORD = "Totp-Test-Password-123!"


class Clock:
    def __init__(self) -> None:
        self.t = float(int(time.time() // 30) * 30 + 5)  # inside a step, far from a boundary

    def advance(self, seconds: float) -> None:
        self.t += seconds


@pytest.fixture()
def clock(monkeypatch) -> Clock:
    c = Clock()
    monkeypatch.setattr(totp_lib, "current_time", lambda: c.t)
    return c


@pytest.fixture()
def totp_mode(monkeypatch):
    monkeypatch.setattr(get_settings(), "AUTH_SECOND_FACTOR", "totp")


def _make_user(db_session, role_name: str = "Auditor") -> User:
    role = _get_or_create_role(db_session, role_name)
    user = User(username=f"u_{uuid.uuid4().hex[:10]}", password_hash=hash_password(PASSWORD), role_id=role.role_id)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _code(secret: str, clock: Clock, step_offset: int = 0) -> str:
    return pyotp.TOTP(secret).at(clock.t + 30 * step_offset)


def _start(client, username, code, password=PASSWORD):
    return client.post(
        f"{API}/auth/totp/enroll/start",
        json={"username": username, "password": password, "enrollment_code": code},
    )


def _enroll(client, db_session, clock, user) -> str:
    """Full enrollment as a user would do it. Returns the TOTP secret (as the authenticator app holds it)."""
    code, _ = totp_service.issue_enrollment_code(db_session, user, issued_by=None)
    started = _start(client, user.username, code)
    assert started.status_code == 200, started.text
    secret = started.json()["secret"]
    confirm = client.post(
        f"{API}/auth/totp/enroll/confirm",
        json={"enrollment_token": started.json()["enrollment_token"], "otp_code": _code(secret, clock)},
    )
    assert confirm.status_code == 200, confirm.text
    clock.advance(30)  # the confirmation code's step is consumed; sign in with the next step's code
    return secret


def _login(client, user, password=PASSWORD):
    auth_router._login_limiter.reset()  # these tests are not about login throttling (see the dedicated tests)
    return client.post(f"{API}/auth/login", json={"username": user.username, "password": password})


def _verify(client, pre_auth_token, code):
    return client.post(f"{API}/auth/otp/verify", json={"pre_auth_token": pre_auth_token, "otp_code": code})


def _sign_in(client, user, secret, clock):
    r = _login(client, user)
    assert r.status_code == 200, r.text
    return _verify(client, r.json()["pre_auth_token"], _code(secret, clock))


def _events(db_session, model, event_type, user_id=None) -> int:
    db_session.expire_all()
    q = db_session.query(model).filter(model.event_type == event_type)
    if user_id is not None:
        q = q.filter(model.actor_id == user_id)
    return q.count()


# ===========================================================================
# Configuration / library-level
# ===========================================================================


def test_totp_is_the_default_second_factor_and_config_is_validated():
    assert Settings.model_fields["AUTH_SECOND_FACTOR"].default == "totp"
    assert Settings.model_fields["TOTP_VALID_WINDOW"].default == 1
    assert Settings(_env_file=None, AUTH_SECOND_FACTOR="TOTP").AUTH_SECOND_FACTOR == "totp"
    with pytest.raises(ValidationError):
        Settings(_env_file=None, AUTH_SECOND_FACTOR="sms")
    for bad in (-1, 3, 10):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, TOTP_VALID_WINDOW=bad)


@pytest.mark.parametrize(
    "key,reason",
    [("", "not configured"), ("not base64 !!", "base64"), (base64.b64encode(b"short").decode(), "32 bytes")],
)
def test_missing_or_invalid_encryption_key_is_refused(monkeypatch, key, reason):
    monkeypatch.setattr(get_settings(), "TOTP_ENCRYPTION_KEY", key)
    with pytest.raises(totp_lib.TotpConfigError) as exc:
        totp_lib.load_encryption_key()
    assert reason in str(exc.value)
    assert key not in str(exc.value) or key == ""  # the value is never echoed


def test_encryption_key_must_differ_from_the_paper_master_key(monkeypatch):
    shared = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setattr(get_settings(), "TOTP_ENCRYPTION_KEY", shared)
    monkeypatch.setattr(get_settings(), "QUESTION_PAPER_MASTER_KEY", shared)
    with pytest.raises(totp_lib.TotpConfigError) as exc:
        totp_lib.load_encryption_key()
    assert "differ" in str(exc.value)


def test_secret_encryption_roundtrip_and_binding_to_the_user():
    user_id, other = uuid.uuid4(), uuid.uuid4()
    secret = totp_lib.generate_secret()
    blob = totp_lib.encrypt_secret(secret, user_id)
    assert secret.encode() not in blob
    assert totp_lib.decrypt_secret(blob, user_id) == secret
    assert totp_lib.encrypt_secret(secret, user_id) != blob  # fresh random nonce each time
    with pytest.raises(totp_lib.TotpDecryptError):
        totp_lib.decrypt_secret(blob, other)  # ciphertext cannot be moved to another account
    tampered = bytearray(blob)
    tampered[-1] ^= 1
    with pytest.raises(totp_lib.TotpDecryptError):
        totp_lib.decrypt_secret(bytes(tampered), user_id)
    with pytest.raises(totp_lib.TotpDecryptError):
        totp_lib.decrypt_secret(b"", user_id)


def test_match_code_window_and_malformed_input():
    secret = totp_lib.generate_secret()
    t = float(int(time.time() // 30) * 30 + 5)
    totp = pyotp.TOTP(secret)
    step = int(t // 30)
    assert totp_lib.match_code(secret, totp.at(t), 1, now=t) == step
    assert totp_lib.match_code(secret, totp.at(t - 30), 1, now=t) == step - 1
    assert totp_lib.match_code(secret, totp.at(t + 30), 1, now=t) == step + 1
    assert totp_lib.match_code(secret, totp.at(t - 60), 1, now=t) is None
    assert totp_lib.match_code(secret, totp.at(t + 60), 1, now=t) is None
    assert totp_lib.match_code(secret, totp.at(t - 30), 0, now=t) is None  # window 0 = current step only
    for bad in ("", "12345", "1234567", "abcdef", "12 456", "１２３４５６", None, 123456):
        assert totp_lib.match_code(secret, bad, 1, now=t) is None


def test_provisioning_uri_is_a_standard_otpauth_uri():
    secret = totp_lib.generate_secret()
    uri = totp_lib.provisioning_uri(secret, "alice")
    assert uri.startswith("otpauth://totp/")
    assert f"secret={secret}" in uri and "issuer=QPaper" in uri and "alice" in uri
    assert totp_lib.qr_svg_data_uri(uri).startswith("data:image/svg+xml")


# ===========================================================================
# Admin / operator issuing enrollment codes
# ===========================================================================


def test_admin_issues_a_one_time_code_stored_only_as_a_hash(client, db_session, admin_principal, totp_mode):
    user = _make_user(db_session)
    resp = client.post(f"{API}/admin/totp/enrollment-codes", json={"username": user.username}, headers=auth_header(admin_principal))
    assert resp.status_code == 201, resp.text
    body = resp.json()
    code = body["enrollment_code"]
    assert len(code.replace("-", "")) == 12 and body["username"] == user.username
    db_session.expire_all()
    row = db_session.get(UserTotp, user.user_id)
    assert row.enrollment_code_hash and code.replace("-", "") not in row.enrollment_code_hash
    assert row.code_issued_by == admin_principal.user_id
    assert row.secret_encrypted is None and row.confirmed_at is None
    assert _events(db_session, AuditEvent, "TOTP_ENROLLMENT_CODE_ISSUED", admin_principal.user_id) == 1


def test_issuing_requires_admin_and_rejects_self_and_unknown_users(client, db_session, admin_principal, auditor_principal, totp_mode):
    url = f"{API}/admin/totp/enrollment-codes"
    target = _make_user(db_session)
    assert client.post(url, json={"username": target.username}).status_code == 401
    assert client.post(url, json={"username": target.username}, headers=auth_header(auditor_principal)).status_code == 403
    self_reset = client.post(url, json={"username": admin_principal.username}, headers=auth_header(admin_principal))
    assert self_reset.status_code == 403
    unknown = client.post(url, json={"username": "no_such_user_xyz"}, headers=auth_header(admin_principal))
    assert unknown.status_code == 404
    db_session.expire_all()
    assert db_session.get(UserTotp, admin_principal.user_id) is None  # self-reset created nothing


# ===========================================================================
# Enrollment
# ===========================================================================


def test_full_enrollment_then_login_issues_a_jwt(client, db_session, clock, totp_mode):
    user = _make_user(db_session)
    secret = _enroll(client, db_session, clock, user)

    login = _login(client, user)
    assert login.status_code == 200
    assert login.json() == {"otp_required": True, "pre_auth_token": login.json()["pre_auth_token"], "second_factor": "totp"}
    verified = _verify(client, login.json()["pre_auth_token"], _code(secret, clock))
    assert verified.status_code == 200, verified.text
    me = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {verified.json()['access_token']}"})
    assert me.status_code == 200 and me.json()["username"] == user.username


def test_enrollment_start_returns_secret_once_and_is_not_active_until_confirmed(client, db_session, clock, totp_mode):
    user = _make_user(db_session)
    code, _ = totp_service.issue_enrollment_code(db_session, user, issued_by=None)
    started = _start(client, user.username, code)
    assert started.status_code == 200, started.text
    body = started.json()
    assert set(body) == {"enrollment_token", "provisioning_uri", "secret", "qr_svg_data_uri", "expires_in_seconds"}
    assert body["provisioning_uri"].startswith("otpauth://totp/") and body["qr_svg_data_uri"].startswith("data:image/svg+xml")

    # Started but unconfirmed: NOT a usable second factor.
    login = _login(client, user)
    assert login.status_code == 403
    assert "pre_auth_token" not in login.text

    # Wrong confirmation code does not activate it.
    bad = client.post(f"{API}/auth/totp/enroll/confirm", json={"enrollment_token": body["enrollment_token"], "otp_code": "000000"})
    assert bad.status_code == 401
    assert _login(client, user).status_code == 403


def test_secret_is_encrypted_at_rest_and_never_returned_again(client, db_session, clock, totp_mode, caplog):
    user = _make_user(db_session)
    with caplog.at_level(logging.DEBUG):
        code, _ = totp_service.issue_enrollment_code(db_session, user, issued_by=None)
        started = _start(client, user.username, code)
        secret = started.json()["secret"]
        confirm = client.post(
            f"{API}/auth/totp/enroll/confirm",
            json={"enrollment_token": started.json()["enrollment_token"], "otp_code": _code(secret, clock)},
        )
        clock.advance(30)
        login = _login(client, user)
        verified = _verify(client, login.json()["pre_auth_token"], _code(secret, clock))
    assert confirm.status_code == 200 and verified.status_code == 200

    db_session.expire_all()
    row = db_session.get(UserTotp, user.user_id)
    assert row.secret_encrypted is not None and secret.encode() not in row.secret_encrypted
    assert totp_lib.decrypt_secret(row.secret_encrypted, user.user_id) == secret

    # The secret, the enrollment code and the TOTP codes never appear in any later response or any log.
    for resp in (confirm, login, verified):
        assert secret not in resp.text
        assert code not in resp.text and code.replace("-", "") not in resp.text
    assert secret not in caplog.text and code not in caplog.text and code.replace("-", "") not in caplog.text
    assert _code(secret, clock) not in caplog.text
    # Starting again with the consumed code is impossible, so the secret cannot be fetched a second time.
    assert _start(client, user.username, code).status_code == 401


def test_every_enrollment_start_failure_returns_the_same_generic_401(client, db_session, totp_mode):
    user = _make_user(db_session)
    code, _ = totp_service.issue_enrollment_code(db_session, user, issued_by=None)
    other = _make_user(db_session)  # exists, but has no code at all
    responses = [
        _start(client, user.username, "AAAA-AAAA-AAAA"),  # wrong code
        _start(client, user.username, code, password="wrong-password"),  # wrong password
        _start(client, "nobody_" + uuid.uuid4().hex[:6], code),  # unknown user
        _start(client, other.username, code),  # user with no issued code
    ]
    assert {r.status_code for r in responses} == {401}
    assert len({r.text for r in responses}) == 1
    assert "Invalid username, password or enrollment code" in responses[0].text


def test_enrollment_locks_after_too_many_wrong_codes(client, db_session, totp_mode, monkeypatch):
    monkeypatch.setattr(get_settings(), "TOTP_ENROLLMENT_MAX_ATTEMPTS", 3)
    user = _make_user(db_session)
    code, _ = totp_service.issue_enrollment_code(db_session, user, issued_by=None)
    for _ in range(3):
        assert _start(client, user.username, "AAAA-AAAA-AAAA").status_code == 401
    # The right code no longer works: the pending enrollment was destroyed; a new code is required.
    assert _start(client, user.username, code).status_code == 401
    assert _events(db_session, SecurityEvent, "TOTP_ENROLLMENT_LOCKED", user.user_id) == 1
    new_code, _ = totp_service.issue_enrollment_code(db_session, user, issued_by=None)
    assert _start(client, user.username, new_code).status_code == 200


def test_expired_enrollment_code_is_refused(client, db_session, totp_mode):
    user = _make_user(db_session)
    code, _ = totp_service.issue_enrollment_code(db_session, user, issued_by=None)
    row = db_session.get(UserTotp, user.user_id)
    row.enrollment_code_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()
    assert _start(client, user.username, code).status_code == 401


def test_confirmation_locks_after_too_many_wrong_codes(client, db_session, clock, totp_mode, monkeypatch):
    monkeypatch.setattr(get_settings(), "TOTP_ENROLLMENT_MAX_ATTEMPTS", 2)
    user = _make_user(db_session)
    code, _ = totp_service.issue_enrollment_code(db_session, user, issued_by=None)
    started = _start(client, user.username, code).json()
    for _ in range(2):
        assert client.post(f"{API}/auth/totp/enroll/confirm", json={"enrollment_token": started["enrollment_token"], "otp_code": "111111"}).status_code == 401
    ok_code = _code(started["secret"], clock)
    late = client.post(f"{API}/auth/totp/enroll/confirm", json={"enrollment_token": started["enrollment_token"], "otp_code": ok_code})
    assert late.status_code == 401  # locked: the correct code no longer activates it
    assert _login(client, user).status_code == 403


def test_only_an_enrollment_token_can_confirm_and_it_authorizes_nothing_else(client, db_session, admin_principal, clock, totp_mode):
    user = _make_user(db_session)
    code, _ = totp_service.issue_enrollment_code(db_session, user, issued_by=None)
    started = _start(client, user.username, code).json()
    token, secret = started["enrollment_token"], started["secret"]

    # A session JWT or a pre-auth token is not an enrollment token.
    wrong_kinds = [admin_principal.access_token, auth_service_module.create_pre_auth_token(user.user_id), "garbage"]
    for bad in wrong_kinds:
        r = client.post(f"{API}/auth/totp/enroll/confirm", json={"enrollment_token": bad, "otp_code": _code(secret, clock)})
        assert r.status_code == 401
    # The enrollment token is rejected on every protected endpoint.
    assert client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    assert client.get(f"{API}/papers", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    assert client.post(f"{API}/auth/logout", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    # And it issues no session itself.
    ok = client.post(f"{API}/auth/totp/enroll/confirm", json={"enrollment_token": token, "otp_code": _code(secret, clock)})
    assert ok.status_code == 200 and set(ok.json()) == {"enrolled"}


def test_enrollment_endpoints_are_rate_limited(client, db_session, totp_mode):
    limiter = auth_router._enroll_start_limiter
    limiter.reset()
    user = _make_user(db_session)
    statuses = [_start(client, user.username, "AAAA-AAAA-AAAA").status_code for _ in range(limiter._limit + 1)]
    assert statuses[-1] == 429
    assert set(statuses[:-1]) == {401}
    limiter.reset()


def test_enrollment_fails_safely_without_valid_security_configuration(client, db_session, totp_mode, monkeypatch):
    user = _make_user(db_session)
    code, _ = totp_service.issue_enrollment_code(db_session, user, issued_by=None)
    monkeypatch.setattr(get_settings(), "TOTP_ENCRYPTION_KEY", "")
    resp = _start(client, user.username, code)
    assert resp.status_code == 503
    assert "secret" not in resp.text.lower() and "TOTP_ENCRYPTION_KEY" not in resp.text
    db_session.expire_all()
    assert db_session.get(UserTotp, user.user_id).secret_encrypted is None  # nothing was generated or stored


# ===========================================================================
# Login with TOTP
# ===========================================================================


def test_not_enrolled_user_gets_guidance_and_no_challenge_or_token(client, db_session, totp_mode):
    user = _make_user(db_session)
    resp = _login(client, user)
    assert resp.status_code == 403
    assert "enrollment code" in resp.json()["error"]["message"]
    assert "pre_auth_token" not in resp.text and "access_token" not in resp.text
    assert db_session.query(OtpCode).filter(OtpCode.user_id == user.user_id).count() == 0
    assert _events(db_session, SecurityEvent, "LOGIN_BLOCKED_NOT_ENROLLED", user.user_id) == 1


def test_wrong_password_is_still_a_generic_401(client, db_session, clock, totp_mode):
    user = _make_user(db_session)
    _enroll(client, db_session, clock, user)
    resp = _login(client, user, password="wrong-password-1!")
    assert resp.status_code == 401 and "pre_auth_token" not in resp.text


def test_wrong_and_malformed_codes_never_produce_a_jwt(client, db_session, clock, totp_mode):
    user = _make_user(db_session)
    secret = _enroll(client, db_session, clock, user)
    good = _code(secret, clock)
    wrong = "000000" if good != "000000" else "111111"
    for bad in (wrong, "12345", "1234567", "abcdef", "12 3456", "000000000", "0"):
        login = _login(client, user)
        resp = _verify(client, login.json()["pre_auth_token"], bad)
        assert resp.status_code == 401, bad
        assert "access_token" not in resp.text
        assert resp.json()["error"]["message"] == "Invalid or expired OTP."  # one generic message for every cause


def test_pre_auth_token_alone_authorizes_nothing(client, db_session, clock, totp_mode):
    user = _make_user(db_session)
    _enroll(client, db_session, clock, user)
    pre = _login(client, user).json()["pre_auth_token"]
    for path in ("/auth/me", "/papers", "/admin/dashboard/summary", "/audit/logs"):
        assert client.get(f"{API}{path}", headers={"Authorization": f"Bearer {pre}"}).status_code == 401, path


def test_expired_challenge_is_rejected_even_with_a_correct_code(client, db_session, clock, totp_mode):
    user = _make_user(db_session)
    secret = _enroll(client, db_session, clock, user)
    login = _login(client, user)
    row = db_session.query(OtpCode).filter(OtpCode.user_id == user.user_id).order_by(OtpCode.created_at.desc()).first()
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()
    resp = _verify(client, login.json()["pre_auth_token"], _code(secret, clock))
    assert resp.status_code == 401


def test_a_consumed_challenge_cannot_be_reused(client, db_session, clock, totp_mode):
    user = _make_user(db_session)
    secret = _enroll(client, db_session, clock, user)
    pre = _login(client, user).json()["pre_auth_token"]
    assert _verify(client, pre, _code(secret, clock)).status_code == 200
    clock.advance(30)
    again = _verify(client, pre, _code(secret, clock))  # valid NEW code, but the challenge is spent
    assert again.status_code == 401


def test_replay_of_an_accepted_code_is_rejected_within_its_window(client, db_session, clock, totp_mode):
    user = _make_user(db_session)
    secret = _enroll(client, db_session, clock, user)
    code = _code(secret, clock)
    first = _verify(client, _login(client, user).json()["pre_auth_token"], code)
    assert first.status_code == 200
    replay = _verify(client, _login(client, user).json()["pre_auth_token"], code)  # same code, fresh challenge
    assert replay.status_code == 401 and "access_token" not in replay.text
    assert _events(db_session, SecurityEvent, "TOTP_REPLAY_REJECTED", user.user_id) == 1
    # Also the adjacent-step code that is still inside the window cannot be used to go "back in time".
    older = _verify(client, _login(client, user).json()["pre_auth_token"], _code(secret, clock, -1))
    assert older.status_code == 401
    # A genuinely newer code works.
    clock.advance(30)
    assert _verify(client, _login(client, user).json()["pre_auth_token"], _code(secret, clock)).status_code == 200


def test_the_enrollment_confirmation_code_cannot_be_replayed_as_a_login_code(client, db_session, clock, totp_mode):
    user = _make_user(db_session)
    code, _ = totp_service.issue_enrollment_code(db_session, user, issued_by=None)
    started = _start(client, user.username, code).json()
    confirm_code = _code(started["secret"], clock)
    assert client.post(f"{API}/auth/totp/enroll/confirm", json={"enrollment_token": started["enrollment_token"], "otp_code": confirm_code}).status_code == 200
    resp = _verify(client, _login(client, user).json()["pre_auth_token"], confirm_code)  # same time step
    assert resp.status_code == 401


def test_clock_skew_is_bounded_to_the_configured_window(client, db_session, clock, totp_mode, monkeypatch):
    user = _make_user(db_session)
    secret = _enroll(client, db_session, clock, user)
    # +/-1 step accepted, +/-2 steps rejected (default window 1).
    far = _verify(client, _login(client, user).json()["pre_auth_token"], _code(secret, clock, 2))
    assert far.status_code == 401
    near = _verify(client, _login(client, user).json()["pre_auth_token"], _code(secret, clock, 1))
    assert near.status_code == 200
    # Window 0: only the current step.
    monkeypatch.setattr(get_settings(), "TOTP_VALID_WINDOW", 0)
    clock.advance(90)
    off_by_one = _verify(client, _login(client, user).json()["pre_auth_token"], _code(secret, clock, 1))
    assert off_by_one.status_code == 401
    exact = _verify(client, _login(client, user).json()["pre_auth_token"], _code(secret, clock))
    assert exact.status_code == 200


def test_failed_attempts_lock_the_challenge_even_for_the_correct_code(client, db_session, clock, totp_mode, monkeypatch):
    monkeypatch.setattr(auth_service_module.settings, "OTP_MAX_ATTEMPTS", 3)
    user = _make_user(db_session)
    secret = _enroll(client, db_session, clock, user)
    pre = _login(client, user).json()["pre_auth_token"]
    good = _code(secret, clock)
    wrong = "000000" if good != "000000" else "111111"
    for _ in range(3):
        assert _verify(client, pre, wrong).status_code == 401
    assert _verify(client, pre, good).status_code == 401  # locked challenge rejects even the right code
    assert _events(db_session, SecurityEvent, "OTP_CHALLENGE_LOCKED", user.user_id) == 1
    # A fresh login creates a fresh challenge that works. (SQLite's CURRENT_TIMESTAMP has one-second
    # resolution, so wait out the second to keep "latest challenge" unambiguous; PostgreSQL does not need it.)
    time.sleep(1.1)
    assert _verify(client, _login(client, user).json()["pre_auth_token"], good).status_code == 200


def test_otp_verify_is_rate_limited_per_challenge(client, db_session, clock, totp_mode):
    user = _make_user(db_session)
    secret = _enroll(client, db_session, clock, user)
    pre = _login(client, user).json()["pre_auth_token"]
    limit = auth_router._otp_limiter._limit
    statuses = [_verify(client, pre, "000000").status_code for _ in range(limit + 2)]
    assert 429 in statuses
    assert "access_token" not in str(statuses)


def test_second_factor_method_claim_must_match_the_configured_method(client, db_session, clock, totp_mode, monkeypatch):
    user = _make_user(db_session)
    secret = _enroll(client, db_session, clock, user)
    totp_pre = _login(client, user).json()["pre_auth_token"]
    legacy_pre = auth_service_module.create_pre_auth_token(user.user_id)  # claims mfa="dev_console"
    # A leftover development challenge is dead while TOTP is the configured method.
    assert _verify(client, legacy_pre, "123456").status_code == 401
    # And a TOTP challenge is dead if the deployment switches back to the development flow.
    monkeypatch.setattr(get_settings(), "AUTH_SECOND_FACTOR", "dev_console")
    assert _verify(client, totp_pre, _code(secret, clock)).status_code == 401


def test_totp_login_never_uses_or_logs_the_development_otp_provider(client, db_session, clock, totp_mode, monkeypatch, caplog):
    def _boom(*a, **k):
        raise AssertionError("the development OTP provider must not be used in totp mode")

    monkeypatch.setattr(auth_service_module._otp_provider, "deliver", _boom)
    monkeypatch.setattr(get_settings(), "APP_ENV", "production")
    monkeypatch.setattr(get_settings(), "OTP_DEV_LOG_ENABLED", True)  # even if someone sets the dev flag
    user = _make_user(db_session)
    with caplog.at_level(logging.DEBUG):
        secret = _enroll(client, db_session, clock, user)
        resp = _sign_in(client, user, secret, clock)
    assert resp.status_code == 200
    assert "DEV-ONLY" not in caplog.text and "otp=" not in caplog.text


@pytest.mark.parametrize("bad_key", ["", "%%%", base64.b64encode(b"short").decode()])
def test_login_fails_safely_with_missing_or_invalid_key(client, db_session, clock, totp_mode, monkeypatch, bad_key):
    user = _make_user(db_session)
    _enroll(client, db_session, clock, user)
    monkeypatch.setattr(get_settings(), "TOTP_ENCRYPTION_KEY", bad_key)
    resp = _login(client, user)
    assert resp.status_code == 503
    assert resp.json()["error"]["message"] == "Authenticator sign-in is temporarily unavailable. Please contact the administrator."
    assert "pre_auth_token" not in resp.text
    assert db_session.query(OtpCode).filter(OtpCode.user_id == user.user_id).count() == 0


def test_a_pre_auth_token_cannot_be_verified_if_the_key_disappears(client, db_session, clock, totp_mode, monkeypatch):
    user = _make_user(db_session)
    secret = _enroll(client, db_session, clock, user)
    pre = _login(client, user).json()["pre_auth_token"]
    monkeypatch.setattr(get_settings(), "TOTP_ENCRYPTION_KEY", "")
    resp = _verify(client, pre, _code(secret, clock))
    assert resp.status_code == 503 and "access_token" not in resp.text


def test_a_stored_secret_that_cannot_be_decrypted_never_authenticates(client, db_session, clock, totp_mode, monkeypatch):
    user = _make_user(db_session)
    secret = _enroll(client, db_session, clock, user)
    row = db_session.get(UserTotp, user.user_id)
    row.secret_encrypted = totp_lib.encrypt_secret(totp_lib.generate_secret(), uuid.uuid4())  # bound to another user
    db_session.commit()
    resp = _sign_in(client, user, secret, clock)
    assert resp.status_code == 401


# ===========================================================================
# Recovery (lost authenticator) and existing-session behaviour
# ===========================================================================


def test_admin_reenrollment_replaces_the_authenticator_and_revokes_sessions(client, db_session, admin_principal, clock, totp_mode):
    user = _make_user(db_session)
    old_secret = _enroll(client, db_session, clock, user)
    signed_in = _sign_in(client, user, old_secret, clock)
    old_jwt = signed_in.json()["access_token"]
    assert client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {old_jwt}"}).status_code == 200

    issue = client.post(f"{API}/admin/totp/enrollment-codes", json={"username": user.username}, headers=auth_header(admin_principal))
    assert issue.status_code == 201

    # The old session is revoked and the old authenticator is gone immediately.
    assert client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {old_jwt}"}).status_code == 401
    assert _login(client, user).status_code == 403

    started = _start(client, user.username, issue.json()["enrollment_code"])
    assert started.status_code == 200
    new_secret = started.json()["secret"]
    assert new_secret != old_secret
    clock.advance(30)
    assert client.post(f"{API}/auth/totp/enroll/confirm", json={"enrollment_token": started.json()["enrollment_token"], "otp_code": _code(new_secret, clock)}).status_code == 200
    clock.advance(30)
    assert _sign_in(client, user, new_secret, clock).status_code == 200
    clock.advance(30)
    assert _sign_in(client, user, old_secret, clock).status_code == 401  # the old device no longer works


def test_logout_and_session_revocation_still_work_after_totp_login(client, db_session, clock, totp_mode):
    user = _make_user(db_session)
    secret = _enroll(client, db_session, clock, user)
    token = _sign_in(client, user, secret, clock).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    assert client.post(f"{API}/auth/logout", headers=h).status_code == 200
    assert client.get(f"{API}/auth/me", headers=h).status_code == 401
    db_session.expire_all()
    assert db_session.query(AuthSession).filter(AuthSession.user_id == user.user_id, AuthSession.revoked_at.isnot(None)).count() >= 1


def test_operator_cli_bootstraps_an_enrollment_without_any_login(client, db_session, clock, totp_mode, monkeypatch, capsys):
    from scripts import totp_enroll_code

    user = _make_user(db_session, "Admin")
    monkeypatch.setattr(sys, "argv", ["totp_enroll_code", "--username", user.username])
    totp_enroll_code.main()
    out = capsys.readouterr().out
    code = out.split(": ", 1)[1].split()[0]
    assert len(code.replace("-", "")) == 12
    assert _events(db_session, AuditEvent, "TOTP_ENROLLMENT_CODE_ISSUED") >= 1
    started = _start(client, user.username, code)
    assert started.status_code == 200
    db_session.expire_all()
    assert db_session.get(UserTotp, user.user_id).code_issued_by is None  # server operator, not an Admin account

    monkeypatch.setattr(sys, "argv", ["totp_enroll_code", "--username", "does_not_exist"])
    with pytest.raises(SystemExit):
        totp_enroll_code.main()


# ===========================================================================
# PostgreSQL-only: real concurrency
# ===========================================================================


def test_concurrent_verifications_of_one_code_yield_exactly_one_session(db_engine, db_session, clock, client, totp_mode):
    if db_engine.dialect.name != "postgresql":
        pytest.skip("row-level locking is only enforced by PostgreSQL")
    user = _make_user(db_session)
    secret = _enroll(client, db_session, clock, user)
    code = _code(secret, clock)
    pre = auth_service_module.login_step1(db_session, user.username, PASSWORD).pre_auth_token

    Sess = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    results: list[str] = []

    def attempt():
        s = Sess()
        try:
            auth_service_module.verify_otp_step2(s, pre, code)
            results.append("ok")
        except Exception as exc:  # noqa: BLE001
            results.append(type(exc).__name__)
        finally:
            s.close()

    threads = [threading.Thread(target=attempt) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert results.count("ok") == 1, results
    assert results.count("UnauthorizedException") == 3, results
