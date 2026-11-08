"""
Phase 6I — CORS is restricted to what the routes and the frontend actually use.

What these tests prove, and what they cannot:

* They drive Starlette's real CORSMiddleware through the FastAPI
  TestClient with Origin / Access-Control-Request-* headers, so they test
  the exact allow/deny decisions the server makes and the exact headers a
  browser would read.
* A browser is what ENFORCES CORS (it hides the response from page
  JavaScript, or refuses to send the real request after a failed
  preflight). The server cannot block a non-browser client (curl, another
  server) and does not try to: CORS is not an authentication control, and
  every protected route still requires a valid JWT and the right role.
* Behaviour that depends on the deployment (a reverse proxy that rewrites
  Origin or adds its own CORS headers, a different frontend origin) is not
  testable here; the allowed origin comes from CORS_ORIGINS.

Derivation of the policy (from the code, not assumed):
  methods  — the routes define only GET, POST and PATCH (asserted below
             against app.routes so a future PUT/DELETE route fails the
             test until CORS is reviewed);
  headers  — frontend/src/api/client.ts sends Accept, Authorization and,
             for JSON bodies, Content-Type;
  credentials — authentication is a Bearer header; the client never uses
             cookies, so Access-Control-Allow-Credentials is not sent.
"""

import pytest
from fastapi.routing import APIRoute
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.main import CORS_ALLOWED_HEADERS, CORS_ALLOWED_METHODS, app
from tests.conftest import auth_header

APPROVED = get_settings().cors_origins_list[0]
EVIL = "https://evil.example"
API = "/api/v1"
PAPER = "00000000-0000-0000-0000-000000000001"

# A representative real route for each method the frontend uses.
METHOD_ROUTES = {
    "GET": f"{API}/auth/me",
    "POST": f"{API}/papers/register",
    "PATCH": f"{API}/papers/{PAPER}/schedule",
}


def _preflight(client, path, method, headers="authorization,content-type", origin=APPROVED):
    h = {"Origin": origin, "Access-Control-Request-Method": method}
    if headers is not None:
        h["Access-Control-Request-Headers"] = headers
    return client.options(path, headers=h)


# ---------------------------------------------------------------------------
# Policy is derived from reality
# ---------------------------------------------------------------------------


def test_cors_methods_cover_exactly_the_methods_the_routes_define():
    route_methods = set()
    for route in app.routes:
        if isinstance(route, APIRoute):
            route_methods |= route.methods
    route_methods -= {"HEAD", "OPTIONS"}
    assert route_methods == {"GET", "POST", "PATCH"}
    assert set(CORS_ALLOWED_METHODS) == route_methods


def test_cors_headers_are_exactly_what_the_frontend_client_sends():
    assert {h.lower() for h in CORS_ALLOWED_HEADERS} == {"accept", "authorization", "content-type"}


def test_no_wildcards_are_configured():
    assert "*" not in CORS_ALLOWED_METHODS and "*" not in CORS_ALLOWED_HEADERS
    assert "*" not in get_settings().cors_origins_list


def test_a_wildcard_origin_is_rejected_at_configuration_time():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, CORS_ORIGINS="*")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, CORS_ORIGINS="http://localhost:3000, *")


# ---------------------------------------------------------------------------
# Preflight: approved origin, every required method, required headers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["GET", "POST", "PATCH"])
def test_preflight_succeeds_for_every_required_method(client, method):
    resp = _preflight(client, METHOD_ROUTES[method], method)
    assert resp.status_code == 200, resp.text
    assert resp.headers["access-control-allow-origin"] == APPROVED
    allowed = {m.strip() for m in resp.headers["access-control-allow-methods"].split(",")}
    assert method in allowed
    allow_headers = {h.strip().lower() for h in resp.headers["access-control-allow-headers"].split(",")}
    assert {"authorization", "content-type"} <= allow_headers


@pytest.mark.parametrize("requested", ["authorization", "content-type", "accept", "Authorization, Content-Type, Accept"])
def test_each_required_request_header_is_permitted(client, requested):
    assert _preflight(client, METHOD_ROUTES["POST"], "POST", headers=requested).status_code == 200


