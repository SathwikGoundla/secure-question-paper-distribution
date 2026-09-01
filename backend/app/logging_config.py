"""
Application logging configuration.

This is standard operational logging (startup, requests, errors) — it is
NOT the audit trail. The audit trail (SRS FR-017, FR-028) is a separate,
security-relevant concept implemented later via AuditService writing to
the audit_events / exam_security_events tables and Hyperledger Fabric
(LLD Section 19, 24). Never log secrets (passwords, JWT secrets, AES
keys, OTP codes) at any level.
"""

import logging
import sys

from app.config import get_settings


def configure_logging() -> None:
    settings = get_settings()

    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Avoid duplicate handlers if configure_logging() is called more than once
    # (e.g. under the test runner reloading the app).
    root_logger.handlers = [handler]

    # Quiet noisy third-party loggers at DEBUG unless explicitly requested.
    if log_level > logging.DEBUG:
        logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
        logging.getLogger("uvicorn.access").setLevel(logging.INFO)
