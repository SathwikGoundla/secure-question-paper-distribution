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
from dataclasses import dataclass

import pyotp
import segno
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import get_settings

TOTP_DIGITS = 6
TOTP_INTERVAL_SECONDS = 30
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


# --------------------------------------------------------------------------- keyring (Phase 7B)

LEGACY_KEY_ID = "legacy"
_KEY_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,32}$")


@dataclass(frozen=True)
class Keyring:
    """All TOTP encryption keys that may be needed, and which one encrypts NEW secrets."""

    keys: dict[str, bytes]
    active_id: str

    @property
    def active_key(self) -> bytes:
        return self.keys[self.active_id]

    def only(self, key_id: str) -> "Keyring":
        """A keyring containing just one key (used to PROVE a key alone suffices after rotation)."""
        return Keyring({key_id: self.keys[key_id]}, key_id)


def _decode_key(raw: str, label: str) -> bytes:
    try:
        key = base64.b64decode(raw.strip(), validate=True)
    except Exception as exc:  # noqa: BLE001 - never echo the value
        raise TotpConfigError(f"{label} is not valid base64.") from exc
    if len(key) != 32:
        raise TotpConfigError(f"{label} must decode to exactly 32 bytes.")
    return key


def load_keyring() -> Keyring:
    """
    Build and validate the keyring from configuration:
      * TOTP_ENCRYPTION_KEY            -> key id "legacy" (the Phase 7A key; unchanged meaning)
      * TOTP_ENCRYPTION_KEYS           -> "id=base64,id2=base64"
      * TOTP_ACTIVE_KEY_ID             -> the key used for new encryptions
    Raises TotpConfigError (secret-free message) if nothing is configured, a key is malformed, an id
    is invalid/duplicated, two ids share the same key material, any key equals the paper master key,
    or the active key is ambiguous/unknown. Key material is never echoed.
    """
    settings = get_settings()
    keys: dict[str, bytes] = {}

    legacy_raw = (settings.TOTP_ENCRYPTION_KEY or "").strip()
    if legacy_raw:
        keys[LEGACY_KEY_ID] = _decode_key(legacy_raw, "TOTP_ENCRYPTION_KEY")

    extra = (settings.TOTP_ENCRYPTION_KEYS or "").strip()
    if extra:
        for entry in extra.split(","):
            entry = entry.strip()
            if not entry:
                continue
            key_id, sep, raw = entry.partition("=")
            key_id = key_id.strip()
            if not sep or not _KEY_ID_RE.fullmatch(key_id):
                raise TotpConfigError("TOTP_ENCRYPTION_KEYS must look like 'id=base64key,id2=base64key' with simple ids.")
            if key_id == LEGACY_KEY_ID:
                raise TotpConfigError("The key id 'legacy' is reserved for TOTP_ENCRYPTION_KEY.")
            if key_id in keys:
                raise TotpConfigError(f"Duplicate TOTP key id '{key_id}'.")
            keys[key_id] = _decode_key(raw, f"TOTP_ENCRYPTION_KEYS entry '{key_id}'")

    if not keys:
        raise TotpConfigError("TOTP_ENCRYPTION_KEY is not configured.")

    master = (settings.QUESTION_PAPER_MASTER_KEY or "").strip()
    if master:
        try:
            master_bytes = base64.b64decode(master, validate=True)
        except Exception:  # noqa: BLE001
            master_bytes = master.encode()
        for key_id, key in keys.items():
            if hmac.compare_digest(master_bytes, key) or hmac.compare_digest(master.encode(), base64.b64encode(key)):
                raise TotpConfigError("TOTP_ENCRYPTION_KEY must differ from QUESTION_PAPER_MASTER_KEY.")

    values = list(keys.values())
    if len({bytes(v) for v in values}) != len(values):
        raise TotpConfigError("Each TOTP encryption key id must have distinct key material.")

    active = (settings.TOTP_ACTIVE_KEY_ID or "").strip()
    if not active:
        if len(keys) == 1:
            active = next(iter(keys))
        else:
            raise TotpConfigError("TOTP_ACTIVE_KEY_ID must be set when more than one TOTP key is configured.")
    if active not in keys:
        raise TotpConfigError("TOTP_ACTIVE_KEY_ID does not match any configured TOTP key id.")
    return Keyring(keys, active)


