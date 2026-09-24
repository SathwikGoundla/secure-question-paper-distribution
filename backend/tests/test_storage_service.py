"""
Unit tests for app/services/storage_service.py (Phase 3 hardening).

Covers test requirement 14 (path traversal cannot occur) plus general
correctness of the save/retrieve/delete cycle used by paper_service.py.
Uses its own isolated temp directory per test — independent of the
conftest.py STORAGE_LOCAL_PATH used by the API integration tests.
"""

import shutil
import tempfile

import pytest

from app.services.storage_service import LocalFileSystemStorageService, StorageError


@pytest.fixture()
def storage():
    tmp_dir = tempfile.mkdtemp(prefix="qpaper_storage_unit_test_")
    yield LocalFileSystemStorageService(base_path=tmp_dir)
    shutil.rmtree(tmp_dir, ignore_errors=True)


def test_save_and_retrieve_roundtrip(storage):
    payload = b"\x00\x01ciphertext-looking-bytes\xff\xfe"
    reference = storage.save_encrypted_file(payload)

    assert reference.endswith(".enc")
    assert storage.retrieve_encrypted_file(reference) == payload


def test_retrieve_nonexistent_reference_returns_none(storage):
    assert storage.retrieve_encrypted_file("does-not-exist.enc") is None


def test_each_save_gets_a_unique_reference(storage):
    ref1 = storage.save_encrypted_file(b"same content")
    ref2 = storage.save_encrypted_file(b"same content")
    assert ref1 != ref2  # server-generated uuid4 names, never derived from content or filename


def test_delete_removes_file(storage):
    reference = storage.save_encrypted_file(b"to be deleted")
    storage.delete_encrypted_file(reference)
    assert storage.retrieve_encrypted_file(reference) is None


def test_delete_nonexistent_reference_does_not_raise(storage):
    storage.delete_encrypted_file("never-existed.enc")  # must not raise


# --- Path traversal (test requirement 14) ---
# NOTE: a Windows-style "..\\..\\windows\\system32\\..." string is
# deliberately NOT included here — on this POSIX deployment target,
# backslash is not a path separator, so such a string is (correctly)
# treated as one harmless literal filename, not a traversal attempt.
# Testing it would assert a false vulnerability that does not exist on
# this platform.
@pytest.mark.parametrize(
    "malicious_reference",
    [
        "../../../../etc/passwd",
        "../outside_storage_dir.enc",
        "subdir/../../escape.enc",
    ],
)
def test_path_traversal_is_rejected_on_retrieve(storage, malicious_reference):
    with pytest.raises(StorageError):
        storage.retrieve_encrypted_file(malicious_reference)


def test_path_traversal_is_rejected_on_delete(storage):
    with pytest.raises(StorageError):
        storage.delete_encrypted_file("../../../../etc/passwd")


def test_legitimate_file_is_not_accidentally_blocked_by_traversal_guard(storage):
    """Sanity check: the traversal guard must not be so strict that it
    also rejects ordinary, well-formed references."""
    reference = storage.save_encrypted_file(b"perfectly normal file")
    assert storage.retrieve_encrypted_file(reference) == b"perfectly normal file"
