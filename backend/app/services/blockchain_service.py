"""
Blockchain (Hyperledger Fabric) integration abstraction.

Per the Phase 1 instruction: do NOT attempt to implement the complete
Hyperledger Fabric network in this phase. This module instead defines
the interface every future FabricService implementation must satisfy,
mirroring the logical chaincode operations CC-01–CC-09 already specified
in LLD Sections 9-10 (and CC-09 from the Faculty-Review Addendum). This
keeps blockchain operations cleanly separated from FastAPI business
logic (HLD Section 7.6; LLD Section 5.10), so a real Fabric client can
replace StubBlockchainService later with no change to callers.

Binding constraint (SEC-001, LLD Section 11): no method here accepts or
returns the question-paper file itself — only metadata, hashes,
timestamps, status, and audit information ever cross this interface.
"""

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from app.config import get_settings


@dataclass
class PaperMetadataRecord:
    """Mirrors the on-chain world-state fields defined in LLD Section 11."""
    paper_id: uuid.UUID
    sha256_hash: str
    release_timestamp: datetime
    status: str
    authorized_centre_references: list[uuid.UUID] = field(default_factory=list)
    creation_timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class BlockchainService(ABC):
    """
    Interface for the permissioned-ledger operations required by the
    approved architecture. Method names/signatures map 1:1 to LLD
    Section 10 chaincode functions CC-01–CC-09.
    """

    @abstractmethod
    def register_paper(
        self, paper_id: uuid.UUID, sha256_hash: str, release_timestamp: datetime, metadata: dict[str, Any]
    ) -> str:
        """CC-01 RegisterPaper. Returns a transaction reference."""
        raise NotImplementedError

    @abstractmethod
    def authorize_centre(self, paper_id: uuid.UUID, centre_id: uuid.UUID) -> str:
        """CC-02 AuthorizeCentre. Returns a transaction reference."""
        raise NotImplementedError

    @abstractmethod
    def revoke_centre(self, paper_id: uuid.UUID, centre_id: uuid.UUID) -> str:
        """CC-03 RevokeCentre. Returns a transaction reference."""
        raise NotImplementedError

    @abstractmethod
    def get_paper_metadata(self, paper_id: uuid.UUID) -> PaperMetadataRecord | None:
        """CC-04 GetPaperMetadata. Read-only; returns None if unknown."""
        raise NotImplementedError

    @abstractmethod
    def record_access_attempt(
        self, paper_id: uuid.UUID, centre_id: uuid.UUID, outcome: str, reason: str
    ) -> str:
        """CC-05 RecordAccessAttempt. Returns a transaction reference."""
        raise NotImplementedError

    @abstractmethod
    def record_integrity_result(self, paper_id: uuid.UUID, result: str) -> str:
        """CC-06 RecordIntegrityResult ('match' | 'mismatch'). Returns a transaction reference."""
        raise NotImplementedError

    @abstractmethod
    def record_release(self, paper_id: uuid.UUID, centre_id: uuid.UUID) -> str:
        """CC-07 RecordRelease. Returns a transaction reference."""
        raise NotImplementedError

    @abstractmethod
    def record_audit_event(
        self, event_type: str, actor_id: uuid.UUID | None, paper_id: uuid.UUID | None, outcome: str
    ) -> str:
        """CC-08 RecordAuditEvent. Returns a transaction reference."""
        raise NotImplementedError

    @abstractmethod
    def record_exam_violation(
        self,
        exam_session_id: uuid.UUID,
        paper_id: uuid.UUID,
        centre_id: uuid.UUID,
        event_type: str,
        action_taken: str,
    ) -> str:
        """CC-09 RecordExamViolation (Faculty-Review Addition). Returns a transaction reference."""
        raise NotImplementedError


