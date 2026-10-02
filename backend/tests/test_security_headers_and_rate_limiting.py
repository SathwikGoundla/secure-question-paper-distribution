"""
Phase 6E-2 — automated tests for:
  (A) HTTP security response headers (app/middleware/security_headers.py)
  (B) authentication rate limiting on POST /auth/login and
      POST /auth/otp/verify (app/security/rate_limiter.py,
      app/api/v1/auth.py)
  (C) the interaction between (B) and the Phase 6E-1 OTP
      failed-attempt counter — proving they are genuinely independent
      controls (a 429 from (B) must never increment
      otp_codes.failed_attempts).

Every test drives the REAL FastAPI app and REAL endpoints — nothing
here mocks application logic. The only test-only techniques are
OTP-capture (the same one tests/conftest.py and
tests/test_otp_attempt_limiting.py already use) and, for the
rate-limit window-expiry tests, monkeypatching the module-level
rate-limiter singletons' time source so those tests do not need real
sleeps.
"""

import time as _time
import uuid

import pytest

import app.api.v1.auth as auth_module
import app.services.auth_service as auth_service_module
from app.config import get_settings
from app.models.otp_code import OtpCode
from app.models.user import User
from app.security.password import hash_password
from tests.conftest import SAMPLE_PDF_BYTES, _get_or_create_role, auth_header
from tests.test_paper_api import _register_sample_paper

settings = get_settings()


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    """
    Every test in this file starts with (and leaves) a clean
    rate-limiter slate, regardless of what ran before/after it in the
    same pytest process. The two limiter singletons in
    app/api/v1/auth.py are module-level and therefore persist for the
    life of the process (see that module's docstring) — this fixture
    does not change production behaviour in any way; it only resets
    the IN-MEMORY counters, the same way a freshly started server
    process would start empty.
    """
    auth_module._login_limiter.reset()
    auth_module._otp_limiter.reset()
    yield
    auth_module._login_limiter.reset()
    auth_module._otp_limiter.reset()


# ---------------------------------------------------------------------------
# Local helpers (mirrors tests/test_otp_attempt_limiting.py's pattern)
# ---------------------------------------------------------------------------


@pytest.fixture()
def rl_user(db_session):
    role = _get_or_create_role(db_session, "Admin")
    username = f"rluser_{uuid.uuid4().hex[:8]}"
    password = "Test-RateLimit-Password-123!"
    user = User(username=username, password_hash=hash_password(password), role_id=role.role_id)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user, username, password


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


class _FakeClock:
    """
    A controllable monotonic-like clock for deterministic window-expiry
    tests. Anchored at the REAL time.monotonic() by default so that,
    when swapped in partway through a test (e.g. after a login call
    that used the real clock on a DIFFERENT limiter instance), any
    window already recorded using the real clock stays numerically
    coherent with this fake clock's starting point.
    """

    def __init__(self, start: float | None = None):
        self.now = start if start is not None else _time.monotonic()

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


WRONG_OTP = "000000"


# ===========================================================================
# PART A — HTTP SECURITY HEADERS
# ===========================================================================


def test_header_x_content_type_options(client):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.headers["x-content-type-options"] == "nosniff"


def test_header_x_frame_options(client):
    resp = client.get("/api/v1/health")
    assert resp.headers["x-frame-options"] == "DENY"


def test_header_referrer_policy(client):
    resp = client.get("/api/v1/health")
    assert resp.headers["referrer-policy"] == "strict-origin-when-cross-origin"


def test_header_content_security_policy(client):
    resp = client.get("/api/v1/health")
    assert resp.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"


def test_header_permissions_policy_present(client):
    resp = client.get("/api/v1/health")
    assert "camera=()" in resp.headers["permissions-policy"]


def test_hsts_absent_in_development_http(client):
    """
    The automated suite always runs over plain HTTP (TestClient never
    uses TLS). HSTS must be completely absent here, proving local HTTP
    development is unaffected regardless of APP_ENV (see
    app/middleware/security_headers.py for the exact double condition
    this test and the next one jointly exercise).
    """
    resp = client.get("/api/v1/health")
    assert "strict-transport-security" not in {h.lower() for h in resp.headers.keys()}


