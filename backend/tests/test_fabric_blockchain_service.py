"""
Phase 5C tests for FabricBlockchainService.

All tests use httpx.MockTransport to fake the Fabric Gateway Adapter's
HTTP responses — no live adapter process or Fabric network is required
(consistent with the rest of this test suite, which does not require a
running PostgreSQL server either; see conftest.py). This exercises
FabricBlockchainService's request-building, response-parsing, and
error-mapping logic in isolation.

These tests do NOT touch the module-level `get_blockchain_service()`
cache except in the two tests explicitly about the factory, and those
two always restore/clear the cache afterwards so they cannot leak
state into other test modules (get_blockchain_service is @lru_cache'd
at module scope for the whole pytest process).
"""

import uuid
from datetime import datetime, timezone

import httpx
import pytest

from app.exceptions.base import (
    ConflictException,
    NotFoundException,
    ServiceUnavailableException,
    UnsupportedOperationException,
    ValidationFailedException,
)
from app.services.blockchain_service import PaperMetadataRecord, StubBlockchainService
from app.services.fabric_blockchain_service import FabricBlockchainService

PAPER_ID = uuid.uuid4()
ACTOR_ID = uuid.uuid4()


def _service(handler) -> FabricBlockchainService:
    """Build a FabricBlockchainService wired to a fake transport."""
    transport = httpx.MockTransport(handler)
    return FabricBlockchainService(
        base_url="http://127.0.0.1:8081", timeout_seconds=1.0, transport=transport
    )


# ---------------------------------------------------------------------
# 1. register_paper — success
# ---------------------------------------------------------------------


def test_register_paper_success_preserves_real_transaction_id():
    seen_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        body = httpx.Response(201, json={
            "success": True,
            "transaction_id": "a1b2c3d4e5f6",
            "paper_id": str(PAPER_ID),
        })
        return body

    service = _service(handler)
    tx_id = service.register_paper(
        paper_id=PAPER_ID,
        sha256_hash="ab" * 32,
        release_timestamp=datetime.now(timezone.utc),
        metadata={"admin_id": str(ACTOR_ID), "subject": "Data Structures", "encryption_algorithm": "AES-256-GCM"},
    )

    assert tx_id == "a1b2c3d4e5f6"  # never a fabricated UUID
    assert len(seen_requests) == 1
    req = seen_requests[0]
    assert req.method == "POST"
    assert req.url.path == "/fabric/register-paper"


def test_register_paper_does_not_send_release_timestamp_to_fabric():
    """The deployed chaincode has no field for it — see module docstring."""
    import json

    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(201, json={"success": True, "transaction_id": "tx-1", "paper_id": str(PAPER_ID)})

    service = _service(handler)
    service.register_paper(
        paper_id=PAPER_ID,
        sha256_hash="ab" * 32,
        release_timestamp=datetime(2030, 1, 1, tzinfo=timezone.utc),
        metadata={"admin_id": str(ACTOR_ID), "subject": "OS", "encryption_algorithm": "AES-256-GCM"},
    )

    assert "release_timestamp" not in captured["body"]
    assert set(captured["body"].keys()) == {
        "paper_id", "sha256_hash", "registered_at", "admin_id", "subject", "encryption_algorithm",
    }


def test_register_paper_missing_metadata_raises_validation_error_without_calling_fabric():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(201, json={"success": True, "transaction_id": "tx", "paper_id": str(PAPER_ID)})

    service = _service(handler)
    with pytest.raises(ValidationFailedException) as exc_info:
        service.register_paper(
            paper_id=PAPER_ID,
            sha256_hash="ab" * 32,
            release_timestamp=datetime.now(timezone.utc),
            metadata={"admin_id": str(ACTOR_ID)},  # missing subject, encryption_algorithm
        )

    assert "subject" in str(exc_info.value)
    assert "encryption_algorithm" in str(exc_info.value)
    assert calls == []  # no request was ever sent


# ---------------------------------------------------------------------
# 2. get_paper_metadata — success / not found
# ---------------------------------------------------------------------


def test_get_paper_metadata_success_maps_honestly():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/fabric/paper/{PAPER_ID}"
        return httpx.Response(200, json={
            "docType": "paper",
            "paperId": str(PAPER_ID),
            "sha256Hash": "cd" * 32,
            "registeredAt": "2026-01-01T00:00:00+00:00",
            "adminId": str(ACTOR_ID),
            "subject": "Networks",
            "encryptionAlgorithm": "AES-256-GCM",
        })

    service = _service(handler)
    record = service.get_paper_metadata(PAPER_ID)

    assert isinstance(record, PaperMetadataRecord)
    assert record.sha256_hash == "cd" * 32
    # These two are honestly absent from the chaincode's PaperRecord —
    # see PaperMetadataRecord's docstring for why None/[] here is
    # correct, not a bug.
    assert record.release_timestamp is None
    assert record.authorized_centre_references == []
    assert record.status == "registered"


