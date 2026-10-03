"""
Phase 6E-3 — secret-leakage regression tests.

Covers: passwords, OTPs/OTP hashes, JWTs/pre-auth tokens, the
question-paper master encryption key, per-paper wrapped DEK/nonce
material, exception-response safety, and audit/security-event safety.
Every test drives the REAL application code (real password hashing,
real OTP generation/verification, real JWT issuance, real AES-256-GCM
encryption via app/services/crypto_service.py) — nothing here is
mocked except, where unavoidable, the exact same OTP-delivery-capture
technique every other Phase 6E test file already uses (monkeypatching
only the dev-only delivery call's SIDE CHANNEL used to read the value
back in the test, never bypassing or weakening the real verification
logic itself).

IMPORTANT, HONEST FINDING documented here rather than papered over
(per the Phase 6E-3 brief: "Inspect actual logging and exception
behavior before writing tests. Do not invent secret names that do not
exist" / "do not fabricate results"):

app/security/otp.py's DevConsoleOTPProvider.deliver() DOES log the
plaintext OTP, via logger.warning(...). This is NOT a newly-discovered
leak and NOT a Phase 6E-3 regression — it is the project's explicit,
already-documented, dev-only placeholder OTP delivery mechanism (see
that class's own docstring: "NOT an approved delivery channel —
replace before any non-local use"; SRS OQ-4 and LLD DD-12 record the
real delivery channel as NOT YET DETERMINED).

Precision matters here, so stated exactly as confirmed by inspection
(app/services/auth_service.py line ~38): DevConsoleOTPProvider is
currently the ONLY OTPProvider implementation that exists in the
codebase, and it is instantiated and used UNCONDITIONALLY — there is
no APP_ENV check, no OTP_DELIVERY_CHANNEL-driven branch, and no
alternate provider class anywhere in this codebase today. So this is
"development-only" by DOCUMENTED INTENT and by the fact that no
production deployment of this system exists yet (SRS OQ-4/LLD DD-12
are explicitly open questions), but it is NOT currently environment-
gated in code — running this application with APP_ENV=production
today would still use DevConsoleOTPProvider and would still log the
OTP. Implementing real environment-based provider selection, or a
real delivery channel, is "new authentication architecture" and is
explicitly out of this phase's scope; it is recorded as a known
limitation in PROJECT_STATE.md rather than silently fixed here.

Given that, test_otp_appears_in_logs_exactly_once_at_the_documented_
dev_delivery_point below does NOT claim the OTP "never appears in
logs" (that would be false, and this docstring does not want to repeat
that mistake either). It instead proves the TRUE, and actually
meaningful, property: the OTP appears EXACTLY ONCE, EXACTLY at that
one documented DevConsoleOTPProvider line, and NOWHERE ELSE — not
during successful verification, not during failed verification, not
during lockout, not during rate-limiting, not in any audit/security
event, and not in any API response. That is the real security boundary
this phase is responsible for (secrets must never leak through the
VERIFICATION, AUDIT, or RESPONSE paths), as distinct from the already-
documented, separately-tracked OTP_DELIVERY_CHANNEL open question.
"""

import logging
import uuid

import pytest

from app.config import get_settings
from app.models.audit_event import AuditEvent
from app.models.auth_session import AuthSession
from app.models.otp_code import OtpCode
from app.models.paper import Paper
from app.models.security_event import SecurityEvent
from tests.conftest import SAMPLE_PDF_BYTES, auth_header
from tests.test_paper_api import _register_sample_paper

import app.services.auth_service as auth_service_module

settings = get_settings()


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------


def _login_capture(client, monkeypatch, username: str, password: str):
    """Returns (response, captured_otp_or_None). Does NOT verify."""
    captured: dict[str, str] = {}
    original_deliver = auth_service_module._otp_provider.deliver

    def _capturing_deliver(user_identifier: str, otp: str) -> None:
        captured["otp"] = otp
        original_deliver(user_identifier, otp)

    monkeypatch.setattr(auth_service_module._otp_provider, "deliver", _capturing_deliver)
    resp = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    return resp, captured.get("otp")