class StubBlockchainService(BlockchainService):
    """
    Phase-1 placeholder implementation using an in-process dictionary
    instead of a real Hyperledger Fabric network. This lets every other
    layer (papers, retrieval, exam-session violation handling) be built
    and demonstrated now, without requiring a running Fabric network in
    this environment.

    This is explicitly NOT the approved Hyperledger Fabric integration —
    it provides zero immutability/tamper-evidence guarantees (SEC-008 is
    NOT satisfied by this stub). It exists only to keep the interface
    boundary real and testable. Replacing it with an actual Fabric
    gateway client is planned for the Blockchain Development phase
    (Phase 9 in the project's overall lifecycle).
    """

    def __init__(self) -> None:
        self._ledger: dict[uuid.UUID, PaperMetadataRecord] = {}
        self._tx_counter = 0

    def _next_tx_ref(self) -> str:
        self._tx_counter += 1
        return f"stub-tx-{self._tx_counter:06d}"

    def register_paper(
        self, paper_id: uuid.UUID, sha256_hash: str, release_timestamp: datetime, metadata: dict[str, Any]
    ) -> str:
        if paper_id in self._ledger:
            raise ValueError(f"paper_id {paper_id} already registered on the stub ledger.")
        self._ledger[paper_id] = PaperMetadataRecord(
            paper_id=paper_id,
            sha256_hash=sha256_hash,
            release_timestamp=release_timestamp,
            status="registered",
        )
        return self._next_tx_ref()

    def authorize_centre(self, paper_id: uuid.UUID, centre_id: uuid.UUID) -> str:
        record = self._require_record(paper_id)
        if centre_id not in record.authorized_centre_references:
            record.authorized_centre_references.append(centre_id)
        return self._next_tx_ref()

    def revoke_centre(self, paper_id: uuid.UUID, centre_id: uuid.UUID) -> str:
        record = self._require_record(paper_id)
        if centre_id in record.authorized_centre_references:
            record.authorized_centre_references.remove(centre_id)
        return self._next_tx_ref()

    def get_paper_metadata(self, paper_id: uuid.UUID) -> PaperMetadataRecord | None:
        return self._ledger.get(paper_id)

    def record_access_attempt(
        self, paper_id: uuid.UUID, centre_id: uuid.UUID, outcome: str, reason: str
    ) -> str:
        self._require_record(paper_id)
        return self._next_tx_ref()

    def record_integrity_result(self, paper_id: uuid.UUID, result: str) -> str:
        self._require_record(paper_id)
        return self._next_tx_ref()

    def record_release(self, paper_id: uuid.UUID, centre_id: uuid.UUID) -> str:
        record = self._require_record(paper_id)
        record.status = "released"
        return self._next_tx_ref()

    def record_audit_event(
        self, event_type: str, actor_id: uuid.UUID | None, paper_id: uuid.UUID | None, outcome: str
    ) -> str:
        return self._next_tx_ref()

    def record_exam_violation(
        self,
        exam_session_id: uuid.UUID,
        paper_id: uuid.UUID,
        centre_id: uuid.UUID,
        event_type: str,
        action_taken: str,
    ) -> str:
        self._require_record(paper_id)
        return self._next_tx_ref()

    def _require_record(self, paper_id: uuid.UUID) -> PaperMetadataRecord:
        record = self._ledger.get(paper_id)
        if record is None:
            raise ValueError(f"Unknown paper_id on the stub ledger: {paper_id}")
        return record


@lru_cache
def get_blockchain_service() -> BlockchainService:
    """
    FastAPI-dependency-friendly factory. BLOCKCHAIN_BACKEND selects the
    implementation; only "stub" exists in Phase 1. A real
    "fabric" backend is added in the Blockchain Development phase.

    Cached (singleton) so StubBlockchainService's in-memory ledger
    persists across requests within one running process — it still does
    NOT persist across a process restart, which is expected and
    acceptable for a Phase-1 placeholder, not a real ledger.
    """
    settings = get_settings()
    if settings.BLOCKCHAIN_BACKEND == "stub":
        return StubBlockchainService()
    raise NotImplementedError(
        f"Blockchain backend '{settings.BLOCKCHAIN_BACKEND}' is not implemented yet. "
        "Only 'stub' (Phase 1 placeholder) is available."
    )
