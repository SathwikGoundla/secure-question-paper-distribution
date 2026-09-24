"""
Password hashing (SRS FR-001, SEC-010; LLD Section 14.1).

Passwords are NEVER stored or compared in plaintext. The exact hashing
algorithm was NOT YET DETERMINED in the LLD; bcrypt (via passlib) is
used here as the Phase-1 working default — a well-established adaptive
hash appropriate for this use case.
"""

from passlib.context import CryptContext

from app.config import get_settings

settings = get_settings()

_pwd_context = CryptContext(schemes=[settings.PASSWORD_HASH_SCHEME], deprecated="auto")


def hash_password(plain_password: str) -> str:
    """Return a salted hash of the given plaintext password. Never log the input."""
    return _pwd_context.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Compare a plaintext password against a stored hash. Constant-time via passlib."""
    return _pwd_context.verify(plain_password, password_hash)