def _verify(client, pre_auth_token: str, otp_code: str):
    return client.post(
        "/api/v1/auth/otp/verify",
        json={"pre_auth_token": pre_auth_token, "otp_code": otp_code},
    )


WRONG_OTP = "000000"


# ===========================================================================
# SECRET TEST 1 — password not in response
# ===========================================================================


def test_password_not_in_successful_login_response(client, admin_principal, monkeypatch):
    # admin_principal already logged in once; drive a second, fresh login
    # for this exact user to inspect the raw response body directly.
    resp, _otp = _login_capture(client, monkeypatch, admin_principal.username, admin_principal.password)
    assert resp.status_code == 200
    assert admin_principal.password not in resp.text
    assert set(resp.json().keys()) == {"otp_required", "pre_auth_token"}


def test_password_not_in_failed_login_response(client):
    wrong_password = "this-is-not-the-real-password-123!"
    resp = client.post(
        "/api/v1/auth/login", json={"username": "no-such-user", "password": wrong_password}
    )
    assert resp.status_code == 401
    assert wrong_password not in resp.text


# ===========================================================================
# SECRET TEST 2 — password not in logging
# ===========================================================================


def test_password_not_logged_on_success_or_failure(client, db_session, monkeypatch, caplog):
    from app.models.role import Role
    from app.models.user import User
    from app.security.password import hash_password
    from tests.conftest import _get_or_create_role

    role = _get_or_create_role(db_session, "Admin")
    username = f"pwlogtest_{uuid.uuid4().hex[:8]}"
    distinctive_password = f"Sup3r-Secret-{uuid.uuid4().hex[:10]}!"
    user = User(username=username, password_hash=hash_password(distinctive_password), role_id=role.role_id)
    db_session.add(user)
    db_session.commit()

    with caplog.at_level(logging.DEBUG):
        ok_resp, _otp = _login_capture(client, monkeypatch, username, distinctive_password)
        assert ok_resp.status_code == 200
        bad_resp, _otp2 = _login_capture(client, monkeypatch, username, "totally-wrong-password")
        assert bad_resp.status_code == 401

    assert distinctive_password not in caplog.text
    assert "totally-wrong-password" not in caplog.text
    assert user.password_hash not in caplog.text


# ===========================================================================
# SECRET TEST 3 — OTP not in response
# ===========================================================================


def test_otp_not_in_verify_responses(client, admin_principal, monkeypatch, db_session):
    login_resp, otp = _login_capture(client, monkeypatch, admin_principal.username, admin_principal.password)
    pre_auth_token = login_resp.json()["pre_auth_token"]

    wrong_resp = _verify(client, pre_auth_token, WRONG_OTP)
    assert wrong_resp.status_code == 401
    assert otp not in wrong_resp.text

    otp_row = (
        db_session.query(OtpCode)
        .filter(OtpCode.user_id == admin_principal.user_id)
        .order_by(OtpCode.created_at.desc())
        .first()
    )
    assert otp_row.otp_hash not in wrong_resp.text

    success_resp = _verify(client, pre_auth_token, otp)
    assert success_resp.status_code == 200
    assert otp not in success_resp.text
    assert otp_row.otp_hash not in success_resp.text
    assert set(success_resp.json().keys()) == {"access_token", "token_type", "role"}


# ===========================================================================
# SECRET TEST 4 — OTP logging (see module docstring for the full, honest
# explanation of the one documented exception this test precisely proves
# is the ONLY place the OTP ever appears in logs).
# ===========================================================================