def test_hsts_present_only_when_production_and_https(client, monkeypatch):
    """
    Directly exercises the documented double condition: HSTS appears
    ONLY when BOTH settings.APP_ENV == "production" AND the request
    itself arrived over https. TestClient cannot make a genuinely
    TLS-negotiated request, but Starlette's TestClient DOES set
    request.url.scheme from the URL's own scheme when given an
    explicit https:// base — this drives the real middleware dispatch
    logic (app/middleware/security_headers.py), not a hand-written
    stand-in for it.
    """
    import app.middleware.security_headers as sh_module

    class _ProdSettings:
        APP_ENV = "production"

    class _DevSettings:
        APP_ENV = "development"

    # production APP_ENV alone, over plain http: NOT enough.
    monkeypatch.setattr(sh_module, "get_settings", lambda: _ProdSettings())
    resp_http = client.get("/api/v1/health")
    assert "strict-transport-security" not in {h.lower() for h in resp_http.headers.keys()}

    # https scheme AND production APP_ENV together: HSTS appears.
    resp_https = client.get("https://testserver/api/v1/health")
    assert resp_https.headers.get("strict-transport-security") == "max-age=63072000; includeSubDomains"

    # https scheme but NOT production: still absent.
    monkeypatch.setattr(sh_module, "get_settings", lambda: _DevSettings())
    resp_https_dev = client.get("https://testserver/api/v1/health")
    assert "strict-transport-security" not in {h.lower() for h in resp_https_dev.headers.keys()}


def test_security_headers_do_not_break_normal_authenticated_response(client, admin_principal):
    resp = client.get("/api/v1/auth/me", headers=auth_header(admin_principal))
    assert resp.status_code == 200
    assert resp.json()["username"] == admin_principal.username
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"


def test_security_headers_do_not_break_pdf_retrieval(client, admin_principal, exam_centre_principal):
    reg_response = _register_sample_paper(client, admin_principal)
    paper_id = reg_response.json()["paper_id"]
    client.post(
        f"/api/v1/papers/{paper_id}/authorize",
        json={"centre_id": str(exam_centre_principal.centre_id)},
        headers=auth_header(admin_principal),
    )
    resp = client.get(f"/api/v1/papers/{paper_id}/retrieve", headers=auth_header(exam_centre_principal))

    assert resp.status_code == 200
    assert resp.content == SAMPLE_PDF_BYTES  # the PDF itself is still delivered correctly
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"


def test_security_headers_present_on_error_responses(client):
    """
    The middleware wraps the entire request/exception-handling stack
    (BaseHTTPMiddleware's call_next resolves AFTER Starlette's own
    exception handling has already converted an AppException into a
    JSONResponse) — so an ordinary 401 must carry the same headers as
    a 200. This matters in practice: an attacker probing for weaknesses
    sends plenty of failing requests, and those are exactly the
    responses that must not lose this protection.
    """
    resp = client.post("/api/v1/auth/login", json={"username": "no-such-user", "password": "wrong"})
    assert resp.status_code == 401
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"


def test_docs_endpoint_is_exempt_from_csp_but_keeps_other_headers(client):
    resp = client.get("/docs")
    assert resp.status_code == 200
    assert "content-security-policy" not in {h.lower() for h in resp.headers.keys()}
    # Every OTHER header still applies, per the documented narrow exemption.
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"


# ===========================================================================
# PART B — LOGIN RATE LIMITING
# ===========================================================================


def test_login_below_limit_succeeds_normally(client, rl_user, monkeypatch):
    _user, username, password = rl_user
    resp, otp = _login_capture(client, monkeypatch, username, password)
    assert resp.status_code == 200
    assert otp is not None


def test_login_exceeding_limit_returns_429(client, rl_user, monkeypatch):
    _user, username, password = rl_user
    limit = settings.AUTH_LOGIN_RATE_LIMIT

    for _ in range(limit):
        resp, _otp = _login_capture(client, monkeypatch, username, password)
        assert resp.status_code == 200

    over_resp, _otp = _login_capture(client, monkeypatch, username, password)
    assert over_resp.status_code == 429
    body = over_resp.json()
    assert body["error"]["message"] == "Too many authentication attempts. Please try again later."
    assert "access_token" not in over_resp.text
    assert "pre_auth_token" not in over_resp.text


