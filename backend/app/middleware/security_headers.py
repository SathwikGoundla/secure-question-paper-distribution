"""
Phase 6E-2 — defensive HTTP response headers, applied to every
response this backend returns.

Scope note (read this before assuming these headers "secure the
frontend"): this backend (app/main.py) is a pure JSON + binary(PDF)
API — it serves no HTML templates and mounts no StaticFiles directory
anywhere in this project. The React frontend (../frontend) is an
entirely separate application, built and served independently of this
backend. HTTP response headers only govern how a browser treats the
EXACT response/document they are attached to; a header on this API's
JSON/PDF response cannot reach across and affect a different origin's
already-loaded HTML page. These headers are defense-in-depth for this
API's OWN responses (e.g. a browser pointed directly at an endpoint,
or any future HTML error page), not a substitute for the frontend
host's own security configuration, which is out of scope here.

Registered exactly once, in app/main.py (register_security_headers).
Do not add a second copy of this middleware, and do not set any of
these same header names again anywhere else in the codebase — that
would risk silently-overwritten or duplicated header values.
"""

from __future__ import annotations

from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.config import get_settings

# FastAPI's own interactive API documentation (Swagger UI at /docs,
# ReDoc at /redoc, backed by /openapi.json) is enabled at its library
# defaults — app/main.py does not pass docs_url=None. Swagger UI/ReDoc
# load their JS/CSS from a CDN and inject an inline bootstrap
# <script>, so they cannot function under this API's strict default
# CSP (Content-Security-Policy: default-src 'none') without weakening
# that policy with 'unsafe-inline'/an external script-src allowance
# for every OTHER endpoint too. Rather than weaken the policy globally
# just to keep an optional developer-facing docs page working, these
# three exact paths are exempted from the CSP header ONLY — every
# OTHER header below (X-Content-Type-Options, X-Frame-Options,
# Referrer-Policy, Permissions-Policy) still applies to them. This is
# a narrow, deliberate, documented trade-off, not an oversight.
_CSP_EXEMPT_PATHS = frozenset({"/docs", "/redoc", "/openapi.json"})

# Pure data API, nothing here is ever meant to be loaded as a
# sub-resource or framed by anything — the strictest available policy
# is used for every response except the three paths above.
_API_CONTENT_SECURITY_POLICY = "default-src 'none'; frame-ancestors 'none'"

# This API has no legitimate use for any of these browser features;
# explicitly denying them costs nothing and is safe for every path,
# including the CSP-exempt docs pages.
_PERMISSIONS_POLICY = "camera=(), microphone=(), geolocation=(), payment=()"

_HSTS_VALUE = "max-age=63072000; includeSubDomains"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = _PERMISSIONS_POLICY

        if request.url.path not in _CSP_EXEMPT_PATHS:
            response.headers["Content-Security-Policy"] = _API_CONTENT_SECURITY_POLICY

        settings = get_settings()
        # HSTS instructs browsers to enforce HTTPS for FUTURE requests
        # to this exact origin. Per RFC 6797 Section 8.1, browsers
        # already ignore this header when it arrives over plain HTTP —
        # but this backend does not even rely on that: it only ever
        # SENDS the header when BOTH (a) settings.APP_ENV == "production"
        # (the project's existing environment setting, app/config.py)
        # AND (b) this specific request actually arrived over HTTPS
        # (request.url.scheme == "https"). A developer running
        # `uvicorn app.main:app --reload` against http://localhost —
        # in ANY APP_ENV value — therefore never receives this header,
        # so local HTTP development is never affected by it.
        if settings.APP_ENV == "production" and request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = _HSTS_VALUE

        return response


def register_security_headers(app: FastAPI) -> None:
    app.add_middleware(SecurityHeadersMiddleware)
