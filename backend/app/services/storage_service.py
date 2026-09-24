"""
Secure off-chain storage abstraction (LLD Section 4.7, 5.9, 21).

Only the FastAPI backend ever touches this layer — never the frontend
or an examination centre directly (HLD Section 7.8). This module never
handles plaintext question papers as the final artifact: whatever bytes
are passed to save() are expected to already be AES-256 ciphertext,
produced by EncryptionService in a later phase.

The exact production storage provider is NOT YET DETERMINED
(LLD DD-13, SRS Section 10) — that decision is intentionally deferred.
LocalFileSystemStorageService below is a development/demo-only
implementation so the rest of the system can be built and tested now;
swapping in a real provider later only requires a new class implementing
StorageService, with no change to calling code.
"""

import os
import uuid
from abc import ABC, abstractmethod
from pathlib import Path

from app.config import get_settings


class StorageError(Exception):
    """Raised for storage-layer failures (e.g. a resolved path escaping
    the configured storage root). Never includes file contents."""


class StorageService(ABC):
    """
    Abstraction covering what LLD Section 21 requires (store/retrieve),
    plus a minimal delete() added in Phase 3. LLD Section 21 marks
    RETENTION POLICY (how long files are kept, cleanup schedules) as
    NOT YET DETERMINED — that remains true. delete() is added here only
    as an internal safety primitive so paper_service.py can clean up an
    orphaned encrypted file if database persistence fails after a
    successful write (see paper_service.py); it is not itself a
    retention-policy decision.
    """

    @abstractmethod
    def save_encrypted_file(self, file_bytes: bytes, suggested_name: str | None = None) -> str:
        """Persist ciphertext bytes; return an opaque file_reference (LLD 7.4)."""
        raise NotImplementedError

    @abstractmethod
    def retrieve_encrypted_file(self, file_reference: str) -> bytes | None:
        """Return ciphertext bytes for a reference, or None if not found."""
        raise NotImplementedError

    @abstractmethod
    def delete_encrypted_file(self, file_reference: str) -> None:
        """Best-effort delete; must not raise if the file is already absent."""
        raise NotImplementedError


class LocalFileSystemStorageService(StorageService):
    """
    Development/demo-only implementation. Stores encrypted files under
    STORAGE_LOCAL_PATH on the local disk. This is explicitly NOT the
    approved production storage decision (LLD DD-13 remains open) —
    it exists purely so paper registration/retrieval can be built and
    demonstrated in this environment.

    Phase 3 hardening (previously a simple write_bytes/read_bytes pair):
      - file_reference is ALWAYS server-generated (uuid4 + ".enc"),
        never derived from user input (e.g. the uploaded filename),
        which is the primary path-traversal defense.
      - _resolve() adds a second, defense-in-depth check: even if a
        caller ever passed an unexpected file_reference, the resolved
        absolute path is verified to still be inside the storage root
        before any read/write/delete touches disk.
      - Writes are atomic: content is written to a temp file in the
        same directory, fsync'd, then moved into place with os.replace
        (atomic on POSIX and Windows), so a crash mid-write can never
        leave a partially-written .enc file at the final path.
    """

    def __init__(self, base_path: str | None = None) -> None:
        settings = get_settings()
        self._base_path = Path(base_path or settings.STORAGE_LOCAL_PATH).resolve()
        self._base_path.mkdir(parents=True, exist_ok=True)

    def _resolve(self, file_reference: str) -> Path:
        candidate = (self._base_path / file_reference).resolve()
        try:
            candidate.relative_to(self._base_path)
        except ValueError:
            raise StorageError(
                "Resolved path escapes the configured storage root; refusing to proceed."
            )
        return candidate

    def save_encrypted_file(self, file_bytes: bytes, suggested_name: str | None = None) -> str:
        file_reference = f"{uuid.uuid4()}.enc"
        target_path = self._resolve(file_reference)

        tmp_path = target_path.with_suffix(target_path.suffix + f".tmp-{uuid.uuid4().hex}")
        try:
            with open(tmp_path, "wb") as f:
                f.write(file_bytes)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, target_path)  # atomic on POSIX and Windows
        finally:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)

        return file_reference

    def retrieve_encrypted_file(self, file_reference: str) -> bytes | None:
        target_path = self._resolve(file_reference)
        if not target_path.exists():
            return None
        return target_path.read_bytes()

    def delete_encrypted_file(self, file_reference: str) -> None:
        target_path = self._resolve(file_reference)
        target_path.unlink(missing_ok=True)


def get_storage_service() -> StorageService:
    """
    FastAPI-dependency-friendly factory. STORAGE_BACKEND selects the
    implementation; only "local" exists in Phase 1.
    """
    settings = get_settings()
    if settings.STORAGE_BACKEND == "local":
        return LocalFileSystemStorageService()
    raise NotImplementedError(
        f"Storage backend '{settings.STORAGE_BACKEND}' is not implemented yet. "
        "Only 'local' (development-only) is available in Phase 1."
    )
