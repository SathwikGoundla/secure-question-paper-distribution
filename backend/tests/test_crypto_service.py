"""
Unit tests for app/services/crypto_service.py.

Covers Phase 3 test requirements 1-7:
  1. SHA-256 produces the expected digest
  2. AES-256-GCM encryption succeeds
  3. Encrypted output differs from plaintext
  4. Correct key/metadata decrypts successfully
  5. Modified ciphertext fails authentication/decryption
  6. Modified authentication metadata (wrapped key) fails
  7. Wrong key fails
"""

import base64
import hashlib
import secrets

import pytest

from app.services import crypto_service as crypto


# --- 1. SHA-256 known-answer test ---
def test_sha256_matches_hashlib_reference():
    data = b"hello world"
    assert crypto.compute_sha256(data) == hashlib.sha256(data).hexdigest()


def test_sha256_matches_published_nist_test_vectors():
    """
    Independently-published SHA-256 test vectors (not derived from this
    codebase), so this test can fail if compute_sha256 is broken even
    if hashlib itself were somehow also broken/mocked.
    """
    assert (
        crypto.compute_sha256(b"")
        == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )
    assert (
        crypto.compute_sha256(b"abc")
        == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )


# --- 2, 3, 4. Encrypt/decrypt roundtrip ---
def test_encrypt_paper_succeeds_and_output_differs_from_plaintext(monkeypatch):
    plaintext = b"%PDF-1.4 sample exam paper content for crypto test"
    result = crypto.encrypt_paper(plaintext)

    assert result.algorithm == "AES-256-GCM"
    assert result.ciphertext != plaintext  # requirement 3
    assert len(result.ciphertext) == len(plaintext) + 16  # GCM appends a 16-byte tag
    assert result.sha256_hex == hashlib.sha256(plaintext).hexdigest()


def test_decrypt_paper_with_correct_metadata_recovers_original_plaintext():
    plaintext = b"another sample plaintext payload \x00\x01\xff for roundtrip verification"
    result = crypto.encrypt_paper(plaintext)

    recovered = crypto.decrypt_paper(result.ciphertext, result.file_nonce_b64, result.wrapped_dek_b64)
    assert recovered == plaintext  # requirement 4


# --- 5. Modified ciphertext fails ---
def test_tampered_ciphertext_fails_decryption():
    plaintext = b"%PDF-1.4 integrity test content"
    result = crypto.encrypt_paper(plaintext)

    tampered = bytearray(result.ciphertext)
    tampered[0] ^= 0xFF  # flip a bit in the ciphertext body

    with pytest.raises(crypto.CryptoError):
        crypto.decrypt_paper(bytes(tampered), result.file_nonce_b64, result.wrapped_dek_b64)


def test_tampered_authentication_tag_fails_decryption():
    """The GCM tag is the LAST 16 bytes of the ciphertext blob — flipping
    a bit there specifically tests tag tampering, not body tampering."""
    plaintext = b"%PDF-1.4 tag tamper test content"
    result = crypto.encrypt_paper(plaintext)

    tampered = bytearray(result.ciphertext)
    tampered[-1] ^= 0xFF  # last byte falls within the 16-byte GCM tag

    with pytest.raises(crypto.CryptoError):
        crypto.decrypt_paper(bytes(tampered), result.file_nonce_b64, result.wrapped_dek_b64)


# --- 6. Modified wrapped-key metadata fails ---
def test_tampered_wrapped_dek_fails_decryption():
    plaintext = b"%PDF-1.4 wrapped-key tamper test"
    result = crypto.encrypt_paper(plaintext)

    combined = bytearray(base64.b64decode(result.wrapped_dek_b64))
    combined[-1] ^= 0xFF  # tamper the wrapped-DEK's own GCM tag
    tampered_wrapped_dek_b64 = base64.b64encode(bytes(combined)).decode("ascii")

    with pytest.raises(crypto.CryptoError):
        crypto.decrypt_paper(result.ciphertext, result.file_nonce_b64, tampered_wrapped_dek_b64)


def test_tampered_file_nonce_fails_decryption():
    plaintext = b"%PDF-1.4 nonce tamper test"
    result = crypto.encrypt_paper(plaintext)

    nonce_bytes = bytearray(base64.b64decode(result.file_nonce_b64))
    nonce_bytes[0] ^= 0xFF
    tampered_nonce_b64 = base64.b64encode(bytes(nonce_bytes)).decode("ascii")

    with pytest.raises(crypto.CryptoError):
        crypto.decrypt_paper(result.ciphertext, tampered_nonce_b64, result.wrapped_dek_b64)


# --- 7. Wrong master key fails ---
def test_wrong_master_key_fails_decryption(monkeypatch):
    plaintext = b"%PDF-1.4 wrong key test"
    result = crypto.encrypt_paper(plaintext)

    # Swap in a DIFFERENT valid-format master key after encryption, then
    # attempt to decrypt with it — simulates a wrong/rotated master key.
    from app.config import get_settings

    get_settings.cache_clear()
    wrong_key_b64 = base64.b64encode(secrets.token_bytes(32)).decode("ascii")
    monkeypatch.setenv("QUESTION_PAPER_MASTER_KEY", wrong_key_b64)
    get_settings.cache_clear()

    try:
        with pytest.raises(crypto.CryptoError):
            crypto.decrypt_paper(result.ciphertext, result.file_nonce_b64, result.wrapped_dek_b64)
    finally:
        get_settings.cache_clear()


def test_missing_master_key_raises_crypto_error(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("QUESTION_PAPER_MASTER_KEY", "")
    get_settings.cache_clear()
    try:
        with pytest.raises(crypto.CryptoError):
            crypto.encrypt_paper(b"%PDF-1.4 no key configured")
    finally:
        get_settings.cache_clear()


def test_invalid_length_master_key_raises_crypto_error(monkeypatch):
    from app.config import get_settings

    too_short_key_b64 = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
    monkeypatch.setenv("QUESTION_PAPER_MASTER_KEY", too_short_key_b64)
    get_settings.cache_clear()
    try:
        with pytest.raises(crypto.CryptoError):
            crypto.encrypt_paper(b"%PDF-1.4 wrong length key")
    finally:
        get_settings.cache_clear()


def test_each_paper_gets_a_fresh_random_dek_and_nonce():
    """Two encryptions of the SAME plaintext must not produce the same
    ciphertext or reuse a nonce — proves the DEK/nonce are freshly
    randomised per call, not reused across papers (LLD DD-07 rationale)."""
    plaintext = b"%PDF-1.4 identical content encrypted twice"
    r1 = crypto.encrypt_paper(plaintext)
    r2 = crypto.encrypt_paper(plaintext)

    assert r1.ciphertext != r2.ciphertext
    assert r1.file_nonce_b64 != r2.file_nonce_b64
    assert r1.wrapped_dek_b64 != r2.wrapped_dek_b64
    # But the plaintext hash is deterministic, as expected:
    assert r1.sha256_hex == r2.sha256_hex
