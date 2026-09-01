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

import uuid
from abc import ABC, abstractmethod
from pathlib import Path

from app.config import get_settings


class StorageService(ABC):
    """
    Abstraction covering exactly what LLD Section 21 requires:
    - store an encrypted file, returning a reference
    - retrieve an encrypted file by that reference
    No deletion/retention method is defined here because LLD Section 21
    explicitly marks deletion/retention policy as NOT YET DETERMINED.
    """

    @abstractmethod
    def save_encrypted_file(self, file_bytes: bytes, suggested_name: str | None = None) -> str:
        """Persist ciphertext bytes; return an opaque file_reference (LLD 7.4)."""
        raise NotImplementedError

    @abstractmethod
    def retrieve_encrypted_file(self, file_reference: str) -> bytes | None:
        """Return ciphertext bytes for a reference, or None if not found."""
        raise NotImplementedError


class LocalFileSystemStorageService(StorageService):
    """
    Development/demo-only implementation. Stores encrypted files under
    STORAGE_LOCAL_PATH on the local disk. This is explicitly NOT the
    approved production storage decision (LLD DD-13 remains open) —
    it exists purely so paper registration/retrieval can be built and
    demonstrated in this environment.
    """

    def __init__(self, base_path: str | None = None) -> None:
        settings = get_settings()
        self._base_path = Path(base_path or settings.STORAGE_LOCAL_PATH)
        self._base_path.mkdir(parents=True, exist_ok=True)

    def save_encrypted_file(self, file_bytes: bytes, suggested_name: str | None = None) -> str:
        file_reference = f"{uuid.uuid4()}.enc"
        target_path = self._base_path / file_reference
        target_path.write_bytes(file_bytes)
        return file_reference

    def retrieve_encrypted_file(self, file_reference: str) -> bytes | None:
        target_path = self._base_path / file_reference
        if not target_path.exists():
            return None
        return target_path.read_bytes()


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