def load_encryption_key() -> bytes:
    """Compatibility wrapper (Phase 7A name): the ACTIVE key. Validates the whole keyring."""
    return load_keyring().active_key


# --------------------------------------------------------------------------- secrets at rest
#
# Envelope formats (stored in user_totp.secret_encrypted):
#   v1 (Phase 7A):  b"v1" + nonce(12) + AESGCM(ct||tag),            AAD = user_id            key id = "legacy"
#   v2 (Phase 7B):  b"v2" + len(kid)(1) + kid + nonce(12) + ct||tag, AAD = b"v2|" + kid + b"|" + user_id
# v2 carries the key id so a record says which key decrypts it, and binds the id (and user) as
# authenticated data so neither can be altered. v1 records are never reinterpreted: they are read as
# v1 under the "legacy" key and are rewritten as v2 by the rotation utility.


class TotpKeyUnavailableError(TotpDecryptError):
    """The record names a key that is not in the configured keyring (e.g. an old key was retired too early)."""


def generate_secret() -> str:
    """160-bit random base32 secret (pyotp's CSPRNG-backed generator)."""
    return pyotp.random_base32(length=32)


def _v2_aad(key_id: str, user_id: uuid.UUID) -> bytes:
    return b"v2|" + key_id.encode("ascii") + b"|" + user_id.bytes


def encrypt_secret(secret_b32: str, user_id: uuid.UUID, keyring: Keyring | None = None) -> bytes:
    """Always writes the current (v2) format under the ACTIVE key."""
    ring = keyring or load_keyring()
    kid = ring.active_id.encode("ascii")
    nonce = os.urandom(_NONCE_BYTES)
    ct = AESGCM(ring.active_key).encrypt(nonce, secret_b32.encode("ascii"), _v2_aad(ring.active_id, user_id))
    return b"v2" + bytes([len(kid)]) + kid + nonce + ct


def envelope_info(blob: bytes) -> tuple[str, str]:
    """(version, key_id) of a stored envelope WITHOUT decrypting it. Raises TotpDecryptError if malformed."""
    if not blob or len(blob) < 2 + _NONCE_BYTES + 16:
        raise TotpDecryptError("unsupported or truncated secret envelope")
    if blob.startswith(b"v1"):
        return "v1", LEGACY_KEY_ID
    if blob.startswith(b"v2"):
        kid_len = blob[2]
        if kid_len < 1 or len(blob) < 3 + kid_len + _NONCE_BYTES + 16:
            raise TotpDecryptError("unsupported or truncated secret envelope")
        try:
            kid = blob[3 : 3 + kid_len].decode("ascii")
        except UnicodeDecodeError as exc:
            raise TotpDecryptError("malformed key id") from exc
        if not _KEY_ID_RE.fullmatch(kid):
            raise TotpDecryptError("malformed key id")
        return "v2", kid
    raise TotpDecryptError("unsupported or truncated secret envelope")


def decrypt_secret(blob: bytes, user_id: uuid.UUID, keyring: Keyring | None = None) -> str:
    ring = keyring or load_keyring()
    version, kid = envelope_info(blob)
    key = ring.keys.get(kid)
    if key is None:
        raise TotpKeyUnavailableError("the key that encrypted this secret is not configured")
    try:
        if version == "v1":
            nonce, ct, aad = blob[2 : 2 + _NONCE_BYTES], blob[2 + _NONCE_BYTES :], user_id.bytes
        else:
            start = 3 + len(kid)
            nonce, ct, aad = blob[start : start + _NONCE_BYTES], blob[start + _NONCE_BYTES :], _v2_aad(kid, user_id)
        return AESGCM(key).decrypt(nonce, ct, aad).decode("ascii")
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