def test_login_rate_limit_window_resets_after_expiry(client, rl_user, monkeypatch):
    _user, username, password = rl_user
    fake_clock = _FakeClock()
    monkeypatch.setattr(auth_module._login_limiter, "_time_func", fake_clock)

    limit = settings.AUTH_LOGIN_RATE_LIMIT
    window = settings.AUTH_LOGIN_RATE_WINDOW_SECONDS

    for _ in range(limit):
        resp, _otp = _login_capture(client, monkeypatch, username, password)
        assert resp.status_code == 200

    over_resp, _otp = _login_capture(client, monkeypatch, username, password)
    assert over_resp.status_code == 429

    fake_clock.advance(window + 1)

    after_resp, otp = _login_capture(client, monkeypatch, username, password)
    assert after_resp.status_code == 200
    assert otp is not None


def test_login_rate_limit_is_per_client_identity(client, monkeypatch, db_session):
    """Proves the key is (IP + username)-scoped, not purely IP-scoped:
    exhausting one username's bucket does not affect a different
    username, even from the same TestClient "IP"."""
    role = _get_or_create_role(db_session, "Admin")
    password = "Test-RateLimit-Password-123!"
    user_a = User(
        username=f"rl_a_{uuid.uuid4().hex[:6]}", password_hash=hash_password(password), role_id=role.role_id
    )
    user_b = User(
        username=f"rl_b_{uuid.uuid4().hex[:6]}", password_hash=hash_password(password), role_id=role.role_id
    )
    db_session.add_all([user_a, user_b])
    db_session.commit()

    limit = settings.AUTH_LOGIN_RATE_LIMIT
    for _ in range(limit):
        resp, _otp = _login_capture(client, monkeypatch, user_a.username, password)
        assert resp.status_code == 200
    exhausted_resp, _otp = _login_capture(client, monkeypatch, user_a.username, password)
    assert exhausted_resp.status_code == 429

    other_resp, otp_b = _login_capture(client, monkeypatch, user_b.username, password)
    assert other_resp.status_code == 200
    assert otp_b is not None


def test_rate_limited_login_does_not_reveal_username_existence(client, monkeypatch):
    nonexistent_username = f"ghost_{uuid.uuid4().hex[:8]}"
    limit = settings.AUTH_LOGIN_RATE_LIMIT

    for _ in range(limit):
        resp, _otp = _login_capture(client, monkeypatch, nonexistent_username, "whatever-password")
        assert resp.status_code == 401  # ordinary "invalid credentials" — not yet rate-limited

    over_resp, _otp = _login_capture(client, monkeypatch, nonexistent_username, "whatever-password")
    assert over_resp.status_code == 429
    # Identical generic message to the real-user case above — a 429
    # response can never be used to infer whether the username exists.
    assert over_resp.json()["error"]["message"] == "Too many authentication attempts. Please try again later."


def test_rate_limited_login_issues_no_token(client, rl_user, monkeypatch):
    _user, username, password = rl_user
    limit = settings.AUTH_LOGIN_RATE_LIMIT
    for _ in range(limit):
        _login_capture(client, monkeypatch, username, password)

    over_resp, _otp = _login_capture(client, monkeypatch, username, password)
    assert over_resp.status_code == 429
    assert "pre_auth_token" not in over_resp.text
    assert "access_token" not in over_resp.text


# ===========================================================================
# PART C — OTP RATE LIMITING
# ===========================================================================


def test_otp_below_rate_limit_reaches_normal_verification(client, rl_user, monkeypatch):
    _user, username, password = rl_user
    login_resp, _otp = _login_capture(client, monkeypatch, username, password)
    pre_auth_token = login_resp.json()["pre_auth_token"]

    resp = _verify(client, pre_auth_token, WRONG_OTP)
    # Reached the REAL OTP logic (not a 429) — proves normal behaviour
    # is untouched below the limit.
    assert resp.status_code == 401
    assert resp.json()["error"]["message"] == "Invalid or expired OTP."


