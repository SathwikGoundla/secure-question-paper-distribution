"""
Central exception handling.

Ensures every error returned by the API has a consistent JSON shape and
that unexpected (unhandled) exceptions never leak internal detail
(stack traces, secrets, SQL errors) to the client — they are logged
server-side and returned as a generic 500 instead.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.exceptions.base import AppException

logger = logging.getLogger(__name__)


def _error_body(message: str, status_code: int) -> dict:
    return {"error": {"message": message, "status_code": status_code}}


def register_exception_handlers(app: FastAPI) -> None:

    @app.exception_handler(AppException)
    async def handle_app_exception(request: Request, exc: AppException) -> JSONResponse:
        logger.warning("AppException on %s %s: %s", request.method, request.url.path, exc.message)
        response = JSONResponse(
            status_code=exc.status_code,
            content=_error_body(exc.message, exc.status_code),
        )
        # Phase 6E-2: a small, explicit allow-list of extra headers an
        # exception may request (currently only Retry-After, set by
        # TooManyRequestsException). Never anything derived from
        # internal state, secrets, or tokens — see AppException.__init__.
        if exc.extra_headers:
            response.headers.update(exc.extra_headers)
        return response

    @app.exception_handler(Exception)
    async def handle_unexpected_exception(request: Request, exc: Exception) -> JSONResponse:
        # Full detail goes to the server log only — never to the response body.
        logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content=_error_body("An internal server error occurred.", 500),
        )
