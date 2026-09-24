# Blockchain (Hyperledger Fabric)

**Status: Phase 5B COMPLETE — a real Gateway Adapter now exists and has
been verified end-to-end against the live network, using the official
`@hyperledger/fabric-gateway` client. Still NOT connected to the
FastAPI backend (that is Phase 5C).**

## What exists now

- `network/` — Phase 5A: a minimal Fabric 2.5 network (1 org, 1 peer, 1
  Raft orderer, LevelDB, 1 channel `paperchannel`).
- `chaincode/paper-ledger/` — Phase 5A: the TypeScript chaincode
  (`RegisterPaper`, `GetPaper`, `VerifyPaperHash`, `RecordAuditEvent`).
- `gateway-adapter/` — Phase 5B: a small internal HTTP service
  (Node/TypeScript, official `@hyperledger/fabric-gateway` client) that
  translates JSON requests into real chaincode transactions. Verified
  with 8/8 real-network integration tests (no mocks) — see
  `gateway-adapter/README.md` and `PROJECT_STATE.md`'s Phase 5B
  section for real transaction IDs and exact commands.

## What does NOT exist yet (Phase 5C)

The FastAPI backend's `backend/app/services/blockchain_service.py`
still only contains the Phase 1 `StubBlockchainService` — it has not
been modified since Phase 1, and does NOT call the Gateway Adapter
above yet. That connection (a `FabricBlockchainService` implementation
that calls the adapter over HTTP) is Phase 5C's scope.

## History

The interface every future Fabric client must satisfy was defined in
Phase 1 at `backend/app/services/blockchain_service.py`
(`BlockchainService` abstract class, mirroring chaincode operations
CC-01–CC-09 from LLD Sections 9–10). A Phase-1 in-memory placeholder
(`StubBlockchainService`) implemented that interface so the rest of
the system could be built and demonstrated before the real network
existed. Phase 5A built the real network and chaincode; Phase 5B built
and verified the Gateway Adapter; Phase 5C will connect FastAPI to it.


