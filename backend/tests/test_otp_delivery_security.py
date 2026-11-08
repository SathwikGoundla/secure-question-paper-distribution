"""
Phase 6I — development-only OTP delivery is gated.

Before this phase DevConsoleOTPProvider logged the plaintext OTP
unconditionally (documented in test_secret_leakage.py as a known gap).
Now the OTP may be written to a log ONLY when APP_ENV == "development"
AND OTP_DEV_LOG_ENABLED=true. Everywhere else the provider logs nothing
about the code and raises, and the login fails safely with a generic HTTP
503 — no pre-auth token is issued and the freshly created challenge is
invalidated. No real email/SMS/authenticator channel exists in this
project, and none is claimed here.

The suite-wide environment (tests/conftest.py) opts in to development
logging, like a developer's local .env. These tests flip the two settings
per test with monkeypatch on the cached Settings object, which the
provider reads at call time.

Existing OTP verification, expiry, single-use and lockout behaviour is
covered by test_otp_attempt_limiting.py and test_secret_leakage.py and is
re-run unchanged; the only new verification test here proves the normal
flow still completes after a refused attempt.
"""

import logging

import pytest

import app.services.auth_service as auth_service_module
from app.config import Settings, get_settings
from app.models.audit_event import AuditEvent
from app.models.otp_code import OtpCode
from app.models.user import User
from app.security.otp import (
    DevConsoleOTPProvider,
    OTPDeliveryError,
    dev_otp_logging_permitted,
    verify_otp,
)


def _set(monkeypatch, env: str, flag: bool) -> None:
    settings = get_settings()  # fetched at call time: the provider reads the same cached object
    monkeypatch.setattr(settings, "APP_ENV", env)
    monkeypatch.setattr(settings, "OTP_DEV_LOG_ENABLED", flag)


def _login_capturing(client, monkeypatch, username, password):
    """Wrap the real provider: record the OTP the application generated, then run the REAL deliver()."""
    captured: dict[str, str] = {}
    real = auth_service_module._otp_provider.deliver

    def _wrapper(user_identifier: str, otp: str) -> None:
        captured["otp"] = otp
        real(user_identifier, otp)  # may raise OTPDeliveryError — that is what is under test

    monkeypatch.setattr(auth_service_module._otp_provider, "deliver", _wrapper)
    resp = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    return resp, captured.get("otp")


def _step1_success_count(db_session, user) -> int:
    db_session.expire_all()
    return (
        db_session.query(AuditEvent)
        .filter(AuditEvent.actor_id == user.user_id, AuditEvent.event_type == "LOGIN_STEP1_SUCCESS")
        .count()
    )


# ---------------------------------------------------------------------------
# 1. Disabled by default
# ---------------------------------------------------------------------------


def test_dev_otp_logging_flag_defaults_to_false():
    assert Settings.model_fields["OTP_DEV_LOG_ENABLED"].default is False


def test_a_fresh_settings_object_without_the_flag_does_not_permit_logging(monkeypatch):
    monkeypatch.delenv("OTP_DEV_LOG_ENABLED", raising=False)
    assert Settings(_env_file=None).OTP_DEV_LOG_ENABLED is False


@pytest.mark.parametrize(
    "env,flag,expected",
    [
        ("development", False, False),  # default posture: off
        ("development", True, True),  # the single permitted combination
        ("Development", True, True),  # case-insensitive
        (" development ", True, True),
        ("staging", True, False),
        ("production", True, False),
        ("production", False, False),
        ("test", True, False),  # unknown environment names fail closed
        ("prod", True, False),
        ("", True, False),
    ],
)
def test_permission_truth_table(monkeypatch, env, flag, expected):
    _set(monkeypatch, env, flag)
    assert dev_otp_logging_permitted() is expected


def test_provider_refuses_and_logs_nothing_when_flag_is_off(monkeypatch, caplog):
    _set(monkeypatch, "development", False)
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(OTPDeliveryError) as exc:
            DevConsoleOTPProvider().deliver("someone", "123456")
    assert "123456" not in caplog.text
    assert "123456" not in str(exc.value)
    assert "someone" not in caplog.text


# ---------------------------------------------------------------------------
# 2. Explicit opt-in works in development (local demo)
# ---------------------------------------------------------------------------


def test_opted_in_development_login_logs_otp_once_and_completes_normal_flow(client, admin_principal, monkeypatch, caplog):
    _set(monkeypatch, "development", True)
    with caplog.at_level(logging.DEBUG):
        resp, otp = _login_capturing(client, monkeypatch, admin_principal.username, admin_principal.password)
    assert resp.status_code == 200, resp.text
    assert set(resp.json()) == {"otp_required", "pre_auth_token"}
    assert otp is not None and sum(otp in r.getMessage() for r in caplog.records) == 1

    verify = client.post(
        "/api/v1/auth/otp/verify", json={"pre_auth_token": resp.json()["pre_auth_token"], "otp_code": otp}
    )
    assert verify.status_code == 200
    assert verify.json()["access_token"]


