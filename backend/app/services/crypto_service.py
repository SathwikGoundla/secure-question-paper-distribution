"""
CryptoService — Phase 3 (SRS FR-008/FR-009/SEC-001/SEC-002/SEC-010;
LLD Section 4.4, 4.5, 12, 13).

Implements the two cryptographic mechanisms the whole project is named
after:
  - AES-256-GCM  : confidentiality (FR-008) via AUTHENTICATED encryption
                   (GCM's tag catches ciphertext tampering during
                   decryption itself — this is the FIRST tamper-detection
                   gate, independent of the SHA-256 check below).
  - SHA-256      : integrity verification (FR-009).

PROJECT DECISION — explicit deviation from LLD Section 13, documented
here rather than silently changed:

  LLD Section 13 originally specified hashing the ENCRYPTED file, so
  integrity could be verified BEFORE decryption (LLD Section 17, Step 6
  happens before Step 7 Decrypt). This Phase-3 implementation instead
  hashes the ORIGINAL PLAINTEXT PDF, per an explicit, repeated
  instruction for this phase. Consequence: the SHA-256 comparison can
  only happen AFTER decryption succeeds, not before. The pre-decryption
  tamper gate is therefore now provided by the AES-GCM authentication
  tag (raises CryptoError on ANY ciphertext/tag tampering before any
  plaintext is produced) rather than by the SHA-256 hash. The SHA-256
  check that follows a successful decryption is a SECOND, independent
  integrity confirmation over the recovered plaintext. Both checks
  must pass before a paper is ever released — see paper_service.py.

  This is recorded as a project decision, not silently absorbed:
  reconciling LLD Section 13's wording with this implementation is
  flagged as follow-up documentation work in PROJECT_STATE.md.

KEY MANAGEMENT — envelope encryption (LLD DD-07 realised as an actual
decision, resolving what LLD Section 12 left as NOT YET DETERMINED):

    random 256-bit per-paper Data Encryption Key (DEK)
            |
            v
    AES-256-GCM(DEK, random 12-byte nonce) encrypts the PDF
            |
            v
    AES-256-GCM(MASTER_KEY, random 12-byte nonce) wraps the DEK
            |
            v
    Only the WRAPPED DEK + both nonces + algorithm name are persisted.
    The raw DEK exists only in process memory for the duration of one
    encrypt/decrypt call; it is never logged, never stored, never
    returned by any API response.

The master key itself comes from QUESTION_PAPER_MASTER_KEY (base64,
must decode to exactly 32 bytes) — an environment variable, never
hard-coded (SEC-010). It is validated lazily, at first use, so that
Phase 1/2 functionality (which never touches this module) continues to
work in environments where Phase 3 has not been configured yet.
"""

from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import get_settings

_AES_KEY_LENGTH_BYTES = 32  # AES-256
_NONCE_LENGTH_BYTES = 12  # standard AES-GCM nonce size
ALGORITHM_NAME = "AES-256-GCM"


class CryptoError(Exception):
    """
    Raised for any cryptographic failure: missing/invalid master key,
    wrong key, or ciphertext/tag tampering detected during decryption.
    Never includes key material or plaintext in its message.
    """


@dataclass
class EncryptionResult:
    """
    Everything paper_service needs to persist after encrypting a paper.
    Deliberately does NOT include the raw DEK — it is not retained
    anywhere after this call returns.
    """

    ciphertext: bytes  # AES-256-GCM output (ciphertext + 16-byte tag), to be written to storage
    file_nonce_b64: str  # base64(12-byte nonce used to encrypt the file)
    wrapped_dek_b64: str  # base64(12-byte wrap-nonce + wrapped-DEK-ciphertext+tag)
    sha256_hex: str  # SHA-256 of the ORIGINAL PLAINTEXT (see module docstring)
    algorithm: str = ALGORITHM_NAME


def compute_sha256(data: bytes) -> str:
    """SHA-256 hex digest of the given bytes (FR-009)."""
    return hashlib.sha256(data).hexdigest()