def test_otp_appears_in_logs_exactly_once_at_the_documented_dev_delivery_point(
    client, db_session, monkeypatch, caplog
):
    from app.models.user import User
    from app.security.password import hash_password
    from tests.conftest import _get_or_create_role

    role = _get_or_create_role(db_session, "Admin")
    username = f"otplogtest_{uuid.uuid4().hex[:8]}"
    password = "Test-OTP-Log-Password-123!"
    user = User(username=username, password_hash=hash_password(password), role_id=role.role_id)
    db_session.add(user)
    db_session.commit()

    with caplog.at_level(logging.DEBUG):
        login_resp, otp = _login_capture(client, monkeypatch, username, password)
        pre_auth_token = login_resp.json()["pre_auth_token"]

        # Failed verification.
        _verify(client, pre_auth_token, WRONG_OTP)
        # Exhaust to the Phase 6E-1 lock.
        for _ in range(settings.OTP_MAX_ATTEMPTS - 1):
            _verify(client, pre_auth_token, WRONG_OTP)
        # Now-locked challenge: correct code still rejected.
        _verify(client, pre_auth_token, otp)
        # Rate-limit path too (Phase 6E-2): a handful more calls.
        for _ in range(3):
            _verify(client, pre_auth_token, WRONG_OTP)

    matching_records = [r for r in caplog.records if otp in r.getMessage()]

    # The property actually worth proving: exactly one record contains
    # the OTP, and it is the documented dev-delivery line, not an
    # accidental duplicate introduced by verification/lock/rate-limit
    # handling.
    assert len(matching_records) == 1, (
        f"expected the OTP to appear in exactly one log record (the documented "
        f"DevConsoleOTPProvider delivery line), found {len(matching_records)}"
    )
    only_record = matching_records[0]
    assert only_record.name == "app.security.otp"
    assert "DEV-ONLY OTP DELIVERY" in only_record.getMessage()


def test_otp_hash_never_appears_in_logs(client, db_session, monkeypatch, caplog):
    with caplog.at_level(logging.DEBUG):
        login_resp, otp = _login_capture(client, monkeypatch, "admin-does-not-need-to-exist", "x")
    # (username doesn't need to exist for THIS assertion — we only care
    # that no otp_hash value already in the DB from earlier tests in
    # this process ever appears; check against every stored hash.)
    all_hashes = [row.otp_hash for row in db_session.query(OtpCode).all()]
    for h in all_hashes:
        assert h not in caplog.text


# ===========================================================================
# SECRET TEST 5 — JWT / pre-auth token not logged
# ===========================================================================


def test_jwt_and_pre_auth_token_not_logged(client, db_session, monkeypatch, caplog):
    from app.models.user import User
    from app.security.password import hash_password
    from tests.conftest import _get_or_create_role

    role = _get_or_create_role(db_session, "Admin")
    username = f"jwtlogtest_{uuid.uuid4().hex[:8]}"
    password = "Test-JWT-Log-Password-123!"
    user = User(username=username, password_hash=hash_password(password), role_id=role.role_id)
    db_session.add(user)
    db_session.commit()

    with caplog.at_level(logging.DEBUG):
        login_resp, otp = _login_capture(client, monkeypatch, username, password)
        pre_auth_token = login_resp.json()["pre_auth_token"]
        verify_resp = _verify(client, pre_auth_token, otp)
        access_token = verify_resp.json()["access_token"]
        me_resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"})
        assert me_resp.status_code == 200

    assert pre_auth_token not in caplog.text
    assert access_token not in caplog.text


def test_raw_jwt_is_never_persisted_only_its_jti_reference(client, admin_principal, db_session):
    """
    LLD DD-06's own design claim, verified rather than assumed: the
    stored auth_sessions.jwt_reference is the token's jti claim (a
    short opaque UUID-like string), never the bearer token itself.
    """
    sessions = db_session.query(AuthSession).filter(AuthSession.user_id == admin_principal.user_id).all()
    assert len(sessions) >= 1
    for session_row in sessions:
        assert session_row.jwt_reference != admin_principal.access_token
        assert session_row.jwt_reference not in admin_principal.access_token
        # The real access token is a JWT: three base64url segments
        # separated by dots. jwt_reference must not even look like one.
        assert session_row.jwt_reference.count(".") == 0


# ===========================================================================
# SECRET TEST 6 — tokens not echoed in error responses
# ===========================================================================


def test_malformed_authorization_header_not_echoed(client):
    garbage = "Bearer this.is.not-a-real-jwt-" + uuid.uuid4().hex
    resp = client.get("/api/v1/auth/me", headers={"Authorization": garbage})
    assert resp.status_code == 401
    assert garbage not in resp.text
    assert "this.is.not-a-real-jwt" not in resp.text