def test_get_paper_metadata_not_found_returns_none():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": {"message": "PAPER_NOT_FOUND: no such paper.", "type": "NOT_FOUND"}})

    service = _service(handler)
    assert service.get_paper_metadata(PAPER_ID) is None


# ---------------------------------------------------------------------
# 3. verify_paper_hash — success (both outcomes)
# ---------------------------------------------------------------------


@pytest.mark.parametrize("match", [True, False])
def test_verify_paper_hash_success(match):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"paper_id": str(PAPER_ID), "match": match})

    service = _service(handler)
    result = service.verify_paper_hash(PAPER_ID, "ef" * 32)

    assert result is match


def test_verify_paper_hash_unsupported_on_stub_backend():
    """
    StubBlockchainService does not override verify_paper_hash, so the
    BlockchainService base implementation applies: an explicit,
    honest "not supported" — never a fabricated True/False.
    """
    stub = StubBlockchainService()
    with pytest.raises(UnsupportedOperationException):
        stub.verify_paper_hash(PAPER_ID, "ef" * 32)


# ---------------------------------------------------------------------
# 4. record_audit_event — success
# ---------------------------------------------------------------------


def test_record_audit_event_success_generates_event_id_and_preserves_tx_id():
    import json

    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(201, json={
            "success": True,
            "transaction_id": "audit-tx-99",
            "event_id": captured["body"]["event_id"],
        })

    service = _service(handler)
    tx_id = service.record_audit_event(
        event_type="PAPER_REGISTERED", actor_id=ACTOR_ID, paper_id=PAPER_ID, outcome="SUCCESS"
    )

    assert tx_id == "audit-tx-99"
    # event_id is generated by FabricBlockchainService itself (see module
    # docstring) — confirm it's a well-formed UUID, not left blank.
    assert uuid.UUID(captured["body"]["event_id"])


def test_record_audit_event_allows_none_actor_and_paper():
    """System-level events may have no actor/paper — chaincode accepts empty strings."""
    import json
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(201, json={"success": True, "transaction_id": "tx", "event_id": "e"})

    service = _service(handler)
    service.record_audit_event(event_type="SYSTEM_STARTUP", actor_id=None, paper_id=None, outcome="SUCCESS")

    assert captured["body"]["actor_id"] == ""
    assert captured["body"]["paper_id"] == ""


# ---------------------------------------------------------------------
# 5. Adapter error propagation (gateway error -> app exception mapping)
# ---------------------------------------------------------------------


def test_gateway_404_maps_to_not_found_exception():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": {"message": "PAPER_NOT_FOUND: x", "type": "NOT_FOUND"}})

    service = _service(handler)
    with pytest.raises(NotFoundException):
        service.verify_paper_hash(PAPER_ID, "ab" * 32)


def test_gateway_409_maps_to_conflict_exception():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"error": {"message": "DUPLICATE_PAPER: already exists.", "type": "DUPLICATE"}})

    service = _service(handler)
    with pytest.raises(ConflictException):
        service.register_paper(
            paper_id=PAPER_ID,
            sha256_hash="ab" * 32,
            release_timestamp=datetime.now(timezone.utc),
            metadata={"admin_id": str(ACTOR_ID), "subject": "x", "encryption_algorithm": "AES-256-GCM"},
        )


def test_gateway_400_maps_to_validation_failed_exception():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "VALIDATION_ERROR: bad hash.", "type": "VALIDATION_ERROR"}})

    service = _service(handler)
    with pytest.raises(ValidationFailedException):
        service.verify_paper_hash(PAPER_ID, "not-a-hash")


@pytest.mark.parametrize("status", [500, 502, 503])
def test_gateway_5xx_maps_to_service_unavailable(status):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": "Fabric is down.", "type": "FABRIC_UNAVAILABLE"}})

    service = _service(handler)
    with pytest.raises(ServiceUnavailableException):
        service.verify_paper_hash(PAPER_ID, "ab" * 32)


# ---------------------------------------------------------------------
# 6. Timeout handling
# ---------------------------------------------------------------------


def test_gateway_timeout_maps_to_service_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    service = _service(handler)
    with pytest.raises(ServiceUnavailableException):
        service.verify_paper_hash(PAPER_ID, "ab" * 32)


def test_gateway_connection_error_maps_to_service_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    service = _service(handler)
    with pytest.raises(ServiceUnavailableException):
        service.verify_paper_hash(PAPER_ID, "ab" * 32)


