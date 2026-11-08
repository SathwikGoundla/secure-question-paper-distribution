"""
FastAPI application entry point.

Run with:
    uvicorn app.main:app --reload

See backend/README.md for full setup instructions.
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.config import get_settings
from app.exceptions.handlers import register_exception_handlers
from app.logging_config import configure_logging
from app.middleware.security_headers import register_security_headers

configure_logging()
logger = logging.getLogger(__name__)

settings = get_settings()

app = FastAPI(
    title=settings.APP_NAME,
    description=(
        "Backend for the Blockchain-Enabled Secure Question Paper Distribution "
        "and Controlled Examination Access Framework. "
        "Implementation status: Phase 1 (foundation) only — see docs/PHASE1_IMPLEMENTATION_STATUS.md."
    ),
    version="0.1.0-phase1",
)

# The frontend never talks to the database, storage, or blockchain layer
# directly (HLD Section 6) — it only ever calls this API over HTTPS.
# Phase 6I: CORS is restricted to what the actual routes and the actual
# frontend client (frontend/src/api/client.ts) use.
#   * Methods: the routes define only GET, POST and PATCH (no PUT/DELETE).
#     The preflight itself is an OPTIONS request that CORSMiddleware answers
#     without OPTIONS being listed.
#   * Headers: the client sends Accept, Authorization and Content-Type
#     (multipart uploads send a Content-Type that is already CORS-safelisted).
#   * Credentials: authentication is a Bearer token in the Authorization
#     header; the client never uses cookies or credentials: "include", so
#     Access-Control-Allow-Credentials is NOT sent.
#   * Origins: explicit list from CORS_ORIGINS (a "*" is rejected at startup);
#     no fallback. A browser enforces this; non-browser clients (curl, other
#     servers) ignore CORS entirely, so it is not an authentication control.
CORS_ALLOWED_METHODS = ["GET", "POST", "PATCH"]
CORS_ALLOWED_HEADERS = ["Accept", "Authorization", "Content-Type"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=False,
    allow_methods=CORS_ALLOWED_METHODS,
    allow_headers=CORS_ALLOWED_HEADERS,
)

# Phase 6E-2: X-Content-Type-Options, X-Frame-Options, Referrer-Policy,
# Permissions-Policy, Content-Security-Policy, and environment-gated
# HSTS on every response (app/middleware/security_headers.py). Added
# once, here — see that module's docstring for exactly what each
# header does and does not affect.
register_security_headers(app)

register_exception_handlers(app)

app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.on_event("startup")
def on_startup() -> None:
    logger.info("Starting %s [env=%s]", settings.APP_NAME, settings.APP_ENV)
    if settings.OTP_DEV_LOG_ENABLED and settings.APP_ENV.strip().lower() != "development":
        # Phase 6I: harmless misconfiguration, but worth flagging. OTPs are NOT
        # logged outside development; sign-in will be refused (HTTP 503).
        logger.warning(
            "OTP_DEV_LOG_ENABLED is set but APP_ENV is not 'development'; the flag is ignored "
            "and no OTP delivery channel is available, so sign-in will be refused."
        )
    logger.info("API mounted at %s", settings.API_V1_PREFIX)


@app.get("/", tags=["root"])
def root() -> dict:
    return {
        "message": settings.APP_NAME,
        "docs": "/docs",
        "health": f"{settings.API_V1_PREFIX}/health",
    }