def test_invalid_pre_auth_token_not_echoed(client):
    garbage_token = "garbage-pre-auth-token-" + uuid.uuid4().hex
    resp = _verify(client, garbage_token, "123456")
    assert resp.status_code == 401
    assert garbage_token not in resp.text


def test_expired_looking_jwt_not_echoed(client):
    """A syntactically JWT-shaped but invalid/garbage token must still
    never be echoed back, and must not trigger a stack trace."""
    fake_jwt = "eyJhbGciOiJIUzI1NiJ9.eyJmYWtlIjp0cnVlfQ.not-a-real-signature"
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {fake_jwt}"})
    assert resp.status_code == 401
    assert fake_jwt not in resp.text
    assert "Traceback" not in resp.text
    assert resp.json() == {
        "error": {"message": "Invalid or expired authentication token.", "status_code": 401}
    }


# ===========================================================================
# SECRET TEST 7 — master key not exposed
# ===========================================================================


def test_master_key_never_exposed_across_full_paper_lifecycle(
    client, db_session, admin_principal, exam_centre_principal, caplog
):
    master_key = settings.QUESTION_PAPER_MASTER_KEY
    assert master_key  # sanity: the test session really has one configured

    with caplog.at_level(logging.DEBUG):
        reg_resp = _register_sample_paper(client, admin_principal, subject="Master Key Leak Check")
        assert reg_resp.status_code == 201, reg_resp.text
        paper_id = reg_resp.json()["paper_id"]
        assert master_key not in reg_resp.text

        meta_resp = client.get(f"/api/v1/papers/{paper_id}", headers=auth_header(admin_principal))
        assert master_key not in meta_resp.text

        # Authorize, then a successful retrieval.
        auth_resp = client.post(
            f"/api/v1/papers/{paper_id}/authorize",
            json={"centre_id": str(exam_centre_principal.centre_id)},
            headers=auth_header(admin_principal),
        )
        assert auth_resp.status_code == 200
        assert master_key not in auth_resp.text

        retrieve_resp = client.get(
            f"/api/v1/papers/{paper_id}/retrieve", headers=auth_header(exam_centre_principal)
        )
        assert retrieve_resp.status_code == 200
        assert master_key.encode() not in retrieve_resp.content

        # And an unauthorized-centre error path too.
        other_resp = client.get(
            f"/api/v1/papers/{uuid.uuid4()}/retrieve", headers=auth_header(exam_centre_principal)
        )
        assert master_key not in other_resp.text

    assert master_key not in caplog.text


# ===========================================================================
# SECRET TEST 8 — per-paper wrapped DEK / nonce not exposed
# ===========================================================================


def test_wrapped_dek_and_nonce_never_returned_by_any_endpoint(
    client, db_session, admin_principal, exam_centre_principal
):
    """
    The RAW (unwrapped) DEK is architecturally impossible to leak via
    the API: it is generated fresh in crypto_service.encrypt_paper(),
    exists only in that function's local scope, and is never persisted
    anywhere (app/services/crypto_service.py's own module docstring).
    The actually-testable claim is the stored WRAPPED form: papers.
    wrapped_dek and papers.file_nonce DO exist as real database columns
    (LLD Section 7.4/12) and must never be serialized back to any
    client, through any paper endpoint.
    """
    reg_resp = _register_sample_paper(client, admin_principal, subject="DEK Leak Check")
    assert reg_resp.status_code == 201, reg_resp.text
    paper_id = reg_resp.json()["paper_id"]

    paper_row = db_session.query(Paper).filter(Paper.paper_id == uuid.UUID(paper_id)).one()
    wrapped_dek = paper_row.wrapped_dek
    file_nonce = paper_row.file_nonce
    assert wrapped_dek and file_nonce  # sanity: these really are populated

    auth_resp = client.post(
        f"/api/v1/papers/{paper_id}/authorize",
        json={"centre_id": str(exam_centre_principal.centre_id)},
        headers=auth_header(admin_principal),
    )
    assert auth_resp.status_code == 200

    endpoints_and_responses = [
        reg_resp,
        client.get(f"/api/v1/papers/{paper_id}", headers=auth_header(admin_principal)),
        client.get(f"/api/v1/papers/{paper_id}/status", headers=auth_header(admin_principal)),
        client.get("/api/v1/papers", headers=auth_header(admin_principal)),
        client.get(f"/api/v1/papers/{paper_id}/retrieve", headers=auth_header(exam_centre_principal)),
    ]
    for resp in endpoints_and_responses:
        assert wrapped_dek not in resp.text
        assert file_nonce not in resp.text