def test_otp_exceeding_rate_limit_returns_429(client, rl_user, monkeypatch):
    _user, username, password = rl_user
    login_resp, _otp = _login_capture(client, monkeypatch, username, password)
    pre_auth_token = login_resp.json()["pre_auth_token"]

    limit = settings.AUTH_OTP_RATE_LIMIT
    for _ in range(limit):
        resp = _verify(client, pre_auth_token, WRONG_OTP)
        assert resp.status_code == 401  # within rate budget (may be ordinary-wrong or 6E-1-locked, both 401)

    over_resp = _verify(client, pre_auth_token, WRONG_OTP)
    assert over_resp.status_code == 429
    assert over_resp.json()["error"]["message"] == "Too many authentication attempts. Please try again later."


def test_otp_rate_limit_window_resets_after_expiry(client, rl_user, monkeypatch):
    _user, username, password = rl_user
    login_resp, _otp = _login_capture(client, monkeypatch, username, password)
    pre_auth_token = login_resp.json()["pre_auth_token"]

    # Login already happened (on _login_limiter, a different instance);
    # swap the OTP limiter's clock in now, before any /otp/verify call.
    fake_clock = _FakeClock()
    monkeypatch.setattr(auth_module._otp_limiter, "_time_func", fake_clock)

    limit = settings.AUTH_OTP_RATE_LIMIT
    window = settings.AUTH_OTP_RATE_WINDOW_SECONDS
    for _ in range(limit):
        _verify(client, pre_auth_token, WRONG_OTP)
    over_resp = _verify(client, pre_auth_token, WRONG_OTP)
    assert over_resp.status_code == 429

    fake_clock.advance(window + 1)

    after_resp = _verify(client, pre_auth_token, WRONG_OTP)
    # No longer rate-limited — reaches real OTP logic again. Since
    # OTP_MAX_ATTEMPTS (5) was already exceeded earlier within THIS
    # challenge (limit=15 > 5), it correctly still says "Invalid or
    # expired OTP." via the Phase 6E-1 lock path, NOT a 429 — proving
    # the rate window and the OTP lock are independent in both
    # directions: the window reset, but the challenge is still locked.
    assert after_resp.status_code == 401
    assert after_resp.json()["error"]["message"] == "Invalid or expired OTP."


def test_otp_rate_limited_request_does_not_increment_failed_attempts(client, db_session, rl_user, monkeypatch):
    user, username, password = rl_user
    login_resp, _otp = _login_capture(client, monkeypatch, username, password)
    pre_auth_token = login_resp.json()["pre_auth_token"]

    limit = settings.AUTH_OTP_RATE_LIMIT
    for _ in range(limit):
        _verify(client, pre_auth_token, WRONG_OTP)

    db_session.expire_all()
    otp_row = (
        db_session.query(OtpCode)
        .filter(OtpCode.user_id == user.user_id)
        .order_by(OtpCode.created_at.desc())
        .first()
    )
    attempts_before_429 = otp_row.failed_attempts
    # Pinned at the Phase 6E-1 cap (5), not still climbing with every
    # one of the 15 requests above.
    assert attempts_before_429 == settings.OTP_MAX_ATTEMPTS

    over_resp = _verify(client, pre_auth_token, WRONG_OTP)
    assert over_resp.status_code == 429

    db_session.expire_all()
    otp_row_after = db_session.query(OtpCode).filter(OtpCode.otp_id == otp_row.otp_id).first()
    assert otp_row_after.failed_attempts == attempts_before_429  # UNCHANGED by the 429


def test_otp_challenge_locking_still_works_independently_of_rate_limiter(client, rl_user, monkeypatch):
    """Phase 6E-1's own lock behaviour, re-proven here specifically
    WITH the Phase 6E-2 rate limiter active, since the rate limit (15)
    is comfortably above OTP_MAX_ATTEMPTS (5) and must not interfere
    with the lock triggering at the right point."""
    _user, username, password = rl_user
    login_resp, otp = _login_capture(client, monkeypatch, username, password)
    pre_auth_token = login_resp.json()["pre_auth_token"]

    max_attempts = settings.OTP_MAX_ATTEMPTS
    for _ in range(max_attempts):
        resp = _verify(client, pre_auth_token, WRONG_OTP)
        assert resp.status_code == 401

    # Correct code, submitted after the Phase 6E-1 lock but still well
    # within the (larger) rate-limit budget: rejected because the
    # CHALLENGE is locked, not because of the rate limiter.
    locked_resp = _verify(client, pre_auth_token, otp)
    assert locked_resp.status_code == 401
    assert locked_resp.json()["error"]["message"] == "Invalid or expired OTP."