def _load_master_key() -> bytes:
    """
    Load and validate QUESTION_PAPER_MASTER_KEY. Raises CryptoError
    (never a bare exception) so callers get one predictable error type.
    Validates the DECODED length, not the base64 string length — an
    incorrectly-sized key is a configuration error, not a "system
    unavailable" condition, so this is a CryptoError, not
    ServiceUnavailableException (that mapping is decided in paper_service.py).
    """
    settings = get_settings()
    raw = settings.QUESTION_PAPER_MASTER_KEY
    if not raw:
        raise CryptoError(
            "QUESTION_PAPER_MASTER_KEY is not configured. Paper encryption "
            "cannot proceed until a 32-byte base64-encoded master key is set."
        )
    try:
        key = base64.b64decode(raw, validate=True)
    except Exception as exc:  # noqa: BLE001 — deliberately broad: any decode failure is one error type
        raise CryptoError("QUESTION_PAPER_MASTER_KEY is not valid base64.") from exc

    if len(key) != _AES_KEY_LENGTH_BYTES:
        raise CryptoError(
            f"QUESTION_PAPER_MASTER_KEY must decode to exactly {_AES_KEY_LENGTH_BYTES} bytes "
            f"(got {len(key)}). Generate one with: "
            "python -c \"import secrets,base64; print(base64.b64encode(secrets.token_bytes(32)).decode())\""
        )
    return key


def _aes_gcm_encrypt(key: bytes, plaintext: bytes) -> tuple[bytes, bytes]:
    """Returns (nonce, ciphertext_with_tag). Never logs key or plaintext."""
    nonce = os.urandom(_NONCE_LENGTH_BYTES)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, None)
    return nonce, ciphertext


def _aes_gcm_decrypt(key: bytes, nonce: bytes, ciphertext: bytes) -> bytes:
    """Raises CryptoError (wrapping InvalidTag) on ANY tampering or wrong key."""
    try:
        return AESGCM(key).decrypt(nonce, ciphertext, None)
    except InvalidTag as exc:
        raise CryptoError(
            "Decryption failed authentication — the ciphertext, nonce, key, "
            "or wrapped key metadata does not match what was recorded at "
            "registration. This is treated as a tamper-detection event."
        ) from exc


def encrypt_paper(plaintext: bytes) -> EncryptionResult:
    """
    Full Phase-3 encryption pipeline for one paper (FR-008, FR-009).
    Generates a fresh random DEK for every call — DEKs are never reused
    across papers (LLD DD-07 rationale: limits blast radius of any
    single key compromise).
    """
    master_key = _load_master_key()

    dek = AESGCM.generate_key(bit_length=256)
    file_nonce, ciphertext = _aes_gcm_encrypt(dek, plaintext)
    wrap_nonce, wrapped_dek = _aes_gcm_encrypt(master_key, dek)

    sha256_hex = compute_sha256(plaintext)

    return EncryptionResult(
        ciphertext=ciphertext,
        file_nonce_b64=base64.b64encode(file_nonce).decode("ascii"),
        wrapped_dek_b64=base64.b64encode(wrap_nonce + wrapped_dek).decode("ascii"),
        sha256_hex=sha256_hex,
    )


def decrypt_paper(ciphertext: bytes, file_nonce_b64: str, wrapped_dek_b64: str) -> bytes:
    """
    Reverses encrypt_paper(). Raises CryptoError if the master key is
    misconfigured, or if EITHER the key-unwrap step OR the file-decrypt
    step fails authentication (tamper detection — see module docstring).
    The recovered DEK exists only in this function's local scope.
    """
    master_key = _load_master_key()

    try:
        combined = base64.b64decode(wrapped_dek_b64, validate=True)
        file_nonce = base64.b64decode(file_nonce_b64, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise CryptoError("Stored encryption metadata is not valid base64.") from exc

    if len(combined) <= _NONCE_LENGTH_BYTES:
        raise CryptoError("Stored wrapped-key metadata is malformed.")
    wrap_nonce, wrapped_dek = combined[:_NONCE_LENGTH_BYTES], combined[_NONCE_LENGTH_BYTES:]

    dek = _aes_gcm_decrypt(master_key, wrap_nonce, wrapped_dek)
    plaintext = _aes_gcm_decrypt(dek, file_nonce, ciphertext)
    return plaintext
