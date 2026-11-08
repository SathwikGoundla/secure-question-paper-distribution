"""
Phase 7B — one-time backup/recovery codes as an alternative SECOND factor.

Reuses the Phase 7A helpers (users, enrollment, clock control). A recovery code is only ever accepted
at the second-factor step, i.e. after the password was verified and a pre-auth challenge exists.
"""

import logging
import threading
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import sessionmaker

import app.api.v1.auth as auth_router
import app.services.auth_service as auth_service_module
from app.config import Settings, get_settings
from app.models.audit_event import AuditEvent
from app.models.otp_code import OtpCode
from app.models.security_event import SecurityEvent
from app.models.user_recovery_code import UserRecoveryCode
from app.security import recovery_codes as rc
from app.services import totp_service
from tests.conftest import auth_header
from tests.test_totp_auth import (  # noqa: F401  (fixtures + helpers)
    API,
    PASSWORD,
    _code,
    _enroll,
    _events,
    _login,
    _make_user,
    _sign_in,
    _verify,
    clock,
    totp_mode,
)


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _recover(client, pre_auth_token, code):
    return client.post(f"{API}/auth/recovery-code/verify", json={"pre_auth_token": pre_auth_token, "recovery_code": code})


def _session(client, user, secret, clock) -> str:
    resp = _sign_in(client, user, secret, clock)
    assert resp.status_code == 200, resp.text
    clock.advance(30)
    return resp.json()["access_token"]


def _regenerate(client, token, password=PASSWORD):
    return client.post(f"{API}/auth/recovery-codes/regenerate", json={"password": password}, headers=_bearer(token))


def _enrolled_with_codes(client, db_session, clock):
    user = _make_user(db_session)
    secret = _enroll(client, db_session, clock, user)
    token = _session(client, user, secret, clock)
    resp = _regenerate(client, token)
    assert resp.status_code == 200, resp.text
    return user, secret, token, resp.json()["codes"]


def _challenge(client, user) -> str:
    resp = _login(client, user)
    assert resp.status_code == 200, resp.text
    return resp.json()["pre_auth_token"]


# ===========================================================================
# Primitives and configuration
# ===========================================================================


def test_generated_codes_are_well_formed_unique_and_high_entropy():
    codes = {rc.generate_code() for _ in range(500)}
    assert len(codes) == 500
    for c in list(codes)[:20]:
        assert len(c) == 19 and c.count("-") == 3 and rc.is_well_formed(c)
        assert not set(c.replace("-", "")) & set("01ILO")  # no look-alikes
    # 16 symbols from a 31-letter alphabet is ~79 bits.
    import math

    assert 16 * math.log2(len("ABCDEFGHJKMNPQRSTUVWXYZ23456789")) > 78


def test_hash_is_bound_to_the_user_and_normalised():
    a, b = uuid.uuid4(), uuid.uuid4()
    code = rc.generate_code()
    assert rc.hash_code(a, code) == rc.hash_code(a, code.lower().replace("-", " "))
    assert rc.hash_code(a, code) != rc.hash_code(b, code)
    assert len(rc.hash_code(a, code)) == 64 and code.replace("-", "") not in rc.hash_code(a, code)
    for bad in ("", "short", "AAAA-AAAA-AAAA", "0000-0000-0000-0000", "A" * 40, None):
        assert not rc.is_well_formed(bad or "")


def test_recovery_code_count_is_configurable_within_bounds():
    assert Settings.model_fields["RECOVERY_CODE_COUNT"].default == 10
    for bad in (0, 4, 21, 100):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, RECOVERY_CODE_COUNT=bad)
    assert Settings(_env_file=None, RECOVERY_CODE_COUNT=5).RECOVERY_CODE_COUNT == 5


# ===========================================================================
# Generation / regeneration / status
# ===========================================================================


def test_regeneration_returns_codes_once_and_stores_only_hashes(client, db_session, clock, totp_mode, caplog):
    user = _make_user(db_session)
    secret = _enroll(client, db_session, clock, user)
    token = _session(client, user, secret, clock)
    with caplog.at_level(logging.DEBUG):
        resp = _regenerate(client, token)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    codes = body["codes"]
    assert body["count"] == len(codes) == 10 and set(body) == {"codes", "count", "generated_at"}

    db_session.expire_all()
    rows = db_session.query(UserRecoveryCode).filter(UserRecoveryCode.user_id == user.user_id).all()
    assert len(rows) == 10 and all(r.used_at is None and r.revoked_at is None for r in rows)
    stored = " ".join(r.code_hash for r in rows)
    for c in codes:
        assert c not in stored and c.replace("-", "") not in stored
    assert {r.code_hash for r in rows} == {rc.hash_code(user.user_id, c) for c in codes}
    assert all(c not in caplog.text and c.replace("-", "") not in caplog.text for c in codes)

    # The codes are never retrievable again.
    status = client.get(f"{API}/auth/recovery-codes/status", headers=_bearer(token))
    assert status.status_code == 200
    assert set(status.json()) == {"unused_count", "generated_at", "authenticator_active"}
    assert status.json()["unused_count"] == 10 and status.json()["authenticator_active"] is True
    assert not any(c in status.text for c in codes)
    assert _events(db_session, AuditEvent, "RECOVERY_CODES_GENERATED", user.user_id) == 1