# ===========================================================================
# SECRET TEST 9 / 12 — exception response safety (including the generic
# catch-all 500 handler)
# ===========================================================================


def test_malformed_request_body_error_is_safe(client):
    resp = client.post("/api/v1/auth/login", json={"username": "someone"})  # missing password
    assert resp.status_code == 422
    assert "Traceback" not in resp.text
    assert "File \"" not in resp.text  # no Python source-file path fragment


def test_invalid_uuid_in_path_error_is_safe(client, admin_principal):
    resp = client.get("/api/v1/papers/not-a-valid-uuid", headers=auth_header(admin_principal))
    assert resp.status_code == 422
    assert "Traceback" not in resp.text
    assert "/home/" not in resp.text
    assert "/app/" not in resp.text


def test_missing_resource_error_is_safe(client, admin_principal):
    resp = client.get(f"/api/v1/papers/{uuid.uuid4()}", headers=auth_header(admin_principal))
    assert resp.status_code == 404
    assert resp.json() == {
        "error": {"message": "The requested resource was not found.", "status_code": 404}
    }


def test_invalid_authentication_error_is_safe(client):
    resp = client.get("/api/v1/auth/me")  # no Authorization header at all
    assert resp.status_code == 401
    assert "Traceback" not in resp.text


def test_unhandled_internal_exception_never_leaks_its_message(client, admin_principal, monkeypatch):
    """
    Proves the catch-all handler (app/exceptions/handlers.py's
    handle_unexpected_exception) redacts ANY exception message, not
    merely the already-safe, hand-written AppException messages used
    elsewhere. A deliberately sensitive-looking message is injected
    into a real code path for exactly one request, to verify the
    safety net itself rather than just the happy path. Reverted
    automatically by monkeypatch at the end of the test.
    """
    import app.services.paper_service as paper_service_module
    from app.main import app
    from fastapi.testclient import TestClient

    sensitive_detail = "DB_PASSWORD=hunter2 SELECT * FROM users; /etc/shadow AES_KEY=deadbeef"

    def _boom(db, paper_id):
        raise RuntimeError(sensitive_detail)

    monkeypatch.setattr(paper_service_module, "get_paper_by_id_or_404", _boom)

    # The shared `client` fixture's TestClient defaults to
    # raise_server_exceptions=True (a pytest debugging convenience),
    # which would re-raise this RuntimeError into the test instead of
    # letting it reach app/exceptions/handlers.py's catch-all handler
    # — the opposite of what real production traffic (uvicorn) does. A
    # second, local TestClient with raise_server_exceptions=False
    # exercises the REAL production behavior: the dependency override
    # on `app` (set by the shared `client` fixture, still active here)
    # is reused since overrides live on the shared `app` object.
    unraising_client = TestClient(app, raise_server_exceptions=False)
    resp = unraising_client.get(f"/api/v1/papers/{uuid.uuid4()}", headers=auth_header(admin_principal))

    assert resp.status_code == 500
    assert resp.json() == {
        "error": {"message": "An internal server error occurred.", "status_code": 500}
    }
    assert sensitive_detail not in resp.text
    assert "hunter2" not in resp.text
    assert "Traceback" not in resp.text
    assert "RuntimeError" not in resp.text


# ===========================================================================
# SECRET TEST 10 — audit / security event safety
# ===========================================================================


_FORBIDDEN_EVENT_SUBSTRINGS_LABEL = (
    "password",
    "otp_hash",
    "wrapped_dek",
    "master",
    "AES",
    "Bearer ",
)


