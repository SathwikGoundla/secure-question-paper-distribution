# Off-Chain Secure Storage

**Status: NOT YET STARTED (production provider).** This is a placeholder folder.

The off-chain storage provider is explicitly NOT YET DETERMINED per LLD DD-13 /
SRS Section 10. For Phase 1, a development-only local-filesystem implementation
lives inside `backend/app/services/storage_service.py`
(`LocalFileSystemStorageService`), behind a swappable `StorageService` interface.

Once a real production storage provider is selected, a new class implementing
`StorageService` should be added — no other code needs to change.
