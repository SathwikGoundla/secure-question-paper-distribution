"""
TOTP helpers — Phase 7A (RFC 6238 via the maintained `pyotp` library).

No cryptographic primitive is implemented here. This module only:
  * validates/loads the dedicated TOTP encryption key,
  * encrypts/decrypts per-user TOTP secrets at rest (AES-256-GCM, bound to the
    user id as associated data so a ciphertext cannot be moved to another user),
  * matches a submitted code against the accepted time-step window in constant
    time and reports WHICH step matched (needed for replay prevention),
  * builds the provisioning URI / QR for enrollment.

Parameters: SHA-1, 6 digits, 30-second step. These are the defaults every
mainstream authenticator app supports (Google Authenticator, Microsoft
Authenticator, Authy, FreeOTP, ...); stronger algorithms are not reliably
supported by apps, so they are intentionally NOT used.

Nothing here ever logs a secret or a code.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import time
import uuid

import pyotp
import segno
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import get_settings

TOTP_DIGITS = 6
TOTP_INTERVAL_SECONDS = 30
_ENVELOPE_VERSION = b"v1"
_NONCE_BYTES = 12
_CODE_RE = re.compile(r"^[0-9]{6}$")

# No look-alike characters (0/O, 1/I/L) so an operator can read a code aloud.
_ENROLLMENT_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


class TotpConfigError(Exception):
    """Required TOTP security configuration is missing or invalid. Message is generic and secret-free."""


class TotpDecryptError(Exception):
    """A stored secret could not be decrypted (wrong key / tampered / wrong user)."""


def current_time() -> float:
    """Single seam for 'now' so tests can control the clock."""
    return time.time()


def current_step(now: float | None = None) -> int:
    return int((current_time() if now is None else now) // TOTP_INTERVAL_SECONDS)


# --------------------------------------------------------------------------- key handling


def load_encryption_key() -> bytes:
    """
    Load TOTP_ENCRYPTION_KEY (base64 of exactly 32 bytes). Raises TotpConfigError
    if absent, malformed, or identical to the question-paper master key (the two
    keys must be independent so compromising one does not expose the other).
    """
    settings = get_settings()
    raw = (settings.TOTP_ENCRYPTION_KEY or "").strip()
    if not raw:
        raise TotpConfigError("TOTP_ENCRYPTION_KEY is not configured.")
    try:
        key = base64.b64decode(raw, validate=True)
    except Exception as exc:  # noqa: BLE001 - never echo the value
        raise TotpConfigError("TOTP_ENCRYPTION_KEY is not valid base64.") from exc
    if len(key) != 32:
        raise TotpConfigError("TOTP_ENCRYPTION_KEY must decode to exactly 32 bytes.")
    master = (settings.QUESTION_PAPER_MASTER_KEY or "").strip()
    if master and hmac.compare_digest(master.encode(), raw.encode()):
        raise TotpConfigError("TOTP_ENCRYPTION_KEY must differ from QUESTION_PAPER_MASTER_KEY.")
    return key


# --------------------------------------------------------------------------- secrets at rest


def generate_secret() -> str:
    """160-bit random base32 secret (pyotp's CSPRNG-backed generator)."""
    return pyotp.random_base32(length=32)


def encrypt_secret(secret_b32: str, user_id: uuid.UUID) -> bytes:
    key = load_encryption_key()
    nonce = os.urandom(_NONCE_BYTES)
    ct = AESGCM(key).encrypt(nonce, secret_b32.encode("ascii"), user_id.bytes)
    return _ENVELOPE_VERSION + nonce + ct


def decrypt_secret(blob: bytes, user_id: uuid.UUID) -> str:
    key = load_encryption_key()
    if not blob or not blob.startswith(_ENVELOPE_VERSION) or len(blob) < len(_ENVELOPE_VERSION) + _NONCE_BYTES + 16:
        raise TotpDecryptError("unsupported or truncated secret envelope")
    body = blob[len(_ENVELOPE_VERSION):]
    nonce, ct = body[:_NONCE_BYTES], body[_NONCE_BYTES:]
    try:
        return AESGCM(key).decrypt(nonce, ct, user_id.bytes).decode("ascii")
    except (InvalidTag, ValueError) as exc:
        raise TotpDecryptError("secret could not be decrypted") from exc


# --------------------------------------------------------------------------- code matching


def match_code(secret_b32: str, submitted: str, window: int, now: float | None = None) -> int | None:
    """
    Return the matched 30-second step number, or None.

    Every candidate step in [now-window, now+window] is evaluated (no early
    exit) and compared in constant time, so timing does not reveal which
    position matched. A malformed submission (not exactly six digits) never matches.
    """
    if not isinstance(submitted, str) or not _CODE_RE.fullmatch(submitted):
        return None
    totp = pyotp.TOTP(secret_b32, digits=TOTP_DIGITS, interval=TOTP_INTERVAL_SECONDS)
    center = current_step(now)
    matched: int | None = None
    for step in range(center - window, center + window + 1):
        expected = totp.at(step * TOTP_INTERVAL_SECONDS)
        if hmac.compare_digest(expected.encode(), submitted.encode()) and (matched is None or step > matched):
            matched = step
    return matched


# --------------------------------------------------------------------------- enrollment helpers


def generate_enrollment_code() -> str:
    """One-time enrollment code, 12 symbols (~59 bits), shown as XXXX-XXXX-XXXX."""
    raw = "".join(secrets.choice(_ENROLLMENT_ALPHABET) for _ in range(12))
    return f"{raw[0:4]}-{raw[4:8]}-{raw[8:12]}"


def normalize_enrollment_code(code: str) -> str:
    return re.sub(r"[\s-]", "", (code or "")).upper()


def hash_enrollment_code(code: str) -> str:
    # The code is random and high-entropy (not a user-chosen password), and is
    # additionally attempt-limited and expiring, so a fast hash is appropriate.
    return hashlib.sha256(normalize_enrollment_code(code).encode()).hexdigest()


def provisioning_uri(secret_b32: str, account_name: str) -> str:
    return pyotp.TOTP(secret_b32, digits=TOTP_DIGITS, interval=TOTP_INTERVAL_SECONDS).provisioning_uri(
        name=account_name, issuer_name=get_settings().TOTP_ISSUER
    )


def qr_svg_data_uri(uri: str) -> str:
    """Inline SVG data URI of the provisioning QR (no image library, no network)."""
    return segno.make(uri, error="m").svg_data_uri(scale=5, border=2)
