# Blockchain (Hyperledger Fabric)

**Status: NOT YET STARTED.** This is a placeholder folder only.

Per Phase 1 instructions, the full Hyperledger Fabric network is intentionally not
implemented yet. The interface every future Fabric client must satisfy already exists
at `backend/app/services/blockchain_service.py` (`BlockchainService` abstract class,
mirroring chaincode operations CC-01–CC-09 from LLD Sections 9–10 and the
Faculty-Review Addendum). A Phase-1 in-memory placeholder (`StubBlockchainService`)
implements that interface so the rest of the system can be built and demonstrated now.

Real Fabric network topology, chaincode source, channel/peer/orderer configuration
will be added here during the Blockchain Development phase (Phase 9 of the project's
overall lifecycle), per LLD Sections 9–10.