def test_correct_otp_still_succeeds_when_not_rate_limited_and_not_locked(client, rl_user, monkeypatch):
    _user, username, password = rl_user
    login_resp, otp = _login_capture(client, monkeypatch, username, password)
    pre_auth_token = login_resp.json()["pre_auth_token"]

    resp = _verify(client, pre_auth_token, otp)
    assert resp.status_code == 200
    assert "access_token" in resp.json()


# ===========================================================================
# MANDATORY INTERACTION TEST — rate limiter vs. Phase 6E-1 OTP lock
# ===========================================================================


def test_rate_limiter_and_otp_lock_are_independent_controls(client, db_session, rl_user, monkeypatch):
    """
    Follows the exact step sequence required for Phase 6E-2:
      1. Create an OTP challenge.
      2. Send enough wrong OTP requests to increment failed_attempts
         up to the Phase 6E-1 maximum (locking the challenge).
      3. Verify the counter.
      4. Continue sending requests against the SAME challenge until the
         independent, larger HTTP rate limit is also triggered.
      5. Verify the rate-limited request did NOT increment
         failed_attempts further.
      6. After the rate-limit window expires, verify the OTP challenge
         still has the SAME failed_attempts value (the rate window
         resetting does not un-lock the challenge).
      7. Verify normal OTP behaviour continues to work correctly for a
         genuinely FRESH challenge (a new login).
    """
    user, username, password = rl_user

    # Step 1.
    login_resp, _old_otp = _login_capture(client, monkeypatch, username, password)
    pre_auth_token = login_resp.json()["pre_auth_token"]

    # Swap in a fake clock for the OTP limiter BEFORE any /otp/verify
    # call in this test, anchored at the real time.monotonic() so it
    # stays coherent with the real clock used by _login_limiter above
    # (a different instance, unaffected either way).
    fake_clock = _FakeClock()
    monkeypatch.setattr(auth_module._otp_limiter, "_time_func", fake_clock)

    # Step 2.
    max_attempts = settings.OTP_MAX_ATTEMPTS
    for _ in range(max_attempts):
        resp = _verify(client, pre_auth_token, WRONG_OTP)
        assert resp.status_code == 401

    # Step 3.
    db_session.expire_all()
    otp_row = (
        db_session.query(OtpCode)
        .filter(OtpCode.user_id == user.user_id)
        .order_by(OtpCode.created_at.desc())
        .first()
    )
    assert otp_row.failed_attempts == max_attempts

    # Step 4.
    rate_limit = settings.AUTH_OTP_RATE_LIMIT
    assert rate_limit > max_attempts, "test assumes the rate limit exceeds the OTP attempt cap"
    remaining_before_429 = rate_limit - max_attempts
    for _ in range(remaining_before_429):
        resp = _verify(client, pre_auth_token, WRONG_OTP)
        assert resp.status_code == 401  # still the OTP-lock path, not yet rate-limited

    rate_limited_resp = _verify(client, pre_auth_token, WRONG_OTP)
    assert rate_limited_resp.status_code == 429

    # Step 5.
    db_session.expire_all()
    otp_row_after_429 = db_session.query(OtpCode).filter(OtpCode.otp_id == otp_row.otp_id).first()
    assert otp_row_after_429.failed_attempts == max_attempts

    # Step 6.
    fake_clock.advance(settings.AUTH_OTP_RATE_WINDOW_SECONDS + 1)

    post_window_resp = _verify(client, pre_auth_token, WRONG_OTP)
    assert post_window_resp.status_code == 401  # allowed THROUGH the rate limiter again...
    assert post_window_resp.json()["error"]["message"] == "Invalid or expired OTP."  # ...but still locked

    db_session.expire_all()
    otp_row_final = db_session.query(OtpCode).filter(OtpCode.otp_id == otp_row.otp_id).first()
    assert otp_row_final.failed_attempts == max_attempts  # STILL unchanged

    # Step 7.
    new_login_resp, new_otp = _login_capture(client, monkeypatch, username, password)
    assert new_login_resp.status_code == 200
    new_pre_auth_token = new_login_resp.json()["pre_auth_token"]

    success_resp = _verify(client, new_pre_auth_token, new_otp)
    assert success_resp.status_code == 200
    assert "access_token" in success_resp.json()
