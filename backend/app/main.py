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
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
    logger.info("API mounted at %s", settings.API_V1_PREFIX)


@app.get("/", tags=["root"])
def root() -> dict:
    return {
        "message": settings.APP_NAME,
        "docs": "/docs",
        "health": f"{settings.API_V1_PREFIX}/health",
    }