# ---------------------------------------------------------------------------
# 3 + 4 + 5. Staging / production: never logged, fails safely, generic error
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("env", ["staging", "production"])
@pytest.mark.parametrize("flag", [True, False])  # the flag must NOT help outside development
def test_outside_development_otp_is_never_logged_and_login_fails_safely(
    client, db_session, admin_principal, monkeypatch, caplog, env, flag
):
    _set(monkeypatch, env, flag)
    with caplog.at_level(logging.DEBUG):
        resp, otp = _login_capturing(client, monkeypatch, admin_principal.username, admin_principal.password)

    assert otp is not None  # the application did generate a code...
    # ...but it is nowhere: not in logs, not in the response, not in any record.
    assert otp not in caplog.text
    assert otp not in resp.text
    assert resp.status_code == 503
    body = resp.json()
    assert "pre_auth_token" not in resp.text
    assert "otp_required" not in body
    assert body["error"]["message"] == "Sign-in is temporarily unavailable. Please contact the administrator."

    # No plaintext OTP at rest; the challenge created for the refused login is invalidated.
    db_session.expire_all()
    user = db_session.query(User).filter(User.username == admin_principal.username).one()
    rows = db_session.query(OtpCode).filter(OtpCode.user_id == user.user_id).all()
    assert rows and all(otp != r.otp_hash for r in rows)
    refused_rows = [r for r in rows if verify_otp(otp, r.otp_hash)]
    assert len(refused_rows) == 1
    assert refused_rows[0].is_used is True, "the refused challenge must be unusable"


def test_refused_login_does_not_record_a_new_success_audit_event(client, db_session, admin_principal, monkeypatch):
    user = db_session.query(User).filter(User.username == admin_principal.username).one()
    before = _step1_success_count(db_session, user)
    _set(monkeypatch, "production", True)
    resp, _ = _login_capturing(client, monkeypatch, admin_principal.username, admin_principal.password)
    assert resp.status_code == 503
    assert _step1_success_count(db_session, user) == before


def test_the_error_log_line_never_contains_the_otp_or_username(client, admin_principal, monkeypatch, caplog):
    _set(monkeypatch, "production", True)
    with caplog.at_level(logging.DEBUG):
        _resp, otp = _login_capturing(client, monkeypatch, admin_principal.username, admin_principal.password)
    delivery_records = [r for r in caplog.records if "OTP delivery" in r.getMessage()]
    assert len(delivery_records) == 1
    assert otp not in delivery_records[0].getMessage()
    assert admin_principal.username not in delivery_records[0].getMessage()


def test_wrong_password_is_still_a_normal_401_and_unaffected(client, admin_principal, monkeypatch):
    _set(monkeypatch, "production", False)
    resp = client.post("/api/v1/auth/login", json={"username": admin_principal.username, "password": "nope-nope-1!"})
    assert resp.status_code == 401  # first factor is judged before any delivery attempt


def test_login_recovers_once_development_opt_in_is_restored(client, admin_principal, monkeypatch):
    _set(monkeypatch, "production", True)
    refused, _ = _login_capturing(client, monkeypatch, admin_principal.username, admin_principal.password)
    assert refused.status_code == 503

    _set(monkeypatch, "development", True)
    ok, otp = _login_capturing(client, monkeypatch, admin_principal.username, admin_principal.password)
    assert ok.status_code == 200
    verify = client.post(
        "/api/v1/auth/otp/verify", json={"pre_auth_token": ok.json()["pre_auth_token"], "otp_code": otp}
    )
    assert verify.status_code == 200


def test_startup_warns_when_flag_is_set_outside_development_without_leaking(monkeypatch, caplog):
    import app.main as main_module
    from app.main import on_startup

    def _set_main(env: str, flag: bool) -> None:
        # on_startup reads the module-level `settings` object bound when app.main was imported.
        # Other test modules call get_settings.cache_clear() (test_crypto_service), after which
        # get_settings() returns a DIFFERENT object, so patch the one on_startup actually reads.
        monkeypatch.setattr(main_module.settings, "APP_ENV", env)
        monkeypatch.setattr(main_module.settings, "OTP_DEV_LOG_ENABLED", flag)

    _set_main("production", True)
    with caplog.at_level(logging.WARNING):
        on_startup()
    assert any("OTP_DEV_LOG_ENABLED is set but APP_ENV is not 'development'" in r.getMessage() for r in caplog.records)

    caplog.clear()
    _set_main("development", True)
    with caplog.at_level(logging.WARNING):
        on_startup()
    assert not any("OTP_DEV_LOG_ENABLED" in r.getMessage() for r in caplog.records)