def test_regeneration_requires_the_current_password(client, db_session, clock, totp_mode):
    user = _make_user(db_session)
    secret = _enroll(client, db_session, clock, user)
    token = _session(client, user, secret, clock)
    bad = _regenerate(client, token, password="Wrong-Password-1!")
    assert bad.status_code == 401 and "codes" not in bad.text
    assert db_session.query(UserRecoveryCode).filter(UserRecoveryCode.user_id == user.user_id).count() == 0
    assert _events(db_session, SecurityEvent, "RECOVERY_REGENERATE_FAILED", user.user_id) == 1


def test_regeneration_needs_a_full_mfa_session_not_a_pre_auth_or_enrollment_token(client, db_session, clock, totp_mode):
    user = _make_user(db_session)
    secret = _enroll(client, db_session, clock, user)
    pre = _challenge(client, user)
    enrollment_code, _ = totp_service.issue_enrollment_code(db_session, _make_user(db_session), issued_by=None)
    assert _regenerate(client, pre).status_code == 401  # password-only stage
    from app.security.jwt_handler import create_enrollment_token

    assert _regenerate(client, create_enrollment_token(user.user_id)).status_code == 401
    assert client.post(f"{API}/auth/recovery-codes/regenerate", json={"password": PASSWORD}).status_code == 401
    assert client.get(f"{API}/auth/recovery-codes/status", headers=_bearer(pre)).status_code == 401
    assert db_session.query(UserRecoveryCode).filter(UserRecoveryCode.user_id == user.user_id).count() == 0


def test_regeneration_requires_an_active_authenticator(client, db_session, admin_principal, totp_mode):
    # admin_principal signed in through the legacy flow, so it has no TOTP authenticator.
    resp = _regenerate(client, admin_principal.access_token, password=admin_principal.password)
    assert resp.status_code == 409


def test_regeneration_replaces_the_whole_set(client, db_session, clock, totp_mode):
    user, secret, token, old_codes = _enrolled_with_codes(client, db_session, clock)
    new = _regenerate(client, token)
    assert new.status_code == 200
    new_codes = new.json()["codes"]
    assert set(new_codes).isdisjoint(old_codes)
    db_session.expire_all()
    rows = db_session.query(UserRecoveryCode).filter(UserRecoveryCode.user_id == user.user_id).all()
    assert len(rows) == 20 and sum(r.revoked_at is not None for r in rows) == 10
    assert client.get(f"{API}/auth/recovery-codes/status", headers=_bearer(token)).json()["unused_count"] == 10
    # The old set no longer works; the new one does.
    assert _recover(client, _challenge(client, user), old_codes[0]).status_code == 401
    assert _recover(client, _challenge(client, user), new_codes[0]).status_code == 200


def test_configured_count_is_used(client, db_session, clock, totp_mode, monkeypatch):
    monkeypatch.setattr(get_settings(), "RECOVERY_CODE_COUNT", 6)
    user = _make_user(db_session)
    secret = _enroll(client, db_session, clock, user)
    assert len(_regenerate(client, _session(client, user, secret, clock)).json()["codes"]) == 6


# ===========================================================================
# Recovery login
# ===========================================================================


def test_recovery_code_signs_in_after_the_password_and_is_single_use(client, db_session, clock, totp_mode):
    user, secret, old_token, codes = _enrolled_with_codes(client, db_session, clock)
    pre = _challenge(client, user)
    assert "access_token" not in client.post(f"{API}/auth/login", json={"username": user.username, "password": PASSWORD}).text

    resp = _recover(client, pre, codes[0])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["role"] == "Auditor" and body["recovery_codes_remaining"] == 9
    assert client.get(f"{API}/auth/me", headers=_bearer(body["access_token"])).json()["username"] == user.username

    # Policy: signing in with a recovery code revokes the user's OTHER sessions.
    assert client.get(f"{API}/auth/me", headers=_bearer(old_token)).status_code == 401
    # Policy: it does not disable the authenticator.
    clock.advance(30)
    assert _sign_in(client, user, secret, clock).status_code == 200

    # The same code can never be used again, not even with a fresh password-verified challenge.
    reuse = _recover(client, _challenge(client, user), codes[0])
    assert reuse.status_code == 401 and "access_token" not in reuse.text
    # The other codes still work.
    assert _recover(client, _challenge(client, user), codes[1]).status_code == 200

    assert _events(db_session, AuditEvent, "RECOVERY_CODE_USED", user.user_id) == 2
    assert _events(db_session, SecurityEvent, "RECOVERY_CODE_USED", user.user_id) == 2


