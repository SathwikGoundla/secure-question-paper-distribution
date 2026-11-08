"""
Recovery-code primitives — Phase 7B (no database access here).

Format: 16 symbols from a 31-character alphabet without look-alikes
(0/O, 1/I/L), shown as XXXX-XXXX-XXXX-XXXX. That is 31**16 ~= 2**79 possibilities
generated with the `secrets` CSPRNG.

Why a plain SHA-256 (and not bcrypt/Argon2) is appropriate HERE: slow,
salted password hashes exist to make guessing LOW-entropy, human-chosen
secrets expensive. A 79-bit random code cannot be brute-forced from a leaked
hash, so extra work factors add cost and DoS surface without adding security.
The hash is bound to the user id (a leaked hash cannot be matched against, or
replayed for, another account, and there is no cross-user precomputation).
Online guessing is the real risk and is controlled separately: per-challenge
attempt limit, rate limits, generic errors and audit events.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import uuid

_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 16
_DOMAIN = b"qpaper-recovery-v1|"
_SHAPE = re.compile(rf"^[{_ALPHABET}]{{{CODE_LENGTH}}}$")


def generate_code() -> str:
    raw = "".join(secrets.choice(_ALPHABET) for _ in range(CODE_LENGTH))
    return "-".join(raw[i : i + 4] for i in range(0, CODE_LENGTH, 4))


def normalize(code: str) -> str:
    return re.sub(r"[\s-]", "", code or "").upper()


def is_well_formed(code: str) -> bool:
    """Cheap shape check so garbage never reaches the database."""
    return bool(_SHAPE.fullmatch(normalize(code)))


def hash_code(user_id: uuid.UUID, code: str) -> str:
    return hashlib.sha256(_DOMAIN + user_id.bytes + b"|" + normalize(code).encode()).hexdigest()