def test_preflight_without_requested_headers_succeeds(client):
    assert _preflight(client, METHOD_ROUTES["GET"], "GET", headers=None).status_code == 200


# ---------------------------------------------------------------------------
# Preflight: rejections
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["PUT", "DELETE", "TRACE", "CONNECT"])
def test_preflight_rejects_methods_no_route_uses(client, method):
    resp = _preflight(client, METHOD_ROUTES["GET"], method)
    assert resp.status_code == 400
    assert "Disallowed CORS method" in resp.text
    assert method not in resp.headers.get("access-control-allow-methods", "")


@pytest.mark.parametrize(
    "requested",
    ["x-custom-header", "authorization,x-api-key", "x-forwarded-for", "cookie", "x-http-method-override"],
)
def test_preflight_rejects_unnecessary_request_headers(client, requested):
    resp = _preflight(client, METHOD_ROUTES["POST"], "POST", headers=requested)
    assert resp.status_code == 400
    assert "Disallowed CORS headers" in resp.text


def test_preflight_from_an_unapproved_origin_is_rejected_with_no_allow_origin(client):
    resp = _preflight(client, METHOD_ROUTES["POST"], "POST", origin=EVIL)
    assert resp.status_code == 400
    assert "Disallowed CORS origin" in resp.text
    assert "access-control-allow-origin" not in resp.headers


@pytest.mark.parametrize("origin", ["null", "http://localhost:3000.evil.example", "http://localhost:3001", "https://localhost:3000"])
def test_look_alike_origins_are_rejected(client, origin):
    assert _preflight(client, METHOD_ROUTES["GET"], "GET", origin=origin).status_code == 400


def test_preflight_never_answers_with_wildcards(client):
    resp = _preflight(client, METHOD_ROUTES["POST"], "POST")
    for name in ("access-control-allow-origin", "access-control-allow-methods", "access-control-allow-headers"):
        assert "*" not in resp.headers[name]


# ---------------------------------------------------------------------------
# Actual (non-preflight) requests
# ---------------------------------------------------------------------------


def test_approved_origin_actual_request_gets_the_cors_header(client):
    resp = client.get(f"{API}/health", headers={"Origin": APPROVED})
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == APPROVED
    assert "origin" in resp.headers.get("vary", "").lower()


def test_unapproved_origin_actual_request_gets_no_cors_header(client):
    # The server still answers (CORS is enforced by the browser, not the server);
    # without the header a browser will not expose the body to the page's script.
    resp = client.get(f"{API}/health", headers={"Origin": EVIL})
    assert resp.status_code == 200
    assert "access-control-allow-origin" not in resp.headers


def test_credentials_are_not_allowed_because_auth_is_a_bearer_header(client):
    simple = client.get(f"{API}/health", headers={"Origin": APPROVED})
    pre = _preflight(client, METHOD_ROUTES["POST"], "POST")
    assert "access-control-allow-credentials" not in simple.headers
    assert "access-control-allow-credentials" not in pre.headers


def test_authenticated_request_from_the_approved_origin_still_works_end_to_end(client, admin_principal):
    headers = {**auth_header(admin_principal), "Origin": APPROVED}
    resp = client.get(f"{API}/auth/me", headers=headers)
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == APPROVED


def test_cors_does_not_replace_authentication(client):
    # An approved origin with no token is still rejected by the route itself.
    resp = client.get(f"{API}/auth/me", headers={"Origin": APPROVED})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Existing security response headers are unaffected
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("make", ["simple", "preflight", "unapproved"])
def test_security_headers_are_still_present(client, make):
    if make == "simple":
        resp = client.get(f"{API}/health", headers={"Origin": APPROVED})
    elif make == "preflight":
        resp = _preflight(client, METHOD_ROUTES["GET"], "GET")
    else:
        resp = client.get(f"{API}/health", headers={"Origin": EVIL})
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert "referrer-policy" in resp.headers
