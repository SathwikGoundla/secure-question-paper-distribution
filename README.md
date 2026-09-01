# Blockchain-Enabled Secure Question Paper Distribution and Controlled Examination Access Framework

B.Tech CSE Major Project. This repository holds the implementation, tracked against the
approved documentation:

- `PRD v2.1` — Product Requirements Document (Faculty-Review Update)
- `SRS v1.1` — Software Requirements Specification (Faculty-Review Update)
- `HLD v1.1` — High-Level Design (Faculty-Review Update)
- `LLD v1.1` — Low-Level Design (Faculty-Review Update)

These four documents are the **primary source of truth** for every design decision in this
codebase. This code does not redefine, contradict, or silently extend them.

## Current Implementation Status

**Phase 1 — Implementation Foundation: COMPLETE**
**All later phases: NOT YET STARTED**

See `docs/PHASE1_IMPLEMENTATION_STATUS.md` for full detail.

## Repository Layout

```
frontend/     React.js UI (Admin console, Examination-Centre portal). Not yet started.
backend/      FastAPI application — the only component with real code so far.
blockchain/   Hyperledger Fabric network/chaincode. Not yet started; see blockchain/README.md.
storage/      Off-chain encrypted-file storage. Dev-only local implementation lives
              inside backend/app/services/storage_service.py for now; this folder is
              reserved for real deployment-time storage configuration later.
docs/         Implementation-phase documentation (not the PRD/SRS/HLD/LLD themselves).
```

## Where to Start

See `backend/README.md` for how to set up and run what exists today.