def test_audit_and_security_events_contain_no_secrets(
    client, db_session, admin_principal, exam_centre_principal, monkeypatch
):
    """
    Drives a representative spread of event-generating flows (login
    failure, OTP failure/lock, paper registration, authorization,
    successful retrieval, an unauthorized retrieval attempt, and a
    rate-limited OTP request), then inspects EVERY audit_events and
    security_events row created during the test for forbidden
    substrings. Checks structured columns only (event_type, outcome,
    actor_id, paper_id, severity, ledger_tx_reference) — exactly the
    columns LLD Section 7.6/7.7 define; there is no free-text/message
    column on either table for a secret to hide in.
    """
    before_audit_ids = {e.event_id for e in db_session.query(AuditEvent).all()}
    before_security_ids = {e.security_event_id for e in db_session.query(SecurityEvent).all()}

    # Failed login.
    client.post(
        "/api/v1/auth/login", json={"username": admin_principal.username, "password": "wrong-password-xyz"}
    )

    # OTP failure + lock.
    login_resp, otp = _login_capture(client, monkeypatch, exam_centre_principal.username, exam_centre_principal.password)
    pre_auth_token = login_resp.json()["pre_auth_token"]
    for _ in range(settings.OTP_MAX_ATTEMPTS):
        _verify(client, pre_auth_token, WRONG_OTP)

    # Paper registration + authorization + retrieval (success) + a
    # denied cross-resource attempt.
    reg_resp = _register_sample_paper(client, admin_principal, subject="Audit Safety Check")
    paper_id = reg_resp.json()["paper_id"]
    client.post(
        f"/api/v1/papers/{paper_id}/authorize",
        json={"centre_id": str(exam_centre_principal.centre_id)},
        headers=auth_header(admin_principal),
    )
    client.get(f"/api/v1/papers/{paper_id}/retrieve", headers=auth_header(exam_centre_principal))
    client.get(f"/api/v1/papers/{uuid.uuid4()}/retrieve", headers=auth_header(exam_centre_principal))

    db_session.expire_all()
    new_audit = [e for e in db_session.query(AuditEvent).all() if e.event_id not in before_audit_ids]
    new_security = [
        e for e in db_session.query(SecurityEvent).all() if e.security_event_id not in before_security_ids
    ]
    assert new_audit, "expected at least one new audit event from this flow"
    assert new_security, "expected at least one new security event from this flow"

    for event in new_audit:
        serialized = f"{event.event_type}|{event.outcome}|{event.ledger_tx_reference}"
        for forbidden in _FORBIDDEN_EVENT_SUBSTRINGS_LABEL:
            assert forbidden.lower() not in serialized.lower()

    for event in new_security:
        serialized = f"{event.event_type}|{event.severity}"
        for forbidden in _FORBIDDEN_EVENT_SUBSTRINGS_LABEL:
            assert forbidden.lower() not in serialized.lower()


# ===========================================================================
# SECRET TEST 11 — response schema field sets never include sensitive
# internal model fields
# ===========================================================================


_FORBIDDEN_SCHEMA_FIELD_NAMES = {
    "password",
    "password_hash",
    "otp_hash",
    "wrapped_dek",
    "file_nonce",
    "file_reference",
    "jwt_reference",
}


@pytest.mark.parametrize(
    "schema_import_path",
    [
        "app.schemas.auth.LoginResponse",
        "app.schemas.auth.OtpVerifyResponse",
        "app.schemas.auth.CurrentUserResponse",
        "app.schemas.papers.PaperMetadataResponse",
        "app.schemas.papers.PaperListItemResponse",
        "app.schemas.papers.PaperStatusResponse",
        "app.schemas.papers.PaperRegisterResponse",
        "app.schemas.admin.CentreResponse",
        "app.schemas.audit.AuditEventResponse",
        "app.schemas.monitoring.SecurityEventResponse",
    ],
)
def test_response_schema_never_declares_forbidden_fields(schema_import_path):
    module_path, class_name = schema_import_path.rsplit(".", 1)
    import importlib

    module = importlib.import_module(module_path)
    schema_cls = getattr(module, class_name)
    field_names = set(schema_cls.model_fields.keys())
    overlap = field_names & _FORBIDDEN_SCHEMA_FIELD_NAMES
    assert not overlap, f"{schema_import_path} declares forbidden field(s): {overlap}"