def test_wrong_malformed_and_foreign_codes_are_rejected_with_one_generic_message(client, db_session, clock, totp_mode):
    user, _s, _t, codes = _enrolled_with_codes(client, db_session, clock)
    other, _s2, _t2, other_codes = _enrolled_with_codes(client, db_session, clock)
    attempts = [
        rc.generate_code(),  # well-formed but never issued
        "AAAA-AAAA-AAAA",  # too short
        "not a code",
        "０１２３-４５６７-89AB-CDEF",
        codes[0][:-1] + ("A" if codes[0][-1] != "A" else "B"),  # one character off
        other_codes[0],  # a REAL code, but belongs to another user
    ]
    for bad in attempts:
        resp = _recover(client, _challenge(client, user), bad)
        assert resp.status_code == 401, bad
        assert resp.json()["error"]["message"] == "Invalid or expired OTP."
        assert "access_token" not in resp.text
    assert _events(db_session, SecurityEvent, "INVALID_RECOVERY_CODE", user.user_id) == len(attempts)
    # None of that consumed the user's or the other user's codes.
    assert client.get(f"{API}/auth/recovery-codes/status", headers=_bearer(_t)).json()["unused_count"] == 10
    assert _recover(client, _challenge(client, other), other_codes[0]).status_code == 200


def test_recovery_never_bypasses_the_password(client, db_session, clock, totp_mode):
    user, secret, token, codes = _enrolled_with_codes(client, db_session, clock)
    # Wrong password -> no pre-auth token exists to attach a recovery code to.
    login = _login(client, user, password="Wrong-Password-1!")
    assert login.status_code == 401 and "pre_auth_token" not in login.text
    # A recovery code with garbage / wrong-kind tokens is rejected.
    from app.security.jwt_handler import create_enrollment_token

    for bad in ("garbage", token, create_enrollment_token(user.user_id), ""):
        resp = _recover(client, bad or "x", codes[0])
        assert resp.status_code == 401
    # The code was not consumed by any of that.
    assert _recover(client, _challenge(client, user), codes[0]).status_code == 200


def test_expired_challenge_is_rejected_and_the_code_is_not_burned(client, db_session, clock, totp_mode):
    user, _s, _t, codes = _enrolled_with_codes(client, db_session, clock)
    pre = _challenge(client, user)
    row = db_session.query(OtpCode).filter(OtpCode.user_id == user.user_id, OtpCode.is_used == False).order_by(OtpCode.created_at.desc()).first()  # noqa: E712
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()
    assert _recover(client, pre, codes[0]).status_code == 401
    db_session.expire_all()
    assert db_session.query(UserRecoveryCode).filter(UserRecoveryCode.user_id == user.user_id, UserRecoveryCode.used_at.isnot(None)).count() == 0


def test_a_spent_challenge_cannot_be_reused(client, db_session, clock, totp_mode):
    user, _s, _t, codes = _enrolled_with_codes(client, db_session, clock)
    pre = _challenge(client, user)
    assert _recover(client, pre, codes[0]).status_code == 200
    assert _recover(client, pre, codes[1]).status_code == 401


def test_failed_attempts_lock_the_challenge_even_for_a_valid_code(client, db_session, clock, totp_mode, monkeypatch):
    import time

    monkeypatch.setattr(auth_service_module.settings, "OTP_MAX_ATTEMPTS", 3)
    user, _s, _t, codes = _enrolled_with_codes(client, db_session, clock)
    time.sleep(1.1)  # SQLite timestamps are 1 s resolution; keep "latest challenge" unambiguous
    pre = _challenge(client, user)
    for _ in range(3):
        assert _recover(client, pre, rc.generate_code()).status_code == 401
    assert _recover(client, pre, codes[0]).status_code == 401  # locked, so even the right code fails
    assert _events(db_session, SecurityEvent, "OTP_CHALLENGE_LOCKED", user.user_id) == 1
    time.sleep(1.1)
    assert _recover(client, _challenge(client, user), codes[0]).status_code == 200  # code was never burned


