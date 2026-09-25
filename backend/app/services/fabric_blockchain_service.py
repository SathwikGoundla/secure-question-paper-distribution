"""
Phase 5C: real Hyperledger Fabric integration for the FastAPI backend.

FastAPI backend
      |
      v
BlockchainService abstraction (blockchain_service.py)
      |
      v
FabricBlockchainService (this file)
      |  HTTP, localhost only
      v
Fabric Gateway Adapter (Phase 5B, blockchain/gateway-adapter/)
      |
      v
Hyperledger Fabric -> paper-ledger chaincode (Phase 5A)

This module does NOT talk to Hyperledger Fabric directly, does NOT hold
any Fabric identity/wallet/certificate material, and does NOT implement
a second Gateway client. It is a thin HTTP client for the existing
Phase 5B adapter's internal API (blockchain/gateway-adapter/src/server.ts),
exactly mirroring the request/response shapes defined in that adapter's
types.ts. All Fabric credentials, connection profiles, and private key
material stay entirely inside the Node.js adapter process — this class
never sees them (SEC-010, LLD Section 25).

--------------------------------------------------------------------
Supported vs. unsupported BlockchainService operations (Phase 5C)
--------------------------------------------------------------------

The BlockchainService ABC (blockchain_service.py) defines 9 methods,
named to mirror LLD Section 10's CC-01..CC-09 chaincode functions.
The chaincode actually deployed in Phase 5A/5B
(blockchain/chaincode/paper-ledger/src/paperContract.ts) implements
only 4 transactions in total, and — this is the important, easily
mis-stated part — only 3 of those 4 have a same-purpose counterpart
among the 9 ABC methods:

    Deployed chaincode function   ABC method              Status
    ----------------------------  -----------------------  ------------
    RegisterPaper                 register_paper            SUPPORTED
    GetPaper                      get_paper_metadata         SUPPORTED (partial — see below)
    RecordAuditEvent              record_audit_event         SUPPORTED
    VerifyPaperHash               (none — see below)         SUPPORTED, via a
                                                               new non-ABC method

    (no chaincode fn)             authorize_centre           UNSUPPORTED
    (no chaincode fn)             revoke_centre               UNSUPPORTED
    (no chaincode fn)             record_access_attempt      UNSUPPORTED
    (no chaincode fn)             record_integrity_result    UNSUPPORTED
    (no chaincode fn)             record_release              UNSUPPORTED
    (no chaincode fn)             record_exam_violation      UNSUPPORTED

That is 6 unsupported ABC methods, not 5. (An earlier task brief for
this phase assumed 9 methods - 4 supported = 5 unsupported, treating
VerifyPaperHash as if it filled one of the 9 ABC method slots. It does
not: VerifyPaperHash is a real, read-only chaincode query with no
CC-0x counterpart in the original numbering, and `record_integrity_result`
/CC-06 — the closest-named ABC method — is specified as a *write* that
appends a match/mismatch record to the ledger, which this chaincode
does not implement at all. This class corrects that arithmetic rather
than silently reproducing it; see PROJECT_STATE.md Phase 5C section
for the full explanation. Per the project's own continuity protocol,
actual source code is authoritative over assumptions carried in from
an earlier prompt.)

For every unsupported ABC method, this class raises
`UnsupportedOperationException` (HTTP 501) rather than:
  - silently delegating to StubBlockchainService,
  - fabricating a transaction ID,
  - or claiming a ledger write happened when it did not.

`verify_paper_hash` is implemented as a *new*, non-abstract method on
the shared `BlockchainService` base class (see blockchain_service.py)
rather than forced onto the existing ABC contract, so this is an
additive, documented change — not a breaking one. `StubBlockchainService`
does not override it, so calling it against the stub backend also
raises `UnsupportedOperationException` (honest: the stub does not
support it either).

--------------------------------------------------------------------
Data mapping notes
--------------------------------------------------------------------

register_paper(paper_id, sha256_hash, release_timestamp, metadata):
  - The deployed chaincode's RegisterPaper has NO field for a release
    timestamp at all (see paperContract.ts / types.ts RegisterPaperRequest).
    `release_timestamp` is therefore accepted (to satisfy the shared ABC
    signature) but deliberately NOT sent to Fabric. PostgreSQL's
    `papers.release_timestamp` remains the sole authoritative source for
    time-lock enforcement (FR-012, LLD Section 16) — this was already
    true architecturally before Phase 5C and is unchanged by it.
  - `registered_at` (a field the chaincode DOES require) is not part of
    the ABC signature either; this class supplies it as
    `datetime.now(timezone.utc)` at call time.
  - `admin_id`, `subject`, and `encryption_algorithm` (also required by
    the chaincode) are read out of the free-form `metadata` dict. A
    missing/empty value raises `ValidationFailedException` naming the
    missing key(s) rather than sending an incomplete request to Fabric.

get_paper_metadata(paper_id):
  - Maps to the chaincode's GetPaper query. The returned PaperRecord
    has no release_timestamp, status, or authorized_centre_references
    fields (see paperContract.ts) — see PaperMetadataRecord's own
    docstring in blockchain_service.py for how this class fills those
    in honestly (release_timestamp=None; status="registered", the only
    state this chaincode tracks; authorized_centre_references=[],
    which is NOT an authorization source of truth — PostgreSQL's
    paper_authorizations table already is, per LLD 7.5/15, unchanged
    by Phase 5C).

record_audit_event(event_type, actor_id, paper_id, outcome):
  - The chaincode requires an `event_id` (its dedup/idempotency key).
    The ABC signature has no such parameter (PostgreSQL's audit_events
    table uses its own auto-generated primary key instead). This class
    generates a fresh `uuid.uuid4()` per call to satisfy the chaincode.
    This id is NOT shared with the PostgreSQL audit_events row, so it
    provides no cross-store correlation value beyond the returned
    transaction_id — documented as a known limitation, not silently
    glossed over.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

from app.exceptions.base import (
    ConflictException,
    NotFoundException,
    ServiceUnavailableException,
    UnsupportedOperationException,
    ValidationFailedException,
)
from app.services.blockchain_service import BlockchainService, PaperMetadataRecord

logger = logging.getLogger(__name__)

_REQUIRED_REGISTER_METADATA_FIELDS = ("admin_id", "subject", "encryption_algorithm")


class FabricBlockchainService(BlockchainService):
    """
    HTTP client for the Phase 5B Fabric Gateway Adapter. See this
    module's docstring for the full supported/unsupported operation
    mapping and data-mapping notes.
    """

    #: Phase 5E: the only concrete BlockchainService that actually
    #: implements verify_paper_hash() against a real chaincode query —
    #: see blockchain_service.py's docstring for how callers use this.
    supports_ledger_verification: bool = True

    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 5.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        """
        `transport` is a test-only seam (default None -> httpx's real
        network transport). Unit tests pass an `httpx.MockTransport` so
        they can exercise this class's request-building and
        error-mapping logic without a live Fabric Gateway Adapter
        process — see tests/test_fabric_blockchain_service.py.
        """
        if not base_url:
            raise ValueError("FabricBlockchainService requires a non-empty base_url.")
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        # One client reused for the process lifetime — get_blockchain_service()
        # is @lru_cache'd, so this constructor runs once per process
        # (per selected backend), not once per request.
        self._client = httpx.Client(
            base_url=self._base_url, timeout=self._timeout_seconds, transport=transport
        )

    def close(self) -> None:
        """Release the underlying HTTP connection pool. Not called automatically;
        provided for callers (e.g. tests, graceful shutdown hooks) that need it."""
        self._client.close()

    # ------------------------------------------------------------------
    # Supported operations
    # ------------------------------------------------------------------

    def register_paper(
        self, paper_id: uuid.UUID, sha256_hash: str, release_timestamp: datetime, metadata: dict[str, Any]
    ) -> str:
        missing = [f for f in _REQUIRED_REGISTER_METADATA_FIELDS if not metadata.get(f)]
        if missing:
            raise ValidationFailedException(
                "FabricBlockchainService.register_paper: metadata is missing required "
                f"field(s) needed by the deployed chaincode's RegisterPaper transaction: "
                f"{', '.join(missing)}."
            )
        # release_timestamp is intentionally NOT included in the payload —
        # see this module's docstring ("Data mapping notes").
        payload = {
            "paper_id": str(paper_id),
            "sha256_hash": sha256_hash,
            "registered_at": datetime.now(timezone.utc).isoformat(),
            "admin_id": str(metadata["admin_id"]),
            "subject": str(metadata["subject"]),
            "encryption_algorithm": str(metadata["encryption_algorithm"]),
        }
        response = self._post("/fabric/register-paper", payload)
        return response["transaction_id"]

    def get_paper_metadata(self, paper_id: uuid.UUID) -> PaperMetadataRecord | None:
        try:
            record = self._get(f"/fabric/paper/{paper_id}")
        except NotFoundException:
            return None
        return PaperMetadataRecord(
            paper_id=paper_id,
            sha256_hash=record["sha256Hash"],
            # See PaperMetadataRecord's docstring (blockchain_service.py)
            # for why these two are always None / [] for Fabric-backed
            # records, and why that is not a data-loss bug.
            release_timestamp=None,
            status="registered",
            authorized_centre_references=[],
        )

    def record_audit_event(
        self, event_type: str, actor_id: uuid.UUID | None, paper_id: uuid.UUID | None, outcome: str
    ) -> str:
        payload = {
            # See this module's docstring ("Data mapping notes") — a
            # fresh id per call, not shared with the PostgreSQL row.
            "event_id": str(uuid.uuid4()),
            "event_type": event_type,
            "actor_id": str(actor_id) if actor_id is not None else "",
            "paper_id": str(paper_id) if paper_id is not None else "",
            "outcome": outcome,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        response = self._post("/fabric/audit-event", payload)
        return response["transaction_id"]

    def verify_paper_hash(self, paper_id: uuid.UUID, candidate_hash: str) -> bool:
        """Overrides BlockchainService's default (which raises
        UnsupportedOperationException) with a real call to the
        chaincode's read-only VerifyPaperHash transaction."""
        response = self._post(
            "/fabric/verify-hash", {"paper_id": str(paper_id), "candidate_hash": candidate_hash}
        )
        return bool(response["match"])

    # ------------------------------------------------------------------
    # Unsupported operations — see module docstring for why.
    # ------------------------------------------------------------------

    def authorize_centre(self, paper_id: uuid.UUID, centre_id: uuid.UUID) -> str:
        raise self._unsupported("authorize_centre", "AuthorizeCentre")

    def revoke_centre(self, paper_id: uuid.UUID, centre_id: uuid.UUID) -> str:
        raise self._unsupported("revoke_centre", "RevokeCentre")

    def record_access_attempt(
        self, paper_id: uuid.UUID, centre_id: uuid.UUID, outcome: str, reason: str
    ) -> str:
        raise self._unsupported("record_access_attempt", "RecordAccessAttempt")

    def record_integrity_result(self, paper_id: uuid.UUID, result: str) -> str:
        raise self._unsupported("record_integrity_result", "RecordIntegrityResult")

    def record_release(self, paper_id: uuid.UUID, centre_id: uuid.UUID) -> str:
        raise self._unsupported("record_release", "RecordRelease")

    def record_exam_violation(
        self,
        exam_session_id: uuid.UUID,
        paper_id: uuid.UUID,
        centre_id: uuid.UUID,
        event_type: str,
        action_taken: str,
    ) -> str:
        raise self._unsupported("record_exam_violation", "RecordExamViolation")

    @staticmethod
    def _unsupported(method_name: str, chaincode_fn_name: str) -> UnsupportedOperationException:
        return UnsupportedOperationException(
            f"FabricBlockchainService.{method_name}() has no corresponding transaction "
            f"in the deployed paper-ledger chaincode ({chaincode_fn_name} does not exist "
            "there as of Phase 5C). This is not implemented: it is not silently routed to "
            "the stub backend, and no transaction was submitted to Fabric."
        )

    # ------------------------------------------------------------------
    # HTTP transport
    # ------------------------------------------------------------------

    def _post(self, path: str, json_body: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self._client.post(path, json=json_body)
        except httpx.TimeoutException as exc:
            raise ServiceUnavailableException(
                f"Fabric Gateway Adapter did not respond within {self._timeout_seconds}s "
                f"(POST {path})."
            ) from exc
        except httpx.ConnectError as exc:
            raise ServiceUnavailableException(
                f"Could not reach the Fabric Gateway Adapter at {self._base_url} (POST {path}). "
                "Is the adapter process running?"
            ) from exc
        except httpx.HTTPError as exc:
            raise ServiceUnavailableException(
                f"Fabric Gateway Adapter request failed (POST {path}): {exc}"
            ) from exc
        return self._parse_response(response, path)

    def _get(self, path: str) -> dict[str, Any]:
        try:
            response = self._client.get(path)
        except httpx.TimeoutException as exc:
            raise ServiceUnavailableException(
                f"Fabric Gateway Adapter did not respond within {self._timeout_seconds}s (GET {path})."
            ) from exc
        except httpx.ConnectError as exc:
            raise ServiceUnavailableException(
                f"Could not reach the Fabric Gateway Adapter at {self._base_url} (GET {path}). "
                "Is the adapter process running?"
            ) from exc
        except httpx.HTTPError as exc:
            raise ServiceUnavailableException(
                f"Fabric Gateway Adapter request failed (GET {path}): {exc}"
            ) from exc
        return self._parse_response(response, path)

    def _parse_response(self, response: httpx.Response, path: str) -> dict[str, Any]:
        if response.status_code < 300:
            try:
                return response.json()
            except ValueError as exc:
                raise ServiceUnavailableException(
                    f"Fabric Gateway Adapter returned a non-JSON success response ({path})."
                ) from exc

        try:
            body = response.json()
            message = body.get("error", {}).get("message", response.text)
        except ValueError:
            message = response.text or f"HTTP {response.status_code}"

        logger.warning("Fabric Gateway Adapter error on %s: %s %s", path, response.status_code, message)

        if response.status_code == 404:
            raise NotFoundException(message)
        if response.status_code == 409:
            raise ConflictException(message)
        if response.status_code == 400:
            raise ValidationFailedException(message)
        # 501/502/503/500 and anything else unexpected: treat as a
        # dependency-availability problem rather than guessing further —
        # matches ServiceUnavailableException's documented purpose
        # (blockchain_service.py / app/exceptions/base.py).
        raise ServiceUnavailableException(
            f"Fabric Gateway Adapter returned an unexpected error (HTTP {response.status_code}): {message}"
        )
