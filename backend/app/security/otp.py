"""
OTP generation and delivery abstraction (SRS FR-002; LLD Section 14.2).

The OTP delivery channel is explicitly NOT YET DETERMINED in the
approved documents (SRS OQ-4, LLD DD-12) — email vs. authenticator app
has not been decided. Rather than guessing, this module defines an
abstract OTPProvider interface so the eventual channel can be plugged
in later without touching AuthService (added in a later phase).

DevConsoleOTPProvider below is a development/demo-only stand-in — it
"delivers" the OTP by logging it server-side, which is fine for a local
prototype demo but MUST NOT be mistaken for a real delivery channel.
"""

import logging
import secrets
from abc import ABC, abstractmethod

from passlib.context import CryptContext

from app.config import get_settings

logger = logging.getLogger(__name__)


class OTPDeliveryError(Exception):
    """
    Raised when no permitted OTP delivery channel is available. The message
    is deliberately generic and never contains the OTP (it may be logged).
    """


def dev_otp_logging_permitted() -> bool:
    """
    Phase 6I. The ONLY condition under which an OTP may be written to a log:
    APP_ENV is exactly "development" (case-insensitive) AND the operator has
    explicitly set OTP_DEV_LOG_ENABLED=true. Fails closed: staging,
    production, "test", a typo, or an unset flag all return False.
    """
    settings = get_settings()
    return settings.APP_ENV.strip().lower() == "development" and bool(settings.OTP_DEV_LOG_ENABLED)

_otp_hash_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def generate_otp(length: int = 6) -> str:
    """Generate a numeric OTP. Never logged in production; hashed before storage."""
    return "".join(secrets.choice("0123456789") for _ in range(length))


def hash_otp(otp: str) -> str:
    """otp_codes.otp_hash (LLD 7.8) — the raw OTP is never persisted."""
    return _otp_hash_context.hash(otp)


def verify_otp(otp: str, otp_hash: str) -> bool:
    return _otp_hash_context.verify(otp, otp_hash)


class OTPProvider(ABC):
    """Interface every real OTP delivery channel must implement."""

    @abstractmethod
    def deliver(self, user_identifier: str, otp: str) -> None:
        """Deliver the OTP to the user via the concrete channel."""
        raise NotImplementedError


class DevConsoleOTPProvider(OTPProvider):
    """
    Development-only stand-in. Logs the OTP instead of sending it.
    NOT an approved delivery channel — replace before any non-local use
    (LLD DD-12 remains open).

    Phase 6I: gated. deliver() logs the OTP only when
    dev_otp_logging_permitted() is true (APP_ENV=development AND
    OTP_DEV_LOG_ENABLED=true). Otherwise it logs nothing about the OTP and
    raises OTPDeliveryError, so the login fails safely instead of silently
    "delivering" nowhere or leaking the code. No real email/SMS/authenticator
    channel exists in this codebase.
    """

    def deliver(self, user_identifier: str, otp: str) -> None:
        if not dev_otp_logging_permitted():
            raise OTPDeliveryError("No OTP delivery channel is configured for this environment.")
        logger.warning(
            "[DEV-ONLY OTP DELIVERY] user=%s otp=%s "
            "(replace with a real channel before any non-local use)",
            user_identifier,
            otp,
        )
