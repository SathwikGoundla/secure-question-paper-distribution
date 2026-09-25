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
from app.exceptions.base import UnsupportedOperationException


@dataclass
class PaperMetadataRecord:
    """
    Mirrors the on-chain world-state fields defined in LLD Section 11.

    Phase 5C note: `release_timestamp` is typed `datetime | None` (not
    `datetime`) because the actually-deployed Phase 5A/5B chaincode
    (blockchain/chaincode/paper-ledger/src/paperContract.ts) does not
    store a release timestamp at all — LLD Section 11's full world-state
    model was scoped down to 4 transactions during Phase 5 readiness
    (see PROJECT_STATE.md). StubBlockchainService still always populates
    a real value (unchanged behaviour); only FabricBlockchainService
    returns None here, and always does so, since PostgreSQL's
    `papers.release_timestamp` remains the sole authoritative source
    for time-lock enforcement (FR-012) regardless of blockchain backend.
    Similarly, `authorized_centre_references` is never populated by
    FabricBlockchainService (always `[]`) — this chaincode does not
    track authorization on-chain. Callers MUST NOT treat an empty list
    from a Fabric-backed record as "no centres authorized"; PostgreSQL's
    paper_authorizations table (LLD 7.5) remains the sole authorization
    source of truth, exactly as already designed in LLD Section 15
    (Fabric was never the authorization source, even before Phase 5C).
    """
    paper_id: uuid.UUID
    sha256_hash: str
    release_timestamp: datetime | None
    status: str
    authorized_centre_references: list[uuid.UUID] = field(default_factory=list)
    creation_timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class BlockchainService(ABC):
    """
    Interface for the permissioned-ledger operations required by the
    approved architecture. Method names/signatures map 1:1 to LLD
    Section 10 chaincode functions CC-01–CC-09.
    """

    #: Phase 5E explicit capability flag. False by default (matches
    #: verify_paper_hash()'s own default UnsupportedOperationException
    #: behaviour below). Callers (paper_service.retrieve_paper()) check
    #: THIS flag before calling verify_paper_hash() at all, rather than
    #: calling-and-catching — so a backend that doesn't support ledger
    #: verification (e.g. StubBlockchainService) is never actually
    #: invoked for it, not merely "invoked and its exception is caught
    #: every single time." Only FabricBlockchainService overrides this
    #: to True.
    supports_ledger_verification: bool = False

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

    def verify_paper_hash(self, paper_id: uuid.UUID, candidate_hash: str) -> bool:
        """
        Phase 5C addition — deliberately NOT an @abstractmethod and NOT
        one of CC-01..CC-09.

        The actually-deployed chaincode (paperContract.ts) exposes a
        genuine, read-only `VerifyPaperHash` transaction that has no
        counterpart in the original LLD Section 10 CC-numbering (the
        closest-named ABC method, `record_integrity_result`/CC-06, is a
        *write* that appends a match/mismatch record to the ledger —
        a materially different, and currently chaincode-unsupported,
        operation; see FabricBlockchainService's docstring).

        This method is added as a concrete, non-abstract extension so
        Fabric's real capability is reachable through the shared
        `BlockchainService` type without forcing every other backend to
        implement it. The base implementation here raises
        `UnsupportedOperationException` — i.e. by default (including for
        `StubBlockchainService`, which does not override this) calling
        it is an explicit, typed "not supported by this backend"
        condition, never a fabricated True/False result.
        """
        raise UnsupportedOperationException(
            f"{type(self).__name__}.verify_paper_hash() is not supported by this blockchain backend."
        )


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
    implementation:

      - "stub"   Phase-1 in-memory placeholder (default; used by the
                 existing test suite and local development unless
                 explicitly overridden).
      - "fabric" Phase 5C real integration — talks to the Phase 5B
                 Fabric Gateway Adapter over HTTP. Requires
                 FABRIC_GATEWAY_ENDPOINT to be set.

    The default stays "stub" so existing local/unit-test environments
    are unaffected unless BLOCKCHAIN_BACKEND is explicitly changed —
    Fabric is opt-in, never a silent default.

    Cached (singleton) so StubBlockchainService's in-memory ledger
    persists across requests within one running process, and so
    FabricBlockchainService reuses one underlying HTTP client instead
    of opening a new connection per request. Neither persists across a
    process restart. Tests that need a different backend selection
    must call `get_blockchain_service.cache_clear()` first.
    """
    settings = get_settings()
    if settings.BLOCKCHAIN_BACKEND == "stub":
        return StubBlockchainService()
    if settings.BLOCKCHAIN_BACKEND == "fabric":
        # Imported lazily (function-local) rather than at module top so
        # that importing blockchain_service.py never requires httpx to
        # be installed unless the Fabric backend is actually selected,
        # and to avoid a circular import (fabric_blockchain_service.py
        # imports PaperMetadataRecord/UnsupportedOperationException from
        # this module).
        from app.services.fabric_blockchain_service import FabricBlockchainService

        if not settings.FABRIC_GATEWAY_ENDPOINT:
            raise RuntimeError(
                "BLOCKCHAIN_BACKEND=fabric requires FABRIC_GATEWAY_ENDPOINT to be set "
                "to the running Fabric Gateway Adapter's base URL "
                "(e.g. http://127.0.0.1:8081) — see backend/.env.example."
            )
        return FabricBlockchainService(
            base_url=settings.FABRIC_GATEWAY_ENDPOINT,
            timeout_seconds=settings.FABRIC_GATEWAY_TIMEOUT_SECONDS,
        )
    raise NotImplementedError(
        f"Blockchain backend '{settings.BLOCKCHAIN_BACKEND}' is not implemented. "
        "Available: 'stub' (Phase 1 placeholder), 'fabric' (Phase 5C)."
    )
