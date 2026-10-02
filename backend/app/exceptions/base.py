"""
Application-level exception hierarchy.

Using typed exceptions (instead of raising HTTPException everywhere in
business logic) keeps the services layer (LLD Section 5, 24) independent
of the web framework, and gives one place (exceptions/handlers.py) that
controls exactly what error detail is ever returned to a client — so
internal errors never leak stack traces or secrets in API responses.
"""


class AppException(Exception):
    """Base class for all handled application exceptions."""

    status_code: int = 500
    default_message: str = "An unexpected error occurred."

    def __init__(self, message: str | None = None, extra_headers: dict[str, str] | None = None):
        self.message = message or self.default_message
        # Phase 6E-2 addition: lets a specific exception (e.g.
        # TooManyRequestsException's Retry-After) attach safe,
        # non-sensitive extra response headers without every other
        # exception type or the generic handler needing to know about
        # it. Empty by default — every exception from before this
        # phase behaves exactly as before.
        self.extra_headers: dict[str, str] = extra_headers or {}
        super().__init__(self.message)


class NotFoundException(AppException):
    status_code = 404
    default_message = "The requested resource was not found."


class UnauthorizedException(AppException):
    """Authentication failed or is missing (maps to HTTP 401)."""
    status_code = 401
    default_message = "Authentication is required or has failed."


class ForbiddenException(AppException):
    """Authenticated but not permitted to perform this action (HTTP 403)."""
    status_code = 403
    default_message = "You do not have permission to perform this action."


class ValidationFailedException(AppException):
    status_code = 400
    default_message = "Invalid request data."


class ConflictException(AppException):
    """
    Used for state conflicts — e.g. SHA-256 integrity mismatch
    (SRS FR-010/FR-011) maps to HTTP 409, matching LLD Section 6, API-07.
    """
    status_code = 409
    default_message = "The request conflicts with the current state of the resource."


class ServiceUnavailableException(AppException):
    """
    Reserved for dependency failures (storage, Hyperledger Fabric).
    Exact retry/failure policy is NOT YET DETERMINED per LLD Section 18 —
    this exception exists so that gap is visible in code, not silently
    papered over.
    """
    status_code = 503
    default_message = "A required service is temporarily unavailable."


class UnsupportedOperationException(AppException):
    """
    Phase 5C addition. Raised when a caller invokes an operation that
    the currently *configured backend* genuinely does not implement —
    e.g. a BlockchainService method with no corresponding transaction
    in the deployed Fabric chaincode (5 of BlockchainService's 9
    CC-01..CC-09 methods; see fabric_blockchain_service.py). Maps to
    HTTP 501 Not Implemented.

    Deliberately distinct from Python's built-in NotImplementedError,
    which in this codebase signals a *configuration* error (an unknown
    BLOCKCHAIN_BACKEND value) rather than a normal, expected, per-call
    condition a caller can catch and handle.
    """
    status_code = 501
    default_message = "This operation is not supported by the currently configured backend."


class TooManyRequestsException(AppException):
    """
    Phase 6E-2 addition. Raised by the authentication rate limiter
    (app/security/rate_limiter.py) when POST /auth/login or
    POST /auth/otp/verify is called more than the configured number of
    times, for the same client-identity key, within the configured
    window. Maps to HTTP 429 Too Many Requests.

    The message is deliberately generic and identical regardless of
    WHY the limit was hit (unknown username, wrong password, wrong
    OTP, exhausted OTP challenge, ...) — it must never be usable to
    infer anything about account existence or OTP/password
    correctness. retry_after_seconds, when known, is surfaced only via
    the standard Retry-After response header (set in
    exceptions/handlers.py from extra_headers), never in the JSON body
    text itself.
    """
    status_code = 429
    default_message = "Too many authentication attempts. Please try again later."

    def __init__(self, message: str | None = None, retry_after_seconds: int | None = None):
        extra_headers = {}
        if retry_after_seconds is not None and retry_after_seconds > 0:
            extra_headers["Retry-After"] = str(retry_after_seconds)
        super().__init__(message, extra_headers=extra_headers)