def test_recovery_verification_is_rate_limited(client, db_session, clock, totp_mode):
    user, _s, _t, codes = _enrolled_with_codes(client, db_session, clock)
    limiter = auth_router._recovery_verify_limiter
    limiter.reset()
    pre = _challenge(client, user)
    statuses = [_recover(client, pre, rc.generate_code()).status_code for _ in range(limiter._limit + 2)]
    assert 429 in statuses and 200 not in statuses
    limiter.reset()


def test_regeneration_is_rate_limited(client, db_session, clock, totp_mode):
    user = _make_user(db_session)
    secret = _enroll(client, db_session, clock, user)
    token = _session(client, user, secret, clock)
    limiter = auth_router._recovery_regen_limiter
    limiter.reset()
    statuses = [_regenerate(client, token, password="Wrong-Password-1!").status_code for _ in range(limiter._limit + 1)]
    assert statuses[-1] == 429 and set(statuses[:-1]) == {401}
    limiter.reset()


def test_recovery_is_only_available_in_totp_mode(client, db_session, clock, totp_mode, monkeypatch):
    user, _s, _t, codes = _enrolled_with_codes(client, db_session, clock)
    pre = _challenge(client, user)
    monkeypatch.setattr(get_settings(), "AUTH_SECOND_FACTOR", "dev_console")
    assert _recover(client, pre, codes[0]).status_code == 401
    legacy_pre = auth_service_module.create_pre_auth_token(user.user_id)  # mfa = dev_console
    assert _recover(client, legacy_pre, codes[0]).status_code == 401


def test_admin_reenrollment_revokes_the_users_recovery_codes(client, db_session, admin_principal, clock, totp_mode):
    user, _s, _t, codes = _enrolled_with_codes(client, db_session, clock)
    issue = client.post(f"{API}/admin/totp/enrollment-codes", json={"username": user.username}, headers=auth_header(admin_principal))
    assert issue.status_code == 201
    db_session.expire_all()
    rows = db_session.query(UserRecoveryCode).filter(UserRecoveryCode.user_id == user.user_id).all()
    assert rows and all(r.revoked_at is not None for r in rows)
    # Their authenticator is wiped too, so the password stage now refuses (no challenge, no recovery path).
    assert _login(client, user).status_code == 403


def test_no_code_material_in_responses_logs_or_event_tables(client, db_session, clock, totp_mode, caplog):
    with caplog.at_level(logging.DEBUG):
        user, _s, token, codes = _enrolled_with_codes(client, db_session, clock)
        ok = _recover(client, _challenge(client, user), codes[0])
        bad = _recover(client, _challenge(client, user), codes[0])
        status = client.get(f"{API}/auth/recovery-codes/status", headers=_bearer(token))
    assert ok.status_code == 200 and bad.status_code == 401
    flat = [c.replace("-", "") for c in codes]
    for text in (ok.text, bad.text, status.text, caplog.text):
        assert not any(c in text or c.replace("-", "") in text for c in codes)
    db_session.expire_all()
    dump = " ".join(
        f"{e.event_type}{e.outcome}" for e in db_session.query(AuditEvent).all()
    ) + " ".join(f"{e.event_type}{e.severity}" for e in db_session.query(SecurityEvent).all())
    assert not any(c in dump for c in flat)


# ===========================================================================
# PostgreSQL-only: real concurrency
# ===========================================================================


def test_concurrent_use_of_one_recovery_code_yields_exactly_one_session(db_engine, db_session, clock, client, totp_mode):
    if db_engine.dialect.name != "postgresql":
        pytest.skip("row-level locking is only enforced by PostgreSQL")
    user, _s, _t, codes = _enrolled_with_codes(client, db_session, clock)
    code = codes[0]
    # Four DIFFERENT password-verified challenges racing for the SAME code.
    pres = []
    for _ in range(4):
        pres.append(auth_service_module.login_step1(db_session, user.username, PASSWORD).pre_auth_token)

    Sess = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    results: list[str] = []
    barrier = threading.Barrier(4)

    def attempt(pre):
        s = Sess()
        try:
            barrier.wait(timeout=10)
            auth_service_module.verify_otp_step2(s, pre, code, recovery=True)
            results.append("ok")
        except Exception as exc:  # noqa: BLE001
            results.append(type(exc).__name__)
        finally:
            s.close()

    threads = [threading.Thread(target=attempt, args=(p,)) for p in pres]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert results.count("ok") == 1, results
    assert results.count("UnauthorizedException") == 3, results
    db_session.expire_all()
    used = db_session.query(UserRecoveryCode).filter(UserRecoveryCode.user_id == user.user_id, UserRecoveryCode.used_at.isnot(None)).count()
    assert used == 1
