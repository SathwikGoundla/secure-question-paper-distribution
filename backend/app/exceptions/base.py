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

    def __init__(self, message: str | None = None):
        self.message = message or self.default_message
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