# ---------------------------------------------------------------------
# 7. Invalid response handling
# ---------------------------------------------------------------------


def test_non_json_success_response_maps_to_service_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json")

    service = _service(handler)
    with pytest.raises(ServiceUnavailableException):
        service.verify_paper_hash(PAPER_ID, "ab" * 32)


# ---------------------------------------------------------------------
# 8. Unsupported operations — explicit, never a silent Stub fallback
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "call",
    [
        lambda s: s.authorize_centre(PAPER_ID, uuid.uuid4()),
        lambda s: s.revoke_centre(PAPER_ID, uuid.uuid4()),
        lambda s: s.record_access_attempt(PAPER_ID, uuid.uuid4(), "DENIED", "unauthorized"),
        lambda s: s.record_integrity_result(PAPER_ID, "MATCH"),
        lambda s: s.record_release(PAPER_ID, uuid.uuid4()),
        lambda s: s.record_exam_violation(uuid.uuid4(), PAPER_ID, uuid.uuid4(), "TAB_SWITCH", "WARNED"),
    ],
)
def test_unsupported_operations_raise_explicit_error_and_never_call_fabric(call):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)  # should never be reached
        return httpx.Response(200, json={})

    service = _service(handler)
    with pytest.raises(UnsupportedOperationException):
        call(service)

    assert calls == []  # confirms no silent Stub-like fabricated success and no HTTP call at all


# ---------------------------------------------------------------------
# 9. Configuration / factory behaviour — no silent Stub fallback
# ---------------------------------------------------------------------


def test_factory_selects_fabric_backend_when_configured(monkeypatch):
    from app.services import blockchain_service as bs_module

    bs_module.get_blockchain_service.cache_clear()
    try:
        monkeypatch.setenv("BLOCKCHAIN_BACKEND", "fabric")
        monkeypatch.setenv("FABRIC_GATEWAY_ENDPOINT", "http://127.0.0.1:8081")
        bs_module.get_settings.cache_clear()

        service = bs_module.get_blockchain_service()
        assert isinstance(service, FabricBlockchainService)
    finally:
        bs_module.get_blockchain_service.cache_clear()
        bs_module.get_settings.cache_clear()
        monkeypatch.undo()
        bs_module.get_settings.cache_clear()
        bs_module.get_blockchain_service.cache_clear()
        # Restore the module-level singletons the rest of the suite
        # (and conftest's app fixtures) rely on being the "stub" backend.
        assert bs_module.get_settings().BLOCKCHAIN_BACKEND == "stub"
        assert isinstance(bs_module.get_blockchain_service(), StubBlockchainService)


def test_factory_requires_gateway_endpoint_for_fabric_backend(monkeypatch):
    from app.services import blockchain_service as bs_module

    bs_module.get_blockchain_service.cache_clear()
    try:
        monkeypatch.setenv("BLOCKCHAIN_BACKEND", "fabric")
        monkeypatch.setenv("FABRIC_GATEWAY_ENDPOINT", "")
        bs_module.get_settings.cache_clear()

        with pytest.raises(RuntimeError, match="FABRIC_GATEWAY_ENDPOINT"):
            bs_module.get_blockchain_service()
    finally:
        bs_module.get_blockchain_service.cache_clear()
        bs_module.get_settings.cache_clear()
        monkeypatch.undo()
        bs_module.get_settings.cache_clear()
        bs_module.get_blockchain_service.cache_clear()
        assert bs_module.get_settings().BLOCKCHAIN_BACKEND == "stub"


def test_default_backend_remains_stub_not_fabric():
    """Fabric must never become the default (Phase 5C brief, requirement 10)."""
    from app.services.blockchain_service import get_blockchain_service

    assert isinstance(get_blockchain_service(), StubBlockchainService)


# ---------------------------------------------------------------------
# 10. Transaction ID preservation (explicit, cross-cutting check)
# ---------------------------------------------------------------------


def test_transaction_ids_are_never_replaced_with_generated_uuids():
    """
    Regression guard: the returned transaction_id must be exactly what
    the adapter returned, never a locally-generated uuid4() standing in
    for it (which would misrepresent an operation as ledger-committed
    when the ID was never issued by Fabric).
    """
    adapter_tx_id = "not-a-uuid-just-what-fabric-happened-to-return-123"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"success": True, "transaction_id": adapter_tx_id, "paper_id": str(PAPER_ID)})

    service = _service(handler)
    tx_id = service.register_paper(
        paper_id=PAPER_ID,
        sha256_hash="ab" * 32,
        release_timestamp=datetime.now(timezone.utc),
        metadata={"admin_id": str(ACTOR_ID), "subject": "x", "encryption_algorithm": "AES-256-GCM"},
    )

    assert tx_id == adapter_tx_id
