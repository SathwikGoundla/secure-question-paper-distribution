# PROJECT_STATE.md

**Project:** Blockchain-Enabled Secure Question Paper Distribution Framework with Time-Locked Access and Tamper Detection
**This file is the permanent continuity record for this project.** At the start of every future task: read this file, then verify it against the actual source code (not the other way around) — if this file and the code disagree, the code is correct and this file must be updated to match.

Last updated: **Phase 5C (connect FastAPI backend to the Fabric Gateway Adapter) — implemented and tested this session.**

---

## 1. Architecture (unchanged from Phase 1/2)

```
React Frontend (not yet built)
        |
        v  HTTPS
FastAPI Backend  --------------------------------------------
   |        |            |            |            |
Auth/RBAC  PaperService  StorageService  CryptoService  AuditService
   |        |            |            |            |
PostgreSQL (users, roles, exam_centres, papers, paper_authorizations,
            audit_events, security_events, otp_codes, auth_sessions,
            exam_security_events)
        |
   BlockchainService (StubBlockchainService by default; FabricBlockchainService
   when BLOCKCHAIN_BACKEND=fabric, Phase 5C)
        |  HTTP (FabricBlockchainService only)
   Fabric Gateway Adapter (Node.js, Phase 5B, localhost:8081)
        |  gRPC
   Hyperledger Fabric  <-- real network exists (Phase 5A); only
                            record_audit_event is actually called by the
                            app today (Section 10/13) — StubBlockchainService
                            remains the default backend for local/unit tests
        |
   Local filesystem storage (./storage_data)  <-- dev-only, LLD DD-13 open
```

## 2. Technology stack (unchanged)

React.js (frontend, **not yet present in this repo**), Python FastAPI, PostgreSQL + SQLAlchemy, Hyperledger Fabric (stubbed), AES-256-GCM (`cryptography` lib), SHA-256, JWT (PyJWT), OTP (bcrypt-hashed via passlib), bcrypt password hashing.

## 3. Phase status

| Phase | Status |
|---|---|
| Phase 1 — Foundation | COMPLETE |
| Phase 2 — Authentication, RBAC | COMPLETE (28/28 historical checks; re-verified 28/28 this session against fresh real PostgreSQL, confirming the Phase 3 refactor caused zero regressions) |
| Phase 3 — Paper encryption/upload/storage/retrieval foundation | COMPLETE (see Section 5) — *note: this row was missing from a previous edit of this table; corrected here, no change to actual status* |
| **Phase 4 — Time-lock enforcement** | **COMPLETE** (see Section 6) |
| **Phase 5A — Fabric network + chaincode foundation** | **COMPLETE** (see Section 11) |
| Phase 5B — Fabric Gateway Adapter | COMPLETE (see Section 12) |
| Phase 5C — Connect FastAPI backend to the Gateway Adapter | COMPLETE (see Section 13) |
| **Phase 5D — Wire paper registration to the blockchain abstraction** | **COMPLETE** (see Section 14) |
| Phase 5E — Blockchain-backed integrity verification at retrieval | COMPLETE (see Section 15) |
| **Phase 6A — React frontend foundation (auth + routing shell only)** | **COMPLETE this session** (see Section 16) |
| Phase 6B — Admin Portal | NOT STARTED |
| Phase 7 — Evaluation / feedback modules | NOT STARTED |

## 4. Known documentation-vs-code gap (pre-existing, not introduced this session)

The code (models, `admin.py`, `exam_session.py`) references a **"Faculty-Review Addendum"** (FR-024–FR-028, table `exam_security_events`, CC-09, API-14/15, dated 23 Aug 2026, implying PRD v2.1/SRS v1.1/HLD v1.1/LLD v1.1). **This addendum does not exist in the PRD/SRS/HLD/LLD documents currently in the project's knowledge base** (which stop at v2.0/v1.0, FR-023). Not fabricated by any AI session — internally consistent across code+docs — but the source-of-truth documents need to be reconciled. Flagged, not resolved.

---

## 5. Phase 3 — what was implemented this session

### 5.1 New files

| Path | Purpose |
|---|---|
| `backend/app/services/crypto_service.py` | AES-256-GCM envelope encryption (random per-paper DEK, wrapped by `QUESTION_PAPER_MASTER_KEY`) + SHA-256. |
| `backend/app/services/paper_service.py` | Orchestrates register/get-metadata/authorize/retrieve; composes crypto+storage+authorization+audit services. |
| `backend/app/services/audit_service.py` | Shared `record_audit_event` / `record_security_event`, extracted from `auth_service.py` (LLD Section 5.11's generic AuditService, finally built). |
| `backend/app/schemas/papers.py` | Request/response schemas for the paper endpoints. |
| `backend/scripts/add_phase3_columns.py` | Idempotent raw-SQL `ALTER TABLE` helper (no Alembic in this project) for anyone who ran `init_db.py` before Phase 3. |
| `backend/tests/conftest.py` | Pytest fixtures: dual-dialect (SQLite fast path / PostgreSQL) DB engine, real-auth-flow token helpers, sample PDF constant. |
| `backend/tests/test_crypto_service.py` | 12 unit tests for crypto_service. |
| `backend/tests/test_storage_service.py` | 10 unit tests for storage_service (incl. path traversal). |
| `backend/tests/test_paper_api.py` | 19 full-stack integration tests via the real API. |

### 5.2 Modified files

| Path | What changed | Why |
|---|---|---|
| `backend/app/config.py` | Added `QUESTION_PAPER_MASTER_KEY` (default `""`, validated lazily at first use, not at startup) and `PAPER_MAX_UPLOAD_SIZE_BYTES` (default 20 MB). | Phase 3 config, SEC-010 compliant (no hard-coded key). |
| `backend/app/models/paper.py` | Added `encryption_algorithm`, `file_nonce`, `wrapped_dek` (both default `""` — see rationale below), `original_filename`, `file_size_bytes`. | Realises LLD Section 12's "NOT YET DETERMINED" key-management design as an actual, documented decision (envelope encryption). |
| `backend/app/services/storage_service.py` | Added `delete_encrypted_file`; hardened `save_encrypted_file` to atomic write (tempfile+fsync+`os.replace`); added `_resolve()` defense-in-depth path-traversal guard. | Explicit Phase 3 requirements ("prevent path traversal", "safe atomic file writing", orphan-file cleanup). |
| `backend/app/services/auth_service.py` | Removed private `_record_security_event`/`_record_audit_event`; now imports the same-behavior functions from the new `audit_service.py`. | De-duplication now that papers also need audit logging — Phase 2 auth logic/behavior is UNCHANGED (verified: 28/28 Phase 2 checks still pass against real Postgres). |
| `backend/app/api/v1/papers.py` | Replaced all five RBAC-only 501 stubs with real implementations calling `paper_service`. | Core Phase 3 deliverable. |
| `backend/requirements.txt` | Added `cryptography==43.0.3`. | AES-256-GCM implementation. |
| `backend/.env.example` | Added `QUESTION_PAPER_MASTER_KEY`, `PAPER_MAX_UPLOAD_SIZE_BYTES` placeholders. | Keep example env in sync with config. |

### 5.3 Database changes

New nullable/defaulted columns on `papers` (see table above). **No new tables.** Anyone with an existing database created before this session must run either:
```
python -m scripts.init_db                 # fresh DB — creates papers with all current columns
# OR, for an ALREADY-EXISTING papers table:
python scripts/add_phase3_columns.py      # idempotent ALTER TABLE
```
`file_nonce`/`wrapped_dek` default to `""` — this is intentional (see `app/models/paper.py` docstring): it lets pre-Phase-3 code that constructs a bare `Paper(...)` row directly (specifically `tests/test_phase2_manual.py`'s own authorization-only test, which is NOT about encryption) continue to work without a NOT NULL violation. **Any real Paper row with an empty `file_nonce`/`wrapped_dek` is not decryptable and must be treated as invalid/incomplete registration data** — `paper_service.register_paper()` always fills both correctly; only ad-hoc test/debug code could leave them empty.

### 5.4 API changes

| Endpoint | Phase 2 | Phase 3 |
|---|---|---|
| `POST /papers/register` | 501 stub | **Implemented.** Admin-only. multipart: `subject` (form), `release_timestamp` (form, ISO8601), `file` (PDF). Returns 201 + safe metadata (never key material). |
| `GET /papers/{id}` | 501 stub | **Implemented.** Admin (any) / Examination Centre (only if authorized). |
| `POST /papers/{id}/authorize` | 501 stub | **Implemented.** Admin-only. Body: `{"centre_id": "<uuid>"}`. Idempotent. |
| `GET /papers/{id}/retrieve` | 501 stub | **Implemented.** Examination-Centre-only + must be authorized for this paper. Decrypts and returns the PDF. **Time-lock is NOT enforced yet** (see Section 6). |
| `GET /papers/{id}/status` | 501 stub | **Implemented.** Lightweight status view, no audit event (matches LLD API-08). |

### 5.5 Encryption design (envelope encryption — a documented Project Decision)

```
random 256-bit per-paper DEK
     -> AES-256-GCM(DEK, random 12-byte nonce) encrypts the PDF -> ciphertext (stored to disk)
     -> AES-256-GCM(MASTER_KEY, random 12-byte nonce) wraps the DEK -> wrapped_dek (stored in DB, base64)
```
The raw DEK exists only in local function scope during one encrypt/decrypt call — never logged, stored, or returned by any API.

### 5.6 Hashing design — **explicit, documented deviation from LLD Section 13**

Per this phase's explicit instructions, **SHA-256 is computed over the ORIGINAL PLAINTEXT**, not the encrypted file as LLD Section 13 originally specified. Consequence, surfaced rather than hidden: LLD Section 17's original design verified integrity *before* decryption; that is no longer possible if the hash target is the plaintext (you must decrypt first to have plaintext to hash). **The practical tamper-detection gate is now the AES-GCM authentication tag** (checked as part of decryption itself, raising `CryptoError` on any ciphertext/tag tampering *before* any plaintext is produced) — the SHA-256 comparison that follows a successful decryption is a **second, independent** integrity confirmation over the recovered plaintext, not the primary gate. Both must pass before `paper_service.retrieve_paper()` returns anything. **Recommendation for the next design review:** reconcile LLD Section 13's wording with this implementation, or reopen the decision if pre-decryption verification is actually required for the final submission.

### 5.7 Storage design

Local filesystem only (LLD DD-13 still open — not a production decision). Server-generated `uuid4().enc` filenames (never derived from user input); atomic write (tempfile → fsync → `os.replace`); defense-in-depth path-resolution guard in addition to the filename-generation guard; `delete_encrypted_file()` added for orphan-file cleanup on DB-write failure.

### 5.8 Security considerations honored

- Master key: never hard-coded, validated lazily, exactly-32-byte-after-base64-decode enforced.
- No plaintext PDF ever written to the storage directory (integration-tested by literally scanning every file in the storage dir for the plaintext bytes).
- API responses never contain `wrapped_dek`/`file_nonce`/key material (integration-tested).
- Application logs never contain plaintext PDF bytes or `wrapped_dek` (integration-tested via `caplog`).
- Orphan-file cleanup on DB persistence failure after a successful storage write.
- RBAC unchanged/reused, not reimplemented.

### 5.9 Tests executed and results (this session, genuinely run, not simulated)

| Suite | Environment | Result |
|---|---|---|
| `test_crypto_service.py` (12 tests) | SQLite (no DB needed) | **12/12 passed** |
| `test_storage_service.py` (10 tests) | Filesystem only | **10/10 passed** |
| `test_paper_api.py` (19 tests) | SQLite | **19/19 passed** |
| Same 41-test suite | **Real PostgreSQL 16** (installed in-session via apt) | **41/41 passed** |
| `test_phase2_manual.py` (the pre-existing, UNMODIFIED historical script, 28 checks) | **Real PostgreSQL 16 + real live `uvicorn`** | **28/28 passed** — confirms the `auth_service.py` refactor introduced zero regressions |
| Live HTTP smoke test (`curl` against real running `uvicorn` + real Postgres): login → OTP → register (real multipart upload) → authorize → retrieve → tamper (corrupted on-disk file) → 409 | Real PostgreSQL | **All steps passed** |

**Total: 69/69 automated checks passed, across two independently-verified database backends, plus a full manual live-HTTP walkthrough.**

One genuine bug was found and fixed **in the test fixtures only** (not application code): SQLite silently drops timezone info on `DateTime(timezone=True)` columns (a well-known SQLAlchemy+SQLite limitation; PostgreSQL does not have this problem — confirmed by reproducing the same `TypeError` against a live server with no fixture workaround present, then confirming it disappears entirely against real Postgres). Documented in `tests/conftest.py`.

### 5.10 Known limitations carried forward

- ~~Time-lock is NOT enforced~~ — **resolved in Phase 4, see Section 6.**
- Hyperledger Fabric is still `StubBlockchainService` (in-memory dict, discarded on restart) — audit events only have one durable copy (PostgreSQL).
- No Alembic — schema changes are hand-written idempotent SQL scripts.
- Large-file upload is read fully into memory (acceptable at the 20 MB default cap for a B.Tech prototype; would need streaming for larger files).
- No automated CI wiring (pytest must be run manually).
- LLD Section 13 hash-target wording vs. this implementation (Section 5.6 above) needs reconciliation.

---

---

## 6. Phase 4 — what was implemented this session

### 6.1 Files modified (no new files needed — Phase 4 fit entirely into existing structure)

| Path | What changed | Why |
|---|---|---|
| `backend/app/services/paper_service.py` | Inserted time-lock check into `retrieve_paper()` between the authorization check and ciphertext retrieval/decryption. Moved the `PAPER_ACCESS_ATTEMPT`/`PERMITTED` audit event to fire only after BOTH authorization and time-lock succeed (was: immediately after authorization alone) — a sequencing correction to match LLD Section 16's `TimeLockCheck` algorithm, not a new event type. | Core Phase 4 deliverable (SRS FR-012/FR-016). |
| `backend/app/api/v1/papers.py` | Updated docstrings only (removed "time-lock not yet enforced" notes) — no behavioural change here; `retrieve_paper()`'s route handler already just calls `paper_service.retrieve_paper()`. | Keep documentation truthful. |
| `backend/tests/test_paper_api.py` | Changed `_register_sample_paper()`'s default `release_timestamp` from a future date to a past date (`2020-01-01T00:00:00Z`), with the reason documented inline. | These Phase-3 tests are about authorization/tamper-detection, not time-lock, and predate time-lock enforcement — a future default now correctly gets blocked and made 2 pre-existing tests fail for the RIGHT reason (proving Phase 4 works), so the fixture default was corrected. |

### 6.2 New file

| Path | Purpose |
|---|---|
| `backend/tests/test_time_lock.py` | 10 dedicated Phase 4 tests (before/at/after boundary, PRE_RELEASE_ATTEMPT events, unauthorized-still-denied, tamper-detection-still-works, etc.). Uses a monkeypatched `datetime` inside `paper_service` for frozen-time testing — no real sleeps, no new dependency (`freezegun` deliberately avoided). |

### 6.3 Time-lock algorithm (LLD Section 16, now implemented exactly)

```
1. Identify paper (404 if unknown)                         [unchanged, Phase 3]
2. Verify examination-centre authorization                  [unchanged, Phase 3]
     -> if not authorized: audit DENIED, security UNAUTHORIZED_ACCESS, 403
3. current_time = datetime.now(timezone.utc)                [NEW]
   if current_time < paper.release_timestamp:                [NEW]
       -> security event PRE_RELEASE_ATTEMPT                 [NEW]
       -> audit event PRE_RELEASE_ATTEMPT / DENIED            [NEW]
       -> raise 403 "This paper is not yet available."        [NEW]
4. audit event PAPER_ACCESS_ATTEMPT / PERMITTED              [moved here from step 2]
5. retrieve ciphertext -> AES-256-GCM decrypt (tamper gate)   [unchanged, Phase 3]
6. SHA-256 re-check on recovered plaintext                    [unchanged, Phase 3]
7. audit event PAPER_RELEASED / SUCCESS -> return PDF          [unchanged, Phase 3]
```

Boundary condition implemented exactly as specified: `current_time < release_timestamp` denies; `current_time >= release_timestamp` (including EXACT equality) allows. Verified by a dedicated test that reads back the exact persisted `release_timestamp` and freezes "now" to that precise instant.

### 6.4 Security-check ordering rationale

Authorization is checked **before** time-lock (matching LLD Section 16 Step 2 before Steps 3-6). An examination centre with no legitimate claim on a paper gets a uniform 403 "not authorized" without ever learning whether that paper is time-locked, already released, or registered at all — checking time-lock first would leak release-schedule information to a party with no standing to know it.

### 6.5 API behaviour

`GET /api/v1/papers/{paper_id}/retrieve` — same endpoint, no duplicate route added.
- **Before release:** `403 {"error": {"message": "This paper is not yet available.", "status_code": 403}}`. No decryption attempted. No PDF bytes in the response (verified by test).
- **At/after release:** unchanged from Phase 3 — proceeds through authorization (already passed) → decrypt → SHA-256 check → `200` + PDF bytes.

### 6.6 Audit / security events added

- Security event `PRE_RELEASE_ATTEMPT` (severity `MEDIUM`), actor = requesting centre user, linked to `paper_id`.
- Audit event `PRE_RELEASE_ATTEMPT` / outcome `DENIED`, same actor/paper linkage.
- No PDF content, keys, wrapped DEK, OTP, or JWT ever appear in either event (unchanged discipline from Phase 3 — `audit_service.py`/`security_events`/`audit_events` only ever store IDs and short string labels).

### 6.7 Tests executed and results (this session)

| Suite | Environment | Result |
|---|---|---|
| `test_time_lock.py` (10 new tests) | SQLite | **10/10 passed** |
| Full automated suite (51 tests: Phase 3's 41 + Phase 4's 10) | SQLite | **51/51 passed** |
| Same 51-test suite | **Real PostgreSQL 16** | **51/51 passed** |
| `test_phase2_manual.py` (unmodified historical script, 28 checks) | Real PostgreSQL + real live `uvicorn` | **28/28 passed** — zero regressions from the `retrieve_paper()` reordering |
| Live HTTP smoke test: register future-dated paper → authorize → retrieve → **403 pre-release** (real `curl` + real running server + real Postgres) | Real PostgreSQL | **Passed** |
| Live HTTP smoke test: register past-dated paper → authorize → retrieve → **200 + byte-exact PDF** | Real PostgreSQL | **Passed**, `cmp` confirmed byte-for-byte match |

**Total: 79/79 automated checks passed this session (41 Phase 3 + 10 Phase 4 + 28 Phase 2 regression), plus 2 full live-HTTP walkthroughs, across two independently-verified database backends.**

### 6.8 Issues found and fixed during this phase

1. Two pre-existing Phase 3 tests used a future `release_timestamp` by coincidence of their fixture data; once time-lock was enabled they correctly started failing (proving the feature works) — fixed by moving that fixture default to the past, since those tests are about authorization/tamper-detection, not time-lock (Section 6.1 above).
2. No application-code bugs found. The Phase 3-documented SQLite/PostgreSQL timezone round-trip difference was re-confirmed to apply equally to `Paper.release_timestamp` under SQLite; the existing test-only `conftest.py` shim (registered generically on all `DateTime(timezone=True)` columns) already covered it with no changes needed.

### 6.9 Known limitations after Phase 4

- Hyperledger Fabric still stubbed (unchanged from Phase 3).
- No grace-period/clock-skew tolerance on the time-lock boundary — an exact `>=` comparison against the backend clock, as specified.
- No admin-facing "time until release" countdown in any API response yet (not requested this phase).

---

## 7. Next recommended action

**Phase 5C is now COMPLETE (see Section 13).** `FabricBlockchainService` exists and is wired into `get_blockchain_service()`, selectable via `BLOCKCHAIN_BACKEND=fabric`; `StubBlockchainService` remains the default.

The two open decisions from Section 10 were deliberately **NOT** acted on in Phase 5C, per that phase's explicit brief ("do not silently add functionality that belongs to later phases") — `paper_service.py` was not touched, and `Paper` gained no new column:
1. Whether to wire CC-01/RegisterPaper into `paper_service.register_paper()` — **still open**.
2. Whether `ledger_tx_reference` should be added to `Paper` itself — **still open**.

Recommended next step: confirm decisions #1/#2 above with the project owner, then (if confirmed) wire `paper_service.register_paper()` to call `get_blockchain_service().register_paper(...)` and persist the returned transaction ID — this is naturally a Phase 5D-scoped, focused change now that `FabricBlockchainService` exists to call. Do not treat this note as authorization to implement it automatically.

## 8. Assumptions / technical decisions log (cumulative)

- Phase 1: SQLAlchemy ORM (LLD didn't fix this), UUID PKs generated in Python, bcrypt for passwords, DevConsoleOTPProvider for dev-only OTP delivery.
- Phase 2: private audit helpers inside `auth_service.py` (later generalized in Phase 3, Section 5.1 above).
- **Phase 3 (this session):**
  - Envelope encryption (per-paper DEK wrapped by master key) — LLD DD-07 finally resolved.
  - SHA-256 over plaintext, not ciphertext — explicit deviation from LLD Section 13 (Section 5.6 above).
  - `file_nonce`/`wrapped_dek` default to `""` for backward compatibility with pre-Phase-3 direct `Paper(...)` construction in existing tests.
  - Missing/undersized encrypted file on retrieval → `ServiceUnavailableException` (503), distinct from unknown `paper_id` (404) — resolves an LLD Section 18 "NOT YET DETERMINED" row as an explicit Phase 3 decision.
  - `authorize_centre` is idempotent (re-authorizing an already-authorized centre returns the existing row rather than erroring).

- **Phase 4 (this session):**
  - Time-lock uses a strict `<` / `>=` comparison against the trusted backend clock — no grace period or clock-skew tolerance added (not requested; would be a deliberate future decision if needed).
  - Authorization is checked strictly before time-lock (Section 6.4 rationale above) — this ordering choice was made explicitly, not left to fall out of code structure by accident.
  - The pre-existing `PAPER_ACCESS_ATTEMPT`/`PERMITTED` audit event was moved (not renamed) to fire after time-lock passes, correcting a Phase 3 sequencing gap against LLD Section 16 — flagged as a fix, not silently changed.

## 9. Environment / setup information safe to record here

- Backend Python: 3.12. Dependencies in `backend/requirements.txt` (now includes `cryptography==43.0.3`).
- `QUESTION_PAPER_MASTER_KEY` generation: `python -c "import secrets,base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"`.
- To pick up Phase 3 columns on an existing database: `python scripts/add_phase3_columns.py` (see Section 5.3).
- Real PostgreSQL is required for a live demo of the OTP-verify flow — do not attempt to demo against SQLite (see Section 5.9's timezone note); the same applies to any live demo touching `paper.release_timestamp` comparisons.
- To demo time-lock live: register a paper with `release_timestamp` a few minutes in the future, attempt retrieval (expect 403 "not yet available"), then register a second paper with a past `release_timestamp` and retrieve it successfully (expect 200 + PDF bytes) — see Section 6.7 for the exact `curl` sequence used to verify this.

---

## 10. PHASE 5 READINESS INSPECTION (analysis only — Phase 5 NOT implemented)

**Status: inspection/design only. No source code, chaincode, Fabric network, or dependencies were installed, modified, or created this session.**

### Findings (from actual code, not assumption)
- `BlockchainService` ABC (`backend/app/services/blockchain_service.py`) defines 9 methods (CC-01–CC-09). **Only ONE — `record_audit_event` (CC-08) — is ever actually called**, and only from `audit_service.py`. `paper_service.py` never imports `blockchain_service` directly; `register_paper`, `authorize_centre`, `record_access_attempt`, `record_integrity_result`, `record_release` (CC-01,02,05,06,07) are fully implemented in the stub but are dead code — nothing in the app calls them.
- `AuditEvent.ledger_tx_reference` is the only column that ever receives a (stub) transaction reference. `PaperRegisterResponse.ledger_tx_reference` (API schema field) is **always `None`** — `Paper` has no such column and `papers.py`'s register handler never sets it.
- Config is already anticipatory: `BLOCKCHAIN_BACKEND`, `FABRIC_GATEWAY_ENDPOINT`, `FABRIC_CHANNEL_NAME`, `FABRIC_CHAINCODE_NAME` already exist in `config.py`/`.env.example`, all currently unused placeholders.
- No Docker/docker-compose files, no chaincode, no Fabric network config anywhere in the repository. `blockchain/` contains only a README stating "NOT YET STARTED."
- No blockchain-related tests exist yet.

### Architecture decision (full reasoning delivered in the chat response for this phase)
- **Smallest correct scope:** keep a single generic audit/event chaincode transaction (mirroring the CC-08 pattern already used) as the primary Fabric integration point for Phase 5, since that's the only one the app currently calls — plus add `RegisterPaper`/`GetPaper`/`VerifyPaperHash` since "immutable paper metadata" and "hash verification" are headline project requirements, not optional.
- **Fabric network:** single org, single peer, single-node Raft orderer, LevelDB (no CouchDB — no rich/JSON queries needed), one channel, one chaincode. Target Fabric v2.5.x (current LTS as of this session's research; v3.x exists but v2.5 remains LTS and is the safer choice for a graded prototype).
- **Chaincode language: TypeScript** (`fabric-contract-api-node`), an officially-supported chaincode language — chosen so the same language can serve both the chaincode AND the Fabric Gateway adapter (below), minimizing new-language surface for a B.Tech team already working in Python/React.
- **FastAPI↔Fabric integration:** a small local Node.js/TypeScript "Fabric Gateway adapter" microservice using the official `@hyperledger/fabric-gateway` npm package, called by FastAPI over local HTTP/JSON. Explicitly **NOT** `fabric-sdk-py` (unmaintained, Fabric-1.4-only — confirmed via research this session) and **NOT** any unofficial third-party Python Gateway package (the only one found, `moe-fabric-gateway`, is a brand-new v0.0.x single-maintainer package with no track record — too risky for this project's security-critical path).

### Prerequisites confirmed missing from the project repository
Docker, Docker Compose, Fabric binaries/images, Node.js + npm, a Go toolchain (only needed if Go chaincode is chosen instead of TypeScript later). PostgreSQL and Python are already in place and unaffected by Phase 5. (Note: tool availability was checked in the current inspection sandbox as an illustrative proxy only — the actual project owner's development machine must be checked separately.)

### Unresolved decisions to confirm before implementing Phase 5
1. Whether to wire CC-01 (RegisterPaper) onto Fabric at registration time (currently unused) — recommended yes.
2. Whether `ledger_tx_reference` should be added to `Paper` itself (currently only on `AuditEvent`) so `PaperRegisterResponse.ledger_tx_reference` stops being permanently `None`.
3. The LLD Section 13 hash-target question (flagged since Phase 3, still open) should be resolved before or during Phase 5, since Fabric will store `sha256_hash` and its exact meaning needs to be unambiguous in the documentation Fabric is meant to make trustworthy.

### Recommended next implementation step
In order: (a) minimal single-org/single-peer Fabric test network + TypeScript chaincode (`RegisterPaper`, `GetPaper`, `VerifyPaperHash`, `RecordAuditEvent`), (b) Node/TypeScript Gateway adapter service, (c) a new `FabricBlockchainService` implementing the EXISTING `BlockchainService` ABC by calling the adapter over HTTP (zero changes needed to `paper_service.py`'s call sites for the CC-08 path; new calls needed only if decision #1 above is confirmed), (d) tests per the plan in the delivered report.

**PHASE 5 STATUS: NOT READY FOR IMPLEMENTATION YET** — architecture is now designed and de-risked (current Fabric tooling researched, not assumed from stale training data), but no Fabric network, chaincode, or adapter code exists yet, and the three unresolved decisions above should be confirmed with the project owner first.

---

## 11. PHASE 5A — Fabric Network + Chaincode Foundation — COMPLETE

**This session implemented and GENUINELY VERIFIED (real transaction IDs below) Phase 5A. Backend code (`backend/app/`) was NOT touched — confirmed by re-running the full 51-test automated suite after this work, still 51/51 passing.**

### 11.1 Environment findings

- Docker CAN run in the dev sandbox (daemon starts successfully), but **Docker Hub is unreachable**: `docker pull hello-world` → `403 Forbidden` from `registry-1.docker.io`, confirmed via the egress proxy's own `x-deny-reason: host_not_allowed` header. This blocks the classic Docker-per-chaincode / docker-compose model in this sandbox specifically.
- **GitHub Releases ARE reachable** (`github.com`, `release-assets.githubusercontent.com` are allowlisted), and Fabric publishes native binary releases there, independent of Docker Hub. Downloaded and verified real, working Fabric v2.5.16 binaries (`peer`, `orderer`, `cryptogen`, `configtxgen`, `osnadmin`) and Fabric CA v1.5.22 binaries this way.
- Node.js v22 / npm present; Git present. No Go toolchain (not needed — TypeScript chosen for chaincode, per the Phase 5 readiness inspection).
- **This is a sandbox-specific constraint, not necessarily true of the student's actual Windows + Docker Desktop machine**, where Docker Hub should be reachable normally — see `blockchain/network/README.md` for both paths.

### 11.2 Architecture decision: native binaries + Chaincode-as-a-Service (CCaaS)

Given the Docker Hub block, this phase used:
- **peer/orderer as native OS processes** (not Docker containers) — the same approach as Fabric's own official `test-network-nano-bash` sample, not a project-specific hack.
- **Chaincode deployed via CCaaS** (Chaincode-as-a-Service) — an officially-supported Fabric 2.4+ deployment mode, bundled directly in the Fabric binary release (`builders/ccaas/`). The chaincode runs as a plain Node.js process the peer connects to over TCP; no Docker image build is required for the chaincode. This is also the standard recommended approach for Kubernetes deployments — not unique to this project's constraints.
- A `docker-compose.yaml` (Path B) was also written for the classic model, for use on a machine with normal Docker Hub access — **written but not runtime-tested this session** (clearly labeled as such in `blockchain/network/README.md`).

### 11.3 Files created

| Path | Purpose |
|---|---|
| `blockchain/network/crypto-config/crypto-config.yaml` | cryptogen input (1 OrdererOrg, 1 Org1/1 peer) |
| `blockchain/network/configtx/configtx.yaml` | configtxgen input — defines `PaperChannel` profile for `paperchannel` |
| `blockchain/network/orderercfg/orderer.yaml` | Orderer config template (values overridden by env vars at runtime) |
| `blockchain/network/peercfg/core.yaml` | Peer config template, with `externalBuilders` pointed at the CCaaS builder |
| `blockchain/network/docker-compose.yaml` | Path B (Docker Compose) — NOT runtime-tested this session |
| `blockchain/network/README.md` | Documents both paths, Windows/WSL2 guidance, exact commands |
| `blockchain/network/scripts/generate-crypto.sh` | Runs cryptogen |
| `blockchain/network/scripts/generate-channel-artifacts.sh` | Runs configtxgen |
| `blockchain/network/scripts/start-network.sh` | Starts orderer+peer natively, joins paperchannel |
| `blockchain/network/scripts/deploy-chaincode.sh` | Packages (CCaaS)/installs/approves/commits chaincode, starts the chaincode server |
| `blockchain/network/scripts/test-transactions.sh` | Runs the verified demonstration transaction sequence |
| `blockchain/network/scripts/stop-network.sh` | Stops all native processes cleanly |
| `blockchain/chaincode/paper-ledger/src/paperContract.ts` | The chaincode: RegisterPaper, GetPaper, VerifyPaperHash, RecordAuditEvent |
| `blockchain/chaincode/paper-ledger/src/index.ts` | Package entry point (`contracts` export, per fabric-shim's bootstrap convention) |
| `blockchain/chaincode/paper-ledger/package.json` / `tsconfig.json` | Chaincode build config |
| `.gitignore` (project root, new file) | Excludes `organizations/` (private keys!), `data/`, `node_modules/`, `dist/`, etc. |

### 11.4 Files modified

| Path | Change |
|---|---|
| `blockchain/README.md` | Updated from "NOT YET STARTED" to reflect Phase 5A completion and Phase 5B scope |

**No files under `backend/` were modified this session** — confirmed via `py_compile` + full pytest rerun (51/51 passed) after all Phase 5A work.

### 11.5 Chaincode design (as implemented, matches the approved spec)

Four transactions, exactly as specified: `RegisterPaper` (rejects duplicate `paper_id`, validates SHA-256 format), `GetPaper` (read-only, clear not-found error), `VerifyPaperHash` (read-only, returns `{paper_id, match}`, does not modify stored data), `RecordAuditEvent` (rejects duplicate `event_id` via a deterministic `AUDIT_<eventId>` key — enforces "audit records must not be editable after creation" ON-CHAIN, not just by application discipline). Never accepts PDF content, AES keys, wrapped DEKs, passwords, OTPs, or JWTs — there is no parameter through which any of those could be passed. `admin_id`/`actor_id` stored as plain UUID strings (application-level provenance), deliberately separate from Fabric's own cryptographic identity (which proves the authorized backend submitted the transaction) — matching the Phase 5 readiness inspection's recommendation.

### 11.6 Real, verified test results (this session)

**Pure-logic unit test** (fake in-memory stub, no Fabric needed): RegisterPaper, duplicate rejection, GetPaper (found + not-found), VerifyPaperHash (match + mismatch), RecordAuditEvent, duplicate-event rejection, empty-field validation — all passed.

**Full live network transaction test** (real orderer + real peer + real CCaaS chaincode server, run via the actual `blockchain/network/scripts/*.sh` files in this repository — not a throwaway script):

```
### 1. RegisterPaper (paper-demo-1789358290)
Chaincode invoke successful. result: status:200 payload:"e54a556360bc069b03103b8e20b83821a10c60f1a29566a3e51e87b22fa340a4"

### 2. Duplicate RegisterPaper (MUST fail with DUPLICATE_PAPER)
Error: endorsement failure during invoke. response: status:500 message:"DUPLICATE_PAPER: paper_id 'paper-demo-1789358290' is already registered on the ledger."

### 3. GetPaper
{"docType":"paper","paperId":"paper-demo-1789358290","sha256Hash":"aaaa...aaaa","registeredAt":"2026-01-01T00:00:00Z","adminId":"admin-demo","subject":"Demo Subject","encryptionAlgorithm":"AES-256-GCM"}

### 4. VerifyPaperHash — correct hash
{"paper_id":"paper-demo-1789358290","match":true}

### 5. VerifyPaperHash — incorrect hash
{"paper_id":"paper-demo-1789358290","match":false}

### 6. RecordAuditEvent
Chaincode invoke successful. result: status:200 payload:"da9fa8aa39e8f3fb238b4aafb738ac2b865f71765daf8fe2199fd1862cce8ab8"

### 7. GetPaper on a NON-existent paper_id (MUST fail with PAPER_NOT_FOUND)
Error: endorsement failure during query. response: status:500 message:"PAPER_NOT_FOUND: no paper is registered with paper_id 'does-not-exist'."
```

Every success condition from the task brief was met: network starts, `paperchannel` exists, chaincode deployed, all four transactions work correctly, duplicate registration rejected, incorrect hash correctly reported as mismatch, no sensitive data ever touches the chain, and Phases 1–4 remain fully working (51/51 backend tests, confirmed after this work).

### 11.7 Known issues found and fixed during this phase (documented, not hidden)

1. **TLS SAN mismatch**: connecting via `127.0.0.1` failed TLS verification, since cryptogen issues certificates for hostnames (`orderer.example.com`, `peer0.org1.example.com`), not bare IPs. Fixed via `/etc/hosts` entries — documented in `network/README.md` as a required setup step, not silently patched around.
2. **Raft WAL/snapshot path collision**: the orderer's Raft consensus storage defaults to a *fixed OS path* (`/var/hyperledger/production/orderer/etcdraft/...`) independent of the file-ledger location — running the network a second time with a freshly-reset ledger but STALE Raft WAL data caused a ledger-hash-mismatch panic. Fixed by explicitly setting `ORDERER_CONSENSUS_WALDIR`/`ORDERER_CONSENSUS_SNAPDIR` into the same cleaned `network/data/` directory in `start-network.sh`.
3. **`peer lifecycle chaincode package --lang external` does not exist** — that flag only recognizes source-based languages (golang/node/java). CCaaS packages must be hand-built (`metadata.json` + `code.tar.gz{connection.json}`) — this is the documented convention, now implemented correctly in `deploy-chaincode.sh`.
4. **Single-node Raft still needs a moment to elect a leader** after a fresh channel join — `approveformyorg` can transiently fail with "no Raft leader" immediately after joining. Fixed with a short wait plus retry loop in both `start-network.sh` and `deploy-chaincode.sh`.
5. **Test-script timing**: an early version of `test-transactions.sh` fired RegisterPaper and its duplicate-rejection check back-to-back with no delay, racing ahead of the orderer's `BatchTimeout` (2s) — both calls endorsed successfully (simulated against not-yet-updated committed state) before either was actually committed, and a subsequent immediate `GetPaper` saw nothing yet. Fixed by adding `sleep 3` after invokes that a later step depends on. This is a test-script timing fix, not a chaincode or network defect — Fabric's own MVCC validation would still have caught the true duplicate-write race at commit time as a defense-in-depth backstop, independent of the chaincode's own explicit check.
6. **TypeScript type errors** (real, caught by `tsc`, not glossed over): `ctx.stub.getState()` returns `Uint8Array` per fabric-shim's type declarations, not `Buffer` — calling `.toString("utf8")` directly failed to compile; fixed with explicit `Buffer.from(bytes).toString("utf8")`. Also: `Shim.server()` cannot take a raw `Contract`-derived class directly (the internal `ChaincodeFromContract` wrapper isn't publicly exported) — fixed by switching to the officially-documented `fabric-chaincode-node server` CLI (bundled with `fabric-shim`) with a `contracts` array export from `index.ts`, which is the correct, documented pattern.

### 11.8 Known limitations

- Docker Compose path (Path B) is written but not runtime-verified — needs confirmation on a machine with real Docker Hub access.
- Single-peer, single-org network — no fault tolerance (matches the approved minimal architecture; not a gap).
- No mutual TLS between the peer and the CCaaS chaincode server (`tls_required: false` in `connection.json`) — acceptable for this local/dev deployment; flagged as a production-hardening item for later, not implemented here.
- The Phase 5 readiness inspection's open decisions (wiring CC-01 into `paper_service.register_paper()`, adding `Paper.ledger_tx_reference`) remain unresolved — Phase 5A deliberately did not touch backend code, per this phase's explicit scope boundary.

### 11.9 Pending Phase 5B work

Implement `FabricBlockchainService(BlockchainService)` (most likely via a small Node/TypeScript Fabric Gateway adapter, per the readiness inspection), wire it into `get_blockchain_service()`'s existing backend-selection switch, and confirm the two open decisions from Section 10 with the project owner before starting.

### 11.10 Exact next step

**Phase 5B**: build the FastAPI↔Fabric integration layer described in Section 11.9, using the now-real, now-verified network and chaincode from this phase as the target.

---

## 12. PHASE 5B — Fabric Gateway Adapter — COMPLETE

**This session implemented and GENUINELY VERIFIED (8/8 real integration tests, real transaction IDs, no mocks) the Gateway Adapter against the actual live Phase 5A network. `backend/app/` was NOT touched — confirmed via `grep` (no `FabricBlockchainService` exists yet) and a full 51-test regression run (51/51 passing).**

### 12.1 Environment

Node.js v22, npm — same toolchain as Phase 5A's chaincode. `@hyperledger/fabric-gateway` v1.12.1 (latest stable at time of writing; verified against npm registry before pinning). `@grpc/grpc-js` pinned to `1.14.4` specifically to match the version `@hyperledger/fabric-gateway` itself depends on (`^1.14.0`) — an earlier attempt at `1.11.3` caused a real TypeScript compile error (`Client` type mismatch) from npm installing two incompatible copies of the same package; fixed by aligning versions so npm deduplicates them into one.

### 12.2 Gateway Library Version

`@hyperledger/fabric-gateway@1.12.1` — the official client, confirmed NOT `fabric-sdk-py` (confirmed dead/Fabric-1.4-only during the Phase 5 readiness inspection), not a CLI subprocess wrapper, not a mock in the production code path.

### 12.3 Fabric Network Connection

Connects to `peer0.org1.example.com:7051` (the exact endpoint Phase 5A's own scripts use), channel `paperchannel`, chaincode `paper-ledger`, using Phase 5A's Org1 Admin identity (cert + private key paths under `network/organizations/...`) and the peer's own TLS root CA for server-certificate verification. TLS via `grpc.credentials.createSsl()`, matching the real, working configuration already proven in Phase 5A.

### 12.4 Files Created

| Path | Purpose |
|---|---|
| `blockchain/gateway-adapter/src/types.ts` | Request/response TypeScript interfaces |
| `blockchain/gateway-adapter/src/fabricGateway.ts` | Connection management: loads identity/TLS from env, builds the real Gateway client, exposes `getContract()` |
| `blockchain/gateway-adapter/src/server.ts` | Express HTTP server: 5 routes + centralized error classification |
| `blockchain/gateway-adapter/package.json` / `tsconfig.json` | Build config |
| `blockchain/gateway-adapter/tsconfig.jest.json` | Jest-only tsconfig (adds `allowJs`) — kept separate from the production build config; see Section 12.9 |
| `blockchain/gateway-adapter/jest.config.js` | Jest config, with a narrow `transformIgnorePatterns` exception for one ESM-only transitive dependency |
| `blockchain/gateway-adapter/.env.example` | Example config — values already match Phase 5A's actual network exactly |
| `blockchain/gateway-adapter/README.md` | Full documentation: architecture, env vars, API examples, troubleshooting |
| `blockchain/gateway-adapter/tests/unit/server.test.ts` | 13 HTTP-layer unit tests, Fabric contract mocked |
| `blockchain/gateway-adapter/tests/integration/fabricIntegration.test.ts` | 8 REAL Fabric integration tests, zero mocks |

### 12.5 Files Modified

| Path | Change | Reason |
|---|---|---|
| `blockchain/README.md` | Updated to reflect Phase 5B completion and Phase 5C scope | Keep top-level status accurate |
| `blockchain/network/scripts/start-network.sh`, `stop-network.sh` | Replaced `pkill -f` with a `pgrep -f` + `kill` helper (`safe_kill_matching`) | Real bug found this session: `pkill -f` was observed to hang unreliably in this sandboxed (gVisor/runsc) environment, while `pgrep -f` and plain `kill` both worked reliably. This is a portability fix to Phase 5A's scripts, not a Phase 5B feature — documented here since it was discovered and fixed while setting up the network for Phase 5B's real integration tests. |

**No files under `backend/` were modified** — confirmed via `grep -n "FabricBlockchainService" backend/app/services/blockchain_service.py` (no match) and a full pytest rerun (51/51 passed) after all Phase 5B work.

### 12.6 npm Packages

Production: `express@4.21.1`, `@hyperledger/fabric-gateway@1.12.1`, `@grpc/grpc-js@1.14.4`. Dev/test: `typescript@5.6.3`, `jest@29.7.0`, `ts-jest@29.2.5`, `supertest@7.0.0`, plus corresponding `@types/*` packages. Every version was confirmed to actually exist on the npm registry (`npm view <pkg>@<version> version`) before being pinned, rather than assumed.

### 12.7 Adapter Port

`8081` (configurable via `ADAPTER_PORT`), bound to `127.0.0.1` only — never `0.0.0.0`.

### 12.8 Environment Variables

`ADAPTER_PORT`, `FABRIC_MSP_ID`, `FABRIC_CHANNEL_NAME`, `FABRIC_CHAINCODE_NAME`, `FABRIC_PEER_ENDPOINT`, `FABRIC_PEER_HOST_ALIAS` (optional), `FABRIC_TLS_CERT_PATH`, `FABRIC_CERT_PATH`, `FABRIC_PRIVATE_KEY_PATH` — exactly the names requested in the Phase 5B brief. All loaded from `process.env` with fail-fast validation naming the specific missing variable; nothing hardcoded.

### 12.9 Fabric Identity Used

Phase 5A's Org1 Admin identity (`network/organizations/peerOrganizations/org1.example.com/users/Admin@org1.example.com/msp/{signcerts/Admin@org1.example.com-cert.pem,keystore/priv_sk}`) — the same identity Phase 5A's own CLI scripts use for every lifecycle/invoke operation, so this is consistent with (not a regression from) Phase 5A. Documented in `fabricGateway.ts`'s module docstring as a flagged, not-silently-accepted production-hardening item: a narrower, dedicated "application" identity would be preferable once this moves beyond a B.Tech prototype, but does not exist in this project yet.

### 12.10 API Endpoints

`GET /health`, `POST /fabric/register-paper`, `GET /fabric/paper/:paper_id`, `POST /fabric/verify-hash`, `POST /fabric/audit-event` — all five as specified. Full request/response examples in `gateway-adapter/README.md`.

### 12.11 Real Transaction Tests (genuinely executed, no mocks)

All 8 integration tests passed against the actual live network (built via Phase 5A's own scripts, run fresh this session):

```
✓ GET /health reports ok
✓ registers a real paper on the real ledger and returns a genuine transaction ID
✓ rejects a duplicate RegisterPaper for the same paper_id
✓ retrieves the real registered paper via GetPaper
✓ returns 404 for a paper that was never registered
✓ VerifyPaperHash returns match:true for the correct hash
✓ VerifyPaperHash returns match:false for an incorrect hash
✓ records a real audit event and returns a genuine transaction ID
```

A real duplicate-rejection error captured verbatim during this run:
```
chaincode response 500, DUPLICATE_PAPER: paper_id 'it-paper-1789470514692' is already registered on the ledger.
```
The `transaction_id` returned by the register-paper and audit-event tests was asserted to match `/^[a-f0-9]{64}$/` (a real Fabric transaction ID shape), not a placeholder — e.g. `efc34520bc099ad43a3ee67e1bcdf130e8301c3fc78bec264b7c51d81d3002cc` was one such value observed this session.

### 12.12 Error Handling Tests (unit, mocked)

13/13 passed — request validation (missing fields → 400), success-path response shaping (201/200 with correct bodies), chaincode error prefix mapping (`DUPLICATE_PAPER`/`DUPLICATE_EVENT` → 409, `PAPER_NOT_FOUND` → 404), Fabric-unavailable/timeout mapping (→ 503), and an explicit test asserting no stack trace or key-material substring (`priv_sk`, `ENOENT`, `at Object.`) ever appears in an HTTP response body.

### 12.13 Backend Regression Tests

**51/51 PASS**, confirmed after all Phase 5B work — zero backend files were touched this session.

### 12.14 Security Measures

Binds to `127.0.0.1` only. No private key/certificate content ever appears in a log line or HTTP response — only file *paths* are logged (paths are not secrets; the files they point to are git-ignored). `classifyError()` centralizes every error→response mapping so no route handler can accidentally leak raw Fabric/Node error objects into a response body. `.env` is git-ignored; `.env.example` contains only paths.

### 12.15 Known Issues (found and fixed this session, documented not hidden)

1. **`pkill -f` hangs unreliably** in this sandboxed (gVisor/runsc) environment — discovered while setting up the network for integration testing. Fixed in Phase 5A's `start-network.sh`/`stop-network.sh` (Section 12.5 above) by switching to `pgrep -f` + `kill`, both confirmed reliable.
2. **`@grpc/grpc-js` version mismatch** — pinning a different version than `@hyperledger/fabric-gateway`'s own dependency caused duplicate installed copies and a real TypeScript structural-type error. Fixed by pinning to the exact compatible version (Section 12.1).
3. **Express route generic-type mismatch**: `Request<{ paper_id: string }>` didn't satisfy Express's handler type constraints under strict mode. Fixed by using a plain `Request` type and reading `req.params.paper_id` directly.
4. **Jest could not parse `@noble/curves`** (a transitive dependency of `@hyperledger/fabric-gateway`, used for its cryptographic signing), which ships ESM-only JavaScript — Jest ignores `node_modules` for transformation by default. Fixed with a narrow `transformIgnorePatterns` exception plus a Jest-only `tsconfig.jest.json` (with `allowJs: true`, kept separate from the production build's `tsconfig.json`) so ts-jest can transpile just that one dependency.
5. **Background-process lifetime across tool-call boundaries** (an environment characteristic of this development sandbox, not a code defect): the network, once started, does not survive into a separate shell invocation. All real verification in this session was therefore run as a single chained sequence (start network → deploy chaincode → run integration tests) within one continuous execution — documented here for anyone reproducing this on a persistent machine, where this is a non-issue.

### 12.16 PROJECT_STATE.md Update

Done — this Section 12, plus the Section 3 phase-status table and Section 7 "next recommended action" updated to point at Phase 5C.

### 12.17 Exact Phase 5C Next Step

Implement `FabricBlockchainService(BlockchainService)` in `backend/app/services/blockchain_service.py`, making HTTP calls to this adapter's `http://127.0.0.1:8081` endpoints, and wire it into `get_blockchain_service()`'s existing backend-selection switch. Confirm the two Phase-5-readiness open decisions (Section 10) first: whether to wire CC-01/RegisterPaper into `paper_service.register_paper()`, and whether to add a `ledger_tx_reference` column to `Paper` itself.

**PHASE 5B — COMPLETE.** Per the brief, stopping here — not proceeding to Phase 5C automatically.

---

## 13. PHASE 5C — Connect FastAPI Backend to the Fabric Gateway Adapter — COMPLETE

**This session implemented `FabricBlockchainService` and wired it into the existing `get_blockchain_service()` factory. `StubBlockchainService` is unchanged and remains the default (`BLOCKCHAIN_BACKEND=stub`). Full regression run: 80/80 backend tests passing (51 pre-existing + 29 new), 13/13 gateway-adapter unit tests passing (unchanged, not touched this session).**

### 13.1 Correction to the arithmetic in the task brief this session started from

The brief this session began from stated: *"The existing BlockchainService abstraction contains 9 methods... the currently verified chaincode exposes ONLY 4 functions... For the 5 unsupported BlockchainService operations, implement an explicit unsupported-operation behavior."*

Inspecting the actual source (`blockchain_service.py`, `paperContract.ts`) shows this arithmetic does not hold, and per this project's own continuity protocol ("actual source code and actual test execution are authoritative" over a prior prompt's assumptions), the discrepancy is reported rather than silently reproduced:

- The chaincode's 4 functions are `RegisterPaper`, `GetPaper`, `VerifyPaperHash`, `RecordAuditEvent`.
- Only **3** of those have a same-purpose counterpart among the ABC's 9 methods: `register_paper`, `get_paper_metadata`, `record_audit_event`.
- `VerifyPaperHash` has **no** ABC counterpart at all. The closest-named existing method, `record_integrity_result` (CC-06), is specified as a ledger *write* that appends a match/mismatch record — a different, and still chaincode-unsupported, operation. `VerifyPaperHash` is itself a real, read-only chaincode query (`@Transaction(false)`, no `putState` call).
- That leaves **6** ABC methods with no chaincode backing (`authorize_centre`, `revoke_centre`, `record_access_attempt`, `record_integrity_result`, `record_release`, `record_exam_violation`), not 5.

Resolution taken (see 13.3): implement the 3 genuinely-matching ABC methods against Fabric; add `verify_paper_hash` as a new, non-abstract, opt-in extension method on the shared `BlockchainService` base class (default implementation raises `UnsupportedOperationException`; only `FabricBlockchainService` overrides it) rather than forcing a mismatched signature onto an existing ABC method or silently dropping the capability; mark the 6 true CC-0x gaps as unsupported.

### 13.2 Files created

| Path | Purpose |
|---|---|
| `backend/app/services/fabric_blockchain_service.py` | `FabricBlockchainService(BlockchainService)` — HTTP client for the Phase 5B Gateway Adapter. Full method-by-method mapping and rationale in its module docstring. |
| `backend/tests/test_fabric_blockchain_service.py` | 29 unit tests, `httpx.MockTransport`-based (no live Fabric/adapter process required to run this file). |

### 13.3 Files modified

| Path | Change | Reason |
|---|---|---|
| `backend/app/services/blockchain_service.py` | (1) `PaperMetadataRecord.release_timestamp` retyped `datetime` → `datetime \| None`. (2) New concrete (non-abstract) `verify_paper_hash()` method added to `BlockchainService`, default raises `UnsupportedOperationException`. (3) `get_blockchain_service()` factory extended to construct `FabricBlockchainService` when `BLOCKCHAIN_BACKEND=fabric`. | (1) The deployed chaincode's `PaperRecord` genuinely has no release-timestamp field (see 13.1/13.4) — returning a fabricated datetime would misrepresent real ledger data; `None` is the honest value. Confirmed low-risk: `PaperMetadataRecord`/`get_paper_metadata` had zero callers anywhere in `app/` before this session (verified by `grep`). (2) See 13.1. (3) The stated Phase 5C objective. |
| `backend/app/exceptions/base.py` | Added `UnsupportedOperationException` (HTTP 501). | Needed for the "explicit, well-defined unsupported-operation behavior" requirement; fits the existing `AppException` hierarchy pattern exactly (matches `ServiceUnavailableException`'s style/docstring conventions). |
| `backend/app/config.py` | Added `FABRIC_GATEWAY_TIMEOUT_SECONDS` (float, default 5.0). Added a comment on `FABRIC_CHANNEL_NAME`/`FABRIC_CHAINCODE_NAME` clarifying they are **not** read by the backend (owned entirely by the Node adapter's own `.env`) — left in place, unused, rather than removed. | New setting genuinely required for the HTTP client's timeout. The comment prevents a future reader from assuming the backend uses those two settings when it does not. |
| `backend/.env.example` | Documented `FABRIC_GATEWAY_TIMEOUT_SECONDS`; updated the `BLOCKCHAIN_BACKEND` comment block. | Keep example config in sync with `config.py`. |
| `backend/requirements.txt` | Moved `httpx` under a new "HTTP client" comment noting it is now also a **runtime** dependency (not test-only), used by `FabricBlockchainService`. | Accuracy — no version change, `httpx==0.27.2` was already present and used for `TestClient`. |

**No files deleted.** No API routes changed. No database/schema changes. No chaincode changes. `paper_service.py`, `audit_service.py`, and every existing API router are **byte-for-byte unmodified** this session (confirmed via `git diff` — see 13.11).

### 13.4 Fabric operation mapping (method-by-method)

| ABC method | Chaincode fn | Status | Key mapping notes |
|---|---|---|---|
| `register_paper` | `RegisterPaper` | **SUPPORTED** | `release_timestamp` param accepted (ABC signature) but **not sent** — chaincode has no field for it; PostgreSQL `papers.release_timestamp` remains sole authority (unchanged architecture, FR-012). `registered_at` (chaincode-required, not an ABC param) supplied as `datetime.now(timezone.utc)` at call time. `admin_id`/`subject`/`encryption_algorithm` (also chaincode-required, not ABC params) read from the `metadata` dict; missing/empty → `ValidationFailedException` naming the missing key(s), **no HTTP call made**. |
| `get_paper_metadata` | `GetPaper` | **SUPPORTED (partial, documented)** | Returns `PaperMetadataRecord(release_timestamp=None, status="registered", authorized_centre_references=[])`. `status="registered"` is not a guess — it is the only state this chaincode tracks (a record's existence *is* its "registered" state; no other lifecycle transition exists on-chain). `authorized_centre_references=[]` is explicitly documented (in both `PaperMetadataRecord`'s and this method's docstrings) as **not** an authorization source — PostgreSQL's `paper_authorizations` table already was, and remains, the sole authorization source of truth (LLD 7.5/15), unchanged by this phase. Returns `None` (not an exception) when Fabric reports `PAPER_NOT_FOUND`, matching the ABC's documented `-> PaperMetadataRecord \| None` contract. |
| `record_audit_event` | `RecordAuditEvent` | **SUPPORTED (documented limitation)** | Chaincode requires an `event_id` dedup key the ABC signature has no parameter for; `FabricBlockchainService` generates a fresh `uuid.uuid4()` per call. This id is **not** shared with the PostgreSQL `audit_events.event_id` primary key, so it provides no cross-store correlation beyond the returned `transaction_id` — a genuine, documented limitation, not silently glossed over. |
| *(new, non-ABC)* `verify_paper_hash` | `VerifyPaperHash` | **SUPPORTED** | Real call to the chaincode's read-only hash-comparison query. Returns the genuine `match: bool` from Fabric — never a fabricated result. Base `BlockchainService.verify_paper_hash()` (used by `StubBlockchainService`, which does not override it) raises `UnsupportedOperationException`. |
| `authorize_centre` | — | **UNSUPPORTED** | Raises `UnsupportedOperationException`; no HTTP call made. |
| `revoke_centre` | — | **UNSUPPORTED** | ″ |
| `record_access_attempt` | — | **UNSUPPORTED** | ″ |
| `record_integrity_result` | — | **UNSUPPORTED** | ″ — note this is distinct from (and does not replace the need for, if ever implemented) `verify_paper_hash` above; see 13.1. |
| `record_release` | — | **UNSUPPORTED** | ″ |
| `record_exam_violation` | — | **UNSUPPORTED** | ″ (CC-09, Faculty-Review Addendum — see Section 4's flagged documentation gap; unaffected by, and unresolved by, this phase). |

Every "UNSUPPORTED" row raises `UnsupportedOperationException` **before** any HTTP request is built — verified explicitly by test (13.6, item 8: `assert calls == []`).

### 13.5 Configuration

New/changed settings (`backend/app/config.py`, `backend/.env.example`):
- `BLOCKCHAIN_BACKEND` — unchanged field, now has two real values: `stub` (default, unchanged behaviour) / `fabric` (new).
- `FABRIC_GATEWAY_ENDPOINT` — unchanged field, now actually consumed (previously an inert placeholder). Required (non-empty) when `BLOCKCHAIN_BACKEND=fabric`; `get_blockchain_service()` raises `RuntimeError` naming the missing variable if not set, rather than silently falling back to stub or constructing a broken client.
- `FABRIC_GATEWAY_TIMEOUT_SECONDS` — **new**, default `5.0`.
- `FABRIC_CHANNEL_NAME` / `FABRIC_CHAINCODE_NAME` — unchanged fields, confirmed and documented as still unused by the backend (owned by the adapter's own `.env`).

`BLOCKCHAIN_BACKEND` defaults to `"stub"` — confirmed by dedicated test (13.6, item 9) that this is unaffected by Phase 5C's changes.

### 13.6 Tests added (`backend/tests/test_fabric_blockchain_service.py`, 29 tests, all `httpx.MockTransport`-based)

1. `register_paper` success — real transaction ID from the (mocked) adapter is returned unmodified.
2. `register_paper` never sends `release_timestamp` in the request body (explicit key-set assertion).
3. `register_paper` with missing `metadata` fields → `ValidationFailedException`, **and** confirms zero HTTP calls were made.
4. `get_paper_metadata` success — asserts `release_timestamp is None`, `authorized_centre_references == []`, `status == "registered"`.
5. `get_paper_metadata` on a Fabric 404 → returns `None` (not an exception).
6. `verify_paper_hash` success, both `match=True` and `match=False` outcomes (parametrized).
7. `verify_paper_hash` against `StubBlockchainService` → `UnsupportedOperationException` (confirms the new base-class default, not just the Fabric override).
8. `record_audit_event` success — asserts the generated `event_id` is a well-formed UUID and the returned `transaction_id` is the adapter's real value.
9. `record_audit_event` with `actor_id=None, paper_id=None` → sent as `""` (chaincode-compatible), not `"None"` or omitted.
10. Gateway `404` → `NotFoundException`; `409` → `ConflictException`; `400` → `ValidationFailedException`; `500`/`502`/`503` → `ServiceUnavailableException` (parametrized).
11. `httpx.TimeoutException` → `ServiceUnavailableException`.
12. `httpx.ConnectError` → `ServiceUnavailableException`.
13. Non-JSON `200` response body → `ServiceUnavailableException` (invalid-response handling).
14. All 6 unsupported operations (parametrized) → `UnsupportedOperationException`, **and** each test asserts zero HTTP calls were made (`assert calls == []`) — i.e. explicitly confirms no silent Stub-like fabricated success and no wasted/misleading network call.
15. Factory selects `FabricBlockchainService` when `BLOCKCHAIN_BACKEND=fabric` + `FABRIC_GATEWAY_ENDPOINT` set (via `monkeypatch`, with explicit `get_settings.cache_clear()`/`get_blockchain_service.cache_clear()` before **and** after, restoring and re-asserting the stub default afterward so this test cannot leak state into any other test in the suite regardless of run order).
16. Factory raises `RuntimeError` naming `FABRIC_GATEWAY_ENDPOINT` when `BLOCKCHAIN_BACKEND=fabric` but the endpoint is empty.
17. Default backend (no env override at all) is `StubBlockchainService` — explicit regression guard for "Fabric must never become the default."
18. Transaction-ID-preservation regression guard: asserts a deliberately non-UUID-shaped adapter transaction ID (`"not-a-uuid-just-what-fabric-happened-to-return-123"`) is returned byte-for-byte, which would fail if the implementation ever generated its own ID instead of using the adapter's.

Order-independence was explicitly verified: the full suite was run with `test_fabric_blockchain_service.py` both last (alphabetical default) and first — **80/80 either way**, confirming the `lru_cache` restore/clear pattern in tests 15–16 does not leak into `test_paper_api.py`/`test_time_lock.py`'s fixtures (which construct a real `TestClient` against the real app and therefore depend on `get_blockchain_service()` still resolving to the stub).

### 13.7 Exact test results (this session, genuinely run)

```
# New file alone:
$ python3 -m pytest -q tests/test_fabric_blockchain_service.py
29 passed, 4 warnings in 0.08s

# Full backend suite (excludes test_phase2_manual.py — a documented
# live-server + live-PostgreSQL manual script, not a pytest suite;
# same exclusion Phase 5A/5B reports used):
$ python3 -m pytest -q --ignore=tests/test_phase2_manual.py
80 passed, 4 warnings in 55.13s

# Re-run with test_fabric_blockchain_service.py FIRST (order-independence check):
$ python3 -m pytest -q tests/test_fabric_blockchain_service.py tests/test_paper_api.py \
      tests/test_time_lock.py tests/test_crypto_service.py tests/test_storage_service.py
80 passed, 4 warnings in 55.07s

# Gateway adapter unit tests (unchanged this session, re-confirmed):
$ npx jest tests/unit
Tests: 13 passed, 13 total
```

80 = 51 pre-existing (unchanged, all still pass — genuine regression check, not assumed) + 29 new. The 4 warnings are pre-existing `DeprecationWarning`s (`passlib`'s `crypt` import, FastAPI's `on_event`) unrelated to this session's work — present before Phase 5C too.

### 13.8 Live Fabric verification: NOT performed this session

No Docker is available in this sandbox (confirmed: `which docker` → not found), so the Phase 5A Fabric network could not be started, and no crypto material (`generate-crypto.sh` output) exists here. **No claim of live Fabric verification is made.**

### 13.9 What WAS genuinely verified beyond mocks: real (non-mocked) adapter, Fabric intentionally absent

To validate more than the mocked unit tests, the actual Phase 5B adapter was built (`npm run build`, real `tsc` compile — succeeded) and run for real (`node dist/server.js`, no `.env` present, matching this sandbox's genuine state) within a single continuous shell session (the same "background-process lifetime across tool-call boundaries" constraint Phase 5A/5B's own Section 11/12 already documented applies here too):

```
$ curl -s http://127.0.0.1:8081/health
{"status":"ok","service":"fabric-gateway-adapter","fabric_connected":false}

$ python3 -c "... FabricBlockchainService(base_url='http://127.0.0.1:8081').verify_paper_hash(...) ..."
OK: real (non-mocked) adapter process, Fabric itself not configured/reachable here ->
    FabricBlockchainService correctly raised ServiceUnavailableException:
    Fabric Gateway Adapter returned an unexpected error (HTTP 503): Fabric adapter is not correctly configured.

$ curl -s http://127.0.0.1:8081/health   # adapter still healthy afterward, did not crash
{"status":"ok","service":"fabric-gateway-adapter","fabric_connected":false}
```

Adapter-side log for that request: `Error: Missing required environment variable: FABRIC_MSP_ID` — exactly the expected `CONFIGURATION_ERROR` → HTTP 503 path from `server.ts`'s `classifyError()`, and `FabricBlockchainService` correctly mapped that real HTTP 503 to `ServiceUnavailableException`.

**This confirms real, live, process-to-process HTTP/JSON wire compatibility between `FabricBlockchainService` (Python/httpx) and the actual Phase 5B adapter (Node/Express) — it does NOT confirm Fabric connectivity itself**, since Fabric was never reachable here (no network, no crypto material). This distinction is deliberate and should not be conflated with "live Fabric verification" (13.8).

### 13.10 Security considerations

- No Fabric private key, certificate, wallet path, or gateway credential is read, held, or transmitted by `FabricBlockchainService` or by `backend/` at all — all of that stays inside the Node adapter process (unchanged from Phase 5B), confirmed by inspection: `fabric_blockchain_service.py` contains no reference to any credential/certificate/key path.
- No question-paper PDF, AES key, password, OTP, or JWT is sent to Fabric by any method in this file (unaffected by this phase; unchanged from the existing architecture).
- HTTP error responses from the adapter are parsed and re-raised as typed `AppException` subclasses; the adapter's own `classifyError()` (Phase 5B, unmodified) already guarantees no stack trace or key material ever appears in those response bodies (verified by Phase 5B's own dedicated test, re-confirmed unchanged in 13.7's `npx jest` run) — this phase does not add a second place where such a leak could occur.
- `FABRIC_GATEWAY_ENDPOINT` is read from configuration only (never hardcoded); `get_blockchain_service()` fails loudly (`RuntimeError`) rather than silently defaulting to an empty/broken endpoint.

### 13.11 Git status

```
$ git status
```
(reported verbatim in the final chat response for this session, together with the created commit hash — see final report; not duplicated here to avoid this file drifting out of sync with the actual commit).

### 13.12 Known limitations after Phase 5C

1. **6, not 5, ABC methods are unsupported for Fabric** — see 13.1; a real correction to the task brief's own arithmetic, not a new gap introduced this session.
2. **`get_paper_metadata`'s `release_timestamp`/`authorized_centre_references` are structurally absent for Fabric-backed records** (always `None`/`[]`) — by design, documented in three places (dataclass docstring, method docstring, this section), not a bug to "fix" without first deciding whether the chaincode itself should be extended (a chaincode-scope decision, out of Phase 5C).
3. **`record_audit_event`'s generated `event_id` is not correlated with PostgreSQL's `audit_events.event_id`** — see 13.4. A future phase could thread a shared ID through if cross-store correlation becomes a real requirement; not attempted here (would require changing `audit_service.py`'s call site, out of this phase's stated scope).
4. **The two Phase-5-readiness open decisions (Section 10) remain open** — `paper_service.register_paper()` still does not call the blockchain abstraction at all (with either backend); this was deliberately not changed this session (see Section 7).
5. **No live Fabric verification** — see 13.8. The real-adapter check in 13.9 is real but Fabric-absent; it is not a substitute for running the actual Phase 5A network end-to-end through this new code path.
6. **No integration test against a live adapter is part of the committed test suite** — 13.9's check was exploratory/manual (matching the "if a live Fabric network is available... run the appropriate integration tests; if unavailable, clearly report" instruction), not added as `tests/integration/` because there is nothing here for it to run against reliably (no persistent adapter process across tool-call boundaries in this sandbox). A `tests/integration/test_fabric_blockchain_service_live.py` that spins up the real adapter (crypto material + Fabric network permitting) would be a reasonable Phase 5D-or-later addition on a persistent machine.

### 13.13 Decisions made this session (cumulative log entry — see also Section 8)

- **Phase 5C:**
  - Corrected the 9→4→5 unsupported-operation arithmetic to 9→3(+1 non-ABC)→6, with full reasoning (13.1) — flagged rather than silently reproduced, per this project's own continuity-protocol rule that source code outranks a prior prompt's assumptions.
  - `verify_paper_hash` added as a new, concrete, non-abstract, opt-in method on `BlockchainService` (default raises `UnsupportedOperationException`) rather than repurposing `record_integrity_result`'s mismatched signature or adding an isinstance-check escape hatch in callers.
  - `PaperMetadataRecord.release_timestamp` retyped to `datetime | None` — confirmed safe (zero existing callers) before making the change.
  - `release_timestamp` is accepted by `FabricBlockchainService.register_paper()` (to satisfy the shared ABC signature) but deliberately never transmitted to Fabric, since the deployed chaincode has no field for it.
  - `record_audit_event`'s missing `event_id` parameter is filled with a freshly generated `uuid.uuid4()` per call, documented as uncorrelated with PostgreSQL's own event ID.
  - New `UnsupportedOperationException` (HTTP 501) added to the existing `AppException` hierarchy, matching its established style.
  - `paper_service.py` / `audit_service.py` were deliberately left untouched — the two Section 10 open decisions were not acted on, per this phase's explicit "do not silently add functionality that belongs to later phases" instruction.

### 13.14 Pending work / exact next step

Confirm with the project owner:
1. Whether to wire `paper_service.register_paper()` to actually call `get_blockchain_service().register_paper(...)` (Section 7 / 10 decision #1, still open).
2. Whether `Paper` should gain a `ledger_tx_reference` column so `PaperRegisterResponse.ledger_tx_reference` can stop being permanently `None` (Section 10 decision #2, still open).
3. Whether the chaincode itself should eventually be extended to cover any of the 6 currently-unsupported operations (a Phase 5A/chaincode-scope decision, not a Phase 5C/backend-wiring one).

**Per the brief, stopping here — not proceeding to Phase 5D, Security Hardening, or Phase 6 automatically.**

## 14. PHASE 5D — Wire Paper Registration to the Blockchain Abstraction — COMPLETE

Date: 2026-09-24. Resolves both open decisions from Sections 10 and 13.14: `paper_service.register_paper()` now performs a best-effort blockchain (Hyperledger Fabric, or Stub under the default config) ledger write, and `Paper` gained a `ledger_tx_reference` column to durably record the result. `verify_paper_hash()` was explicitly NOT wired into `retrieve_paper()` this phase — deferred by the project owner's own decision (see 14.5).

### 14.1 Pre-implementation inspection (this session)

PROJECT_STATE.md (Phase 5C section) and the actual source code were re-read in full before any change was made, per the continuity rule. Independently verified, in a clean environment, before touching anything:
- Fresh `pip install -r requirements.txt` + `pytest -q --ignore=tests/test_phase2_manual.py` → **80 passed** (matches the checkpoint's own claim, not copy-pasted).
- `paper_service.py` confirmed to have **zero** calls to `get_blockchain_service()`/`blockchain_service` prior to this phase.
- `Paper` model confirmed to have **no** `ledger_tx_reference` column prior to this phase; `PaperRegisterResponse.ledger_tx_reference` confirmed to exist in the schema but always be `None` in the router.
- Chaincode (`paperContract.ts`) confirmed to have exactly 4 functions; Gateway Adapter (`server.ts`) confirmed to have exactly 4 Fabric routes + `/health` — both unchanged in this phase.
- No `.git` directory existed in the checkpoint (confirmed, not assumed).
- No Docker available in this sandbox → live Fabric network verification is (as in Phase 5C) not possible here.

The full inspection report (sections A–K) was presented to and approved by the project owner before any code was written. Decisions received:
1. **YES** — wire `register_paper()` to the real blockchain backend.
2. **YES** — add `papers.ledger_tx_reference` and persist the returned transaction ID.
3. **NO** — do not wire `verify_paper_hash()` into `retrieve_paper()` this phase (deferred).

### 14.2 Files created

| File | Purpose |
|---|---|
| `backend/scripts/add_phase5d_columns.py` | Idempotent (`ADD COLUMN IF NOT EXISTS`) PostgreSQL migration helper for `papers.ledger_tx_reference`, following the exact convention of `scripts/add_phase3_columns.py`. Correct invocation is `python -m scripts.add_phase5d_columns` (documented and verified working in this session — see 14.6; the direct-script form used in `add_phase3_columns.py`'s own docstring does not actually work from a fresh shell without `backend/` separately on `PYTHONPATH`, a pre-existing inaccuracy in that older file's docstring, flagged here rather than silently fixed, since `add_phase3_columns.py` itself was not touched — out of this phase's scope). |
| `backend/tests/test_paper_blockchain_integration.py` | 7 new focused tests for the Phase 5D orchestration logic in `paper_service.register_paper()` (see 14.7). |

### 14.3 Files modified

| File | Change |
|---|---|
| `backend/app/models/paper.py` | Added `ledger_tx_reference: Mapped[str \| None] = mapped_column(String(255), nullable=True)`, with an in-code comment explaining exactly when it is/isn't populated. |
| `backend/app/services/paper_service.py` | Added `import logging` + module-level `logger`; added `from app.services.blockchain_service import get_blockchain_service`; in `register_paper()`, after the existing successful PostgreSQL commit and BEFORE the existing `PAPER_REGISTRATION_COMPLETED` audit event, added a best-effort call to `get_blockchain_service().register_paper(paper_id, sha256_hash, release_timestamp, metadata={admin_id, subject, encryption_algorithm})`. On success, `paper.ledger_tx_reference` is set and a second `db.commit()` persists it (with its own inner try/except + `db.rollback()` so a failure to persist the tx-ref locally cannot invalidate the already-committed paper row). On any exception (from the Fabric/Stub call itself), a `logger.warning(...)` is emitted (paper_id only — no secrets, no key material, no PDF bytes) and `ledger_tx_reference` remains `None`. Module docstring and function docstring updated to describe the new behavior and its failure-tolerance reasoning explicitly. |
| `backend/app/api/v1/papers.py` | `PaperRegisterResponse.ledger_tx_reference` is now populated from `paper.ledger_tx_reference` (the real DB value) instead of being permanently absent/`None`. Docstring updated. |

### 14.4 Files deleted

None.

### 14.5 Database / schema changes

One nullable column: `papers.ledger_tx_reference VARCHAR(255) NULL`. No new table. Applied automatically for fresh databases via `Base.metadata.create_all()` (`scripts/init_db.py`); for an existing (pre-Phase-5D) database, `python -m scripts.add_phase5d_columns` must be run once.

**Verified this session, on real PostgreSQL 16 (installed via apt in this sandbox):**
- Fresh DB via `init_db.py` → column present automatically. Confirmed via `\d papers`.
- Simulated a pre-Phase-5D database by manually `ALTER TABLE papers DROP COLUMN ledger_tx_reference` on an already-initialized DB, confirmed the column was genuinely absent (`\d papers` grep returned nothing), then ran `python -m scripts.add_phase5d_columns` — column reappeared, confirmed via `\d papers`. Ran the script a **second** time immediately after → no error (true idempotency, not just "probably fine because `IF NOT EXISTS`").

### 14.6 API changes

`POST /api/v1/papers/register` — response body unchanged in shape (`ledger_tx_reference` field already existed in the schema since Phase 5A/5C-era scaffolding), but its value is now real: the actual Hyperledger Fabric (or Stub) transaction/reference ID on success, or `null` if the blockchain write failed or was unreachable. No other endpoint changed. No request body change.

### 14.7 Blockchain / chaincode changes

**None.** No chaincode file was modified (verified via `find blockchain -newer <session-start-marker>` → empty result). No Gateway Adapter route was modified. This phase is entirely backend-orchestration wiring using the chaincode/adapter/`FabricBlockchainService` that already existed and was already fully tested as of Phase 5C. `RegisterPaper`'s existing input contract (`paper_id`, `sha256_hash`, `release_timestamp`, `admin_id`, `subject`, `encryption_algorithm`) already covered everything `register_paper()` needed to send — confirmed before writing any code, per the task's explicit instruction not to change chaincode without proving it necessary.

### 14.8 Authentication / RBAC impact

None. Not touched. The full Phase 2 manual regression script (`tests/test_phase2_manual.py`, 28 checks) was re-run **live**, against a real running `uvicorn` server + real PostgreSQL 16, after the Phase 5D changes — **28/28 PASSED**, confirming zero regression in login, OTP, JWT, RBAC, session revocation, or security-event logging.

### 14.9 Encryption / hashing impact

None. AES-256-GCM and SHA-256 logic in `crypto_service.py` was not touched. `paper.sha256_hash` (already computed by the existing pipeline) is the exact value forwarded to the blockchain call — no new hash is computed, no hash is recomputed differently.

### 14.10 Storage impact

None. `storage_service.py` was not touched. The encrypted file is written to off-chain storage exactly as before, before the new blockchain step runs.

### 14.11 Time-lock impact

None. `retrieve_paper()` (where time-lock enforcement lives, Phase 4) was **not modified at all** in this phase — confirmed by design (decision #3: `verify_paper_hash()` deferred) and by inspection (no diff to that function).

### 14.12 Audit-log impact

None to the audit-log mechanism itself (`audit_service.py` untouched). The existing `PAPER_REGISTRATION_COMPLETED` audit event (which itself already goes through `get_blockchain_service().record_audit_event(...)`, unchanged since Phase 3) still fires exactly as before, immediately after the new best-effort ledger-registration step.

### 14.13 Tests executed and exact results (this session)

**Automated suite (SQLite, the project's default test path):**
```
python3 -m pytest -q --ignore=tests/test_phase2_manual.py
→ 87 passed, 4 warnings in ~55-65s
```
(80 pre-existing + 7 new in `test_paper_blockchain_integration.py`.) Re-run with the new test file ordered first (`test_paper_blockchain_integration.py test_paper_api.py test_time_lock.py test_fabric_blockchain_service.py test_crypto_service.py test_storage_service.py`) → still **87 passed** (order-independence check, matching the Phase 5C convention).

**Automated suite against real PostgreSQL 16** (installed via `apt-get install postgresql postgresql-contrib` in this sandbox; a genuinely separate DB engine from the SQLite default, not just re-running the same thing):
```
DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/qpaper_test \
python3 -m pytest -q --ignore=tests/test_phase2_manual.py
→ 87 passed, 4 warnings in ~55s
```

**New Phase 5D tests, 7 total, all in `test_paper_blockchain_integration.py`** (SQLite path):
1. `test_stub_backend_registration_succeeds_and_populates_ledger_tx_reference` — **PASS**. Uses the REAL, unmocked `StubBlockchainService`.
2. `test_fabric_backend_successful_registration_persists_transaction_id` — **PASS**. Monkeypatches `get_blockchain_service` with a fake that returns a fixed tx id; asserts persistence + response exposure + exact non-secret payload sent.
3. `test_fabric_backend_unavailable_does_not_fail_registration` — **PASS**. Fake raises `ServiceUnavailableException`; asserts 201 (not 500/503), `ledger_tx_reference is None`, paper row fully intact, call attempted exactly once (no retry loop).
4. `test_fabric_backend_unavailable_via_generic_exception_still_does_not_fail_registration` — **PASS**. Fake raises a bare `RuntimeError` (not an `AppException`), confirming the broad `except Exception` is intentional and correct, not accidentally narrow.
5. `test_two_registrations_get_distinct_paper_ids_and_distinct_ledger_references` — **PASS**. Two real (unmocked) Stub registrations in a row; confirms no accidental `paper_id` reuse/duplicate-suppression was introduced.
6. `test_registration_response_schema_still_only_exposes_safe_fields` — **PASS**. Companion to the existing Phase-4-era schema test, this time with a real, non-`None` `ledger_tx_reference`.
7. `test_fabric_failure_is_logged_without_leaking_secrets` — **PASS**. Asserts the warning log line exists, mentions the failure, and contains no key/DEK/nonce/PDF material.

**Migration script (`scripts/add_phase5d_columns.py`), real PostgreSQL 16:**
- Fresh-DB path (column already present via `create_all`) — confirmed present, no script run needed.
- Simulated-pre-Phase-5D path — column manually dropped, script run once → column added (confirmed via `\d papers`), script run a second time → no error (idempotency genuinely verified, not assumed).

**Live, manual, end-to-end verification against a real running server (NOT a live Fabric network — see 14.14 for that distinction):**
- Started real PostgreSQL 16 + real `uvicorn app.main:app` + seeded `admin1`/`centre1`/`"Test Centre A"` via `scripts.create_user` and a one-off seeding snippet.
- Ran `tests/test_phase2_manual.py` (the project's own existing 28-check live regression script, unrelated to Phase 5D's own feature but a strong regression gate for auth/RBAC/JWT/OTP/logout) live against that server → **28/28 PASSED**.
- Separately, sent a real `POST /api/v1/papers/register` HTTP request (via `httpx`, real multipart PDF upload, real JWT obtained through the real login+OTP flow) to that same live server → **HTTP 201**, response contained `"ledger_tx_reference": "stub-tx-000005"` (a real, incrementing, non-fabricated value from the real `StubBlockchainService`'s in-memory counter — not synthesized for this report). Confirmed the identical value was durably persisted by querying PostgreSQL directly: `SELECT paper_id, subject, ledger_tx_reference, status FROM papers` returned the matching row with `status='registered'`.

**Static checks:**
```
python3 -m py_compile app/models/paper.py app/services/paper_service.py \
    app/api/v1/papers.py scripts/add_phase5d_columns.py \
    tests/test_paper_blockchain_integration.py
→ no errors
python3 -m py_compile $(find app tests scripts -name "*.py")   # whole backend
→ no errors
```
No linter (flake8/ruff/pylint) is configured anywhere in this repository (confirmed by absence of `.flake8`/`ruff.toml`/`pyproject.toml [tool.ruff]`/`.pylintrc`) — `py_compile` is the full extent of available static checking, same as every prior phase.

### 14.14 What was NOT verified (honesty section, matching Phase 5C's own discipline)

- **No live Fabric network** was started or exercised this session (no Docker in this sandbox — confirmed by `which docker` returning nothing). Everything described in 14.13 as "live"/"manual" used the real FastAPI app + real PostgreSQL + the real `StubBlockchainService` (the default backend) — it is **not** live Fabric verification, and this report does not claim it is.
- `FabricBlockchainService.register_paper()`'s actual HTTP call to a real Gateway Adapter process, and that adapter's actual gRPC call to a real Fabric peer, were **not** exercised in this phase — that exact HTTP-layer path was already exhaustively tested with `httpx.MockTransport` in Phase 5C's 29 tests, which this phase deliberately did not duplicate (see the module docstring of `test_paper_blockchain_integration.py`). This phase's own tests prove `paper_service.py`'s orchestration logic is correct for both success and failure of *whatever* `get_blockchain_service()` returns, which is the layer that changed.
- No load/performance testing was performed (out of scope, consistent with every prior phase).

### 14.15 Decisions made this session (cumulative log entry — see also Section 8, 13.13)

- **Phase 5D:**
  - `register_paper()`'s blockchain call goes through the SAME `get_blockchain_service()` abstraction used everywhere else (not Fabric-specific code) — under the default `BLOCKCHAIN_BACKEND=stub` it legitimately calls the real `StubBlockchainService`, matching the precedent already set by `audit_service.record_audit_event()` (which has always done this, unconditionally, since Phase 3/5C). This was a design choice, not explicitly dictated by the brief, and is recorded here for transparency: it means `ledger_tx_reference` is populated under the Stub backend too, not only under Fabric. No existing test asserted otherwise (confirmed by inspection before making the change), and it is the more architecturally consistent option.
  - The blockchain-registration step is placed AFTER the existing PostgreSQL commit (not inside the same transaction) and is wrapped in its own nested try/except with `db.rollback()` on the (separate) failure to persist `ledger_tx_reference` — this two-layer failure handling was a deliberate design choice to guarantee the original paper row is never put at risk by anything in the new code path, even a failure that occurs while merely trying to record the tx reference.
  - `verify_paper_hash()` remains unwired into `retrieve_paper()`, per the project owner's explicit decision #3 — not attempted, not partially done.
  - `add_phase3_columns.py`'s docstring usage instructions were found to be inaccurate (direct-script invocation doesn't actually work) during verification of the new Phase 5D migration script; documented in the new script's own docstring rather than silently editing the older file (out of this phase's scope).

### 14.16 Known limitations after Phase 5D

1. Everything listed in 13.12 (Phase 5C's known limitations) still applies unchanged — none of it was in this phase's scope.
2. `verify_paper_hash()` is still unused anywhere in the application (deferred by explicit decision, not an oversight).
3. `authorize_centre`, `revoke_centre`, `record_access_attempt`, `record_integrity_result`, `record_release`, `record_exam_violation` remain unsupported for the Fabric backend (chaincode-scope, unchanged, out of this phase).
4. The blockchain-registration step happens as a second, separate `db.commit()` after the primary paper-registration commit — this is correct and safe (rollback-protected, best-effort by design) but means a `Paper` row can very briefly exist with `ledger_tx_reference IS NULL` even under normal, fully-successful operation (the moment between the two commits). This is expected, not a bug, and is documented in the model's own in-code comment.
5. No live Fabric network verification was possible in this sandbox (same constraint as every Phase-5 session so far — no Docker).
6. This sandbox's PostgreSQL/uvicorn background processes did not persist reliably across separate tool-call boundaries during this session (they had to be started and used within a single chained shell invocation each time) — an environment quirk of this sandbox, not a project defect; noted here only for anyone trying to reproduce the live verification steps in 14.13.

### 14.17 Pending work / exact next recommended step

No open decisions remain from Phase 5D itself. Recommended next steps, in order of what the project's own document hierarchy (LLD Section 26 / this file's Section 10) still lists as unresolved:

1. **A deliberate, separately-approved decision on `verify_paper_hash()`** — should `retrieve_paper()` call it as an additional ledger-backed integrity gate alongside the existing AES-GCM tag + SHA-256 checks? This changes retrieval's failure modes (a third, network-dependent check) and deserves its own explicit sign-off, exactly as decision #3 of this phase deferred it.
2. **Whether any of the 6 Fabric-unsupported `BlockchainService` methods should be added to the chaincode** — a Phase 5A/chaincode-scope decision, not a backend-wiring one; only relevant if the project owner wants the ledger to also record authorization/access-attempt/integrity-result/release/violation events (currently only registration + generic audit events reach Fabric).
3. Per the original brief: **do not proceed to Phase 6 (React frontend) automatically** — this phase stops here, as instructed.

---

## 15. PHASE 5E — Blockchain-Backed Paper Integrity Verification (Retrieval)

### 15.1 Objective

Phase 5D deliberately left `verify_paper_hash()` unwired from `retrieve_paper()`
(see 14.17 item 1). Phase 5E's objective was to design, get explicit
sign-off on, and then implement that wiring: an additional,
independent, ledger-backed integrity check at **retrieval** time,
without weakening or replacing anything the local security controls
(AES-256-GCM, SHA-256, time-lock, JWT/OTP, RBAC, audit logging)
already do.

An inspection-first design report was produced and reviewed by the
project owner *before any code was touched* (per this phase's explicit
process requirement). Three decisions required explicit confirmation
before implementation began; all three were confirmed by the project
owner and are recorded verbatim in 15.2 below.

### 15.2 Confirmed decisions (recorded for permanent audit trail)

1. **Fabric-unavailable policy**: `FABRIC_VERIFICATION_MODE=best_effort|strict`,
   default `best_effort`. Under `best_effort`, a Fabric/adapter that
   cannot be reached (or a paper with no ledger record at all) does
   **not** block retrieval — the two already-passed local checks are
   sufficient, and a `BLOCKCHAIN_VERIFICATION_UNAVAILABLE`/`DEGRADED`
   audit event is recorded. Under `strict`, the same condition instead
   rejects with 503. **In both modes**, an explicit `match=False` from
   Fabric is a genuine, positive integrity disagreement and **always**
   fails closed with 409 — never treated as "unavailable", never
   swallowed.
2. **Event names**: `LEDGER_HASH_MISMATCH` (security event, severity
   `HIGH`) for an explicit ledger disagreement, paired with the
   existing `TAMPER_DETECTED`/`REJECTED` audit event (reused, not
   duplicated); `BLOCKCHAIN_VERIFICATION_UNAVAILABLE` (audit event,
   outcome `DEGRADED` under best_effort / `FAILURE` under strict) when
   a comparison could not be obtained at all. No "verification started"
   or "local hash matched" events were added (would be noise, not
   signal — existing `PAPER_RELEASED`/`SUCCESS` already implies both
   local checks passed).
3. **Configuration**: `FABRIC_VERIFICATION_MODE` added to
   `app/config.py` with a `field_validator` that rejects any value
   outside `{"best_effort", "strict"}` at Settings-construction time
   (app startup), documented in `.env.example`.

### 15.3 Final architecture / exact retrieval flow

`retrieve_paper()` (`backend/app/services/paper_service.py`) now
performs, in this exact order:

```
1. 404 check                                          [unchanged, Phase 4]
2. Exam-centre authorization check                     [unchanged, Phase 4]
3. Time-lock check                                     [unchanged, Phase 4]
4. audit PAPER_ACCESS_ATTEMPT / PERMITTED               [unchanged, Phase 4]
5. Retrieve ciphertext from off-chain storage           [unchanged, Phase 4]
6. AES-256-GCM decrypt                                  [unchanged, Phase 4]
     -> InvalidTag: existing tamper rejection (409)     (1st local gate)
7. SHA-256(plaintext) vs paper.sha256_hash              [unchanged, Phase 4]
     -> mismatch: existing tamper rejection (409)       (2nd local gate)
8. NEW (Phase 5E): _verify_against_blockchain_ledger()  (3rd, independent gate)
     a. if not blockchain.supports_ledger_verification:
          -> skip entirely, no call made, no event      (Stub backend today)
     b. else: match = blockchain.verify_paper_hash(paper_id, recomputed_hash)
          - UnsupportedOperationException (defense-in-depth only)
                -> skip, same as (a)
          - ServiceUnavailableException / NotFoundException
                -> "verification could not be obtained":
                   best_effort: record BLOCKCHAIN_VERIFICATION_UNAVAILABLE/
                                DEGRADED, continue
                   strict:      record BLOCKCHAIN_VERIFICATION_UNAVAILABLE/
                                FAILURE, raise 503
          - match is False (genuine disagreement, ALWAYS fails closed,
            both modes):
                -> record LEDGER_HASH_MISMATCH (security, HIGH) +
                   TAMPER_DETECTED/REJECTED (audit), raise 409
          - match is True: fall through silently
9. audit PAPER_RELEASED / SUCCESS                       [unchanged, Phase 4]
10. return plaintext                                    [unchanged, Phase 4]
```

The new step is implemented as a private helper,
`_verify_against_blockchain_ledger(db, current_user, paper, recomputed_hash)`,
called after step 7 and before step 9. Its docstring in the source is
the authoritative reference for the exact branch-by-branch reasoning
(deliberately three separate, non-overlapping branches — never one
broad `except Exception: continue`, per the explicit "do not swallow
match=False" requirement).

### 15.4 Hash semantics (unchanged — explicitly verified, not assumed)

The hash sent to Fabric for comparison is the **exact same**
`SHA256(plaintext)` value the existing local check (step 7 above)
already computed — no second, incompatible hash definition was
introduced, and the ciphertext-vs-plaintext hashing deviation from LLD
Section 13 (documented back in Phase 4) is **not** revisited by this
phase.

### 15.5 AES-256-GCM's role (unchanged)

Still the **first** tamper-detection gate, via the GCM authentication
tag, verified as an intrinsic part of decryption — before any plaintext
exists. Phase 5E's new blockchain check runs strictly **after** this
gate has already passed (confirmed by a dedicated test — see 15.9).

### 15.6 Blockchain verification's role (new, Phase 5E)

A **third, independent** integrity gate. Its specific, honest value
proposition (documented in the module docstring and worth restating
here for faculty/viva purposes): the two existing local checks both
ultimately trust PostgreSQL's own `papers.sha256_hash` column as the
reference value — an attacker who compromises PostgreSQL directly
(not the file, not the network) could edit both the stored file and
that column consistently, and both local checks would still pass.
Hyperledger Fabric's independently-stored hash is the only thing in
this architecture external to PostgreSQL; calling `verify_paper_hash()`
**after** local checks already pass closes that specific gap. It is
additive, never a replacement — this was a hard, explicit design
requirement and is enforced structurally (the local checks run first,
unconditionally, regardless of blockchain backend or outcome).

### 15.7 Backward compatibility — the capability-flag design decision

**Important refinement made during implementation, not anticipated in
full in the pre-implementation design report**: an early implementation
using try/except `UnsupportedOperationException` around the
`verify_paper_hash()` call technically still *called* the method on the
Stub backend (immediately catching the exception) — this satisfied "the
client never sees a 501" but did **not** satisfy the stronger, explicitly
required test assertion "Stub `verify_paper_hash()` is never called" (a
literal call-count-zero guarantee), which a dedicated spy-based test
caught during this session (see 15.9).

Resolved by adding an explicit **capability flag** to the
`BlockchainService` abstraction rather than call-and-catch:

- `BlockchainService.supports_ledger_verification: bool = False` (class
  attribute, `app/services/blockchain_service.py`) — the default for
  any backend that doesn't override it, including `StubBlockchainService`.
- `FabricBlockchainService.supports_ledger_verification: bool = True`
  (`app/services/fabric_blockchain_service.py`) — the only concrete
  backend that actually implements ledger verification against a real
  chaincode query.
- `paper_service._verify_against_blockchain_ledger()` checks this flag
  **before** calling `verify_paper_hash()` at all. Under
  `BLOCKCHAIN_BACKEND=stub`, the method is **never invoked** — not
  "invoked and its exception is caught every time."

This is a small, additive, backward-compatible change (a class
attribute with a safe default) to two files not originally listed as
needing modification in the pre-implementation design report (Section
I/J of that report said "no changes needed to blockchain_service.py's
ABC") — flagged here explicitly per the project's own discipline of
never silently deviating from a stated plan. The change is genuinely
minimal and does not alter any existing method's signature or behavior.

### 15.8 Files created

| File | Purpose |
|---|---|
| `backend/tests/test_paper_retrieval_blockchain_verification.py` | 20 focused Phase 5E tests — see 15.9. |

### 15.9 Files modified

| File | Change |
|---|---|
| `backend/app/config.py` | Added `FABRIC_VERIFICATION_MODE: str = Field(default="best_effort")` with a `field_validator` rejecting anything outside `{"best_effort", "strict"}` at Settings-construction time. Only consulted when a backend both supports and cannot complete ledger verification (see 15.3 step 8b). |
| `backend/.env.example` | Documented `FABRIC_VERIFICATION_MODE`, its default, its allowed values, and that it has no effect under `BLOCKCHAIN_BACKEND=stub`. |
| `backend/app/services/blockchain_service.py` | Added `supports_ledger_verification: bool = False` class attribute to the `BlockchainService` ABC, with a docstring explaining its purpose (capability check, not call-and-catch — see 15.7). No existing method signature changed. |
| `backend/app/services/fabric_blockchain_service.py` | Added `supports_ledger_verification: bool = True` override. No existing method changed. |
| `backend/app/services/paper_service.py` | Added `UnsupportedOperationException` to imports. Updated module docstring (Phase 5E section) and `retrieve_paper()`'s docstring (new step 5 in its numbered list). Added new private helper `_verify_against_blockchain_ledger()` (~90 lines, extensively documented — see 15.3), called from `retrieve_paper()` between the existing local SHA-256 check and the existing `PAPER_RELEASED` audit event. No existing line of `retrieve_paper()`'s prior logic (steps 1–7, 9–10 in 15.3) was altered — only inserted around. |

### 15.10 Files deleted

None.

### 15.11 Database changes

**None.** `audit_events.event_type` and `security_events.event_type` are
(and were already, since Phase 2/3) plain `String` columns, not enums —
the two new event-type string values (15.2 item 2) required no schema
migration, matching the exact precedent of every prior phase's new
event types.

### 15.12 API changes

**None to any request/response shape.**
`GET /api/v1/papers/{paper_id}/retrieve` keeps its existing signature
and existing 200/403/404/409/503 status codes. Under the default
`BLOCKCHAIN_BACKEND=stub`, external behavior is byte-for-byte unchanged
from before Phase 5E (verified — see 15.9/15.13). Under
`BLOCKCHAIN_BACKEND=fabric`, the only new *observable* behavior is that
409/503 can now also originate from the new third gate, with their own
distinct messages (never confused with the existing local-check 409
message — different exact text).

### 15.13 Blockchain / chaincode / Gateway Adapter changes

**None.** Per the pre-implementation design report's finding (Section
E–H of that report) and per the explicit instruction not to modify the
chaincode or Gateway Adapter unless inspection proved it necessary:
`VerifyPaperHash` (chaincode), `POST /fabric/verify-hash` (Gateway
Adapter), and `FabricBlockchainService.verify_paper_hash()` were all
already fully implemented and already unit-tested (Phase 5B/5C) before
this phase began. Phase 5E only added the **caller** (`paper_service.py`)
that was previously missing. Confirmed via `git diff --stat` (15.16
below) that no file under `blockchain/` changed in this phase.

### 15.14 Authentication / OTP / RBAC / time-lock impact

**None.** All four remain structurally earlier in the request-handling
order than the new blockchain-verification step (15.3, steps 1–4 for
authn/authz/time-lock; JWT/OTP are enforced by the router dependency
before `retrieve_paper()` is even called). Verified by a dedicated test
(`test_time_lock_still_enforced_ahead_of_any_blockchain_check`) that
would fail loudly (via `pytest.fail`) if the blockchain check were ever
reached before the time-lock gate.

### 15.15 Encryption / Hashing / Storage impact

**None to their mechanisms.** AES-256-GCM and SHA-256 remain exactly as
implemented since Phase 4 (see 15.5/15.4). Storage access pattern
(`StorageService`, backend-only) is untouched.

### 15.16 Security considerations (restated from the design report, now implemented as designed)

- Confirmed by a dedicated test (`test_fabric_backend_called_with_exact_paper_id_and_hash_match_true_succeeds`,
  assertion block "15.") that the only two keys ever present in a
  `verify_paper_hash()` call are `paper_id` and `candidate_hash` — no
  PDF bytes, AES key, wrapped DEK, nonce, OTP, JWT, password, or any
  other secret is structurally reachable from that call site (the
  method signature makes it impossible, and the test additionally
  string-searches the call arguments for a forbidden-term list as a
  second, independent check).
- Confirmed by a dedicated test
  (`test_blockchain_unavailable_warning_log_never_leaks_secrets`) that
  the new `logger.warning(...)` call in the unavailable-branch never
  logs the PDF content or any key/nonce material — only `paper_id`,
  the exception's own (already-safe) message, and the configured mode.
- The new network dependency this phase introduces (backend → adapter
  → Fabric, only reachable at all under `BLOCKCHAIN_BACKEND=fabric`)
  is exactly the trade-off analyzed and explicitly approved in the
  pre-implementation design report (Section O of that report) —
  `best_effort` as the default keeps retrieval's availability
  unaffected by Fabric/adapter flakiness, while `strict` is available
  for anyone who wants the stronger (but less demo-resilient)
  guarantee.

### 15.17 Test strategy and results

**20 new Phase 5E tests** added in
`backend/tests/test_paper_retrieval_blockchain_verification.py`,
covering (mapped to the 20 requested items):

1–2. Stub retrieval succeeds unchanged; `verify_paper_hash()` provably
     never called (spy-based, not inference) — this test is what
     surfaced the capability-flag design refinement in 15.7.
3–4. Local SHA-256 success/mismatch paths unaffected; mismatch proven
     to short-circuit before any blockchain call is attempted.
5. AES-GCM tamper detection proven to reject before any blockchain call.
6–7, 15. Fabric backend called with the exact `paper_id` and exact
     recomputed plaintext hash; `match=True` succeeds; only
     `paper_id`/`candidate_hash` ever present in the call.
8–10. `match=False` → 409, `LEDGER_HASH_MISMATCH`/`HIGH` recorded,
     `TAMPER_DETECTED`/`REJECTED` recorded, no `PAPER_RELEASED` event
     exists for that paper; response body never contains the PDF bytes.
11–12. Fabric unavailable + `best_effort` (proven to be the real
     default, not just assumed) → 200, `BLOCKCHAIN_VERIFICATION_UNAVAILABLE`/
     `DEGRADED` recorded, plus a dedicated test for the
     paper-not-registered-on-ledger (`NotFoundException`) case,
     treated identically under best_effort.
13. Fabric unavailable + `strict` → 503, `BLOCKCHAIN_VERIFICATION_UNAVAILABLE`/
     `FAILURE` recorded; a companion test confirms `match=False` still
     returns 409 (not 503) even in strict mode — the "never swallowed"
     requirement holds in both modes.
14. A backend that claims support but still raises
     `UnsupportedOperationException` internally never surfaces a 501
     (defense-in-depth branch, 15.3 step 8b).
16–19. RBAC (Admin cannot call `/retrieve`), time-lock (still enforced
     ahead of the new check, proven via an exploding fake), full
     regression via the existing suite.
20. Registration (`register_paper()`, Phase 5D) proven completely
     untouched by this phase (smoke check).

Plus two tests beyond the requested 20: config validation
(`FABRIC_VERIFICATION_MODE` rejects an invalid value at
Settings-construction) and a log-safety check (15.16).

**Also explicitly required and NOT swallowed**: a dedicated test
(`test_unexpected_exception_type_is_not_swallowed_by_best_effort_policy`)
proves that an exception type *other than* `ServiceUnavailableException`/
`NotFoundException` (a `ValidationFailedException`, standing in for a
genuine bug) propagates as its own distinct error and is never
reinterpreted as "unavailable" — satisfying the explicit "do not catch
every exception and silently continue" instruction structurally, not
just by convention.

**Results, this session, run from a completely clean re-extraction of
the Phase 5D checkpoint** (no prior Phase 5E artifacts existed):

| Suite | Environment | Result |
|---|---|---|
| Full backend suite (`pytest -q --ignore=test_phase2_manual.py`) | SQLite (default, matches every prior phase's fast path) | **107 passed** (87 pre-existing + 20 new), 0 failed |
| Same suite, `--randomly-seed=12345` | SQLite | **107 passed** |
| Same suite, `--randomly-seed=999` | SQLite | **107 passed** (order-independence confirmed across two different seeds) |
| Full backend suite | **Real PostgreSQL 16** (installed this session via `apt-get install postgresql postgresql-contrib`, matching Phase 5D's own precedent) | **107 passed** |
| `python3 -m compileall app tests` | — | Clean, no syntax errors across the whole backend |
| `tests/test_phase2_manual.py` (28-check script) | **Real running `uvicorn` server + real PostgreSQL 16** | **28/28 PASSED** |
| Ad hoc live Phase 5E end-to-end script (register → authorize → retrieve success → tamper → 409), real HTTP, real Postgres, real AES-256-GCM/SHA-256, real (unmocked) `StubBlockchainService` | Real running `uvicorn` server + real PostgreSQL 16 | **7/7 PASSED** |

All of the above were actually executed in this session; none are
inferred or assumed. `pytest-randomly` (used only for the
order-independence check) was `pip install`ed for this session only —
it is **not** added to `requirements.txt` and is not part of the
committed project.

### 15.18 Live Fabric verification

**Not performed.** No Docker is available in this sandbox (same,
unchanged constraint documented in every Phase-5 session's own
PROJECT_STATE.md entry — 13.8, 14.14). No claim of live Fabric,
live Gateway-Adapter-to-Fabric, or live chaincode execution is made
anywhere in this report. Every "Fabric" scenario exercised this session
(match=True, match=False, unavailable) was exercised via a small
in-process fake object implementing exactly the `verify_paper_hash(paper_id,
candidate_hash) -> bool` contract (monkeypatched in for
`get_blockchain_service()`), run through the **real** FastAPI app, real
RBAC, real authentication, and (for the PostgreSQL-tier run) a real
database — this proves `paper_service.py`'s new orchestration logic is
correct for every outcome `get_blockchain_service()` can return, which
is exactly the layer this phase changed. It does **not** prove Fabric
connectivity itself, and this distinction is deliberate (matching the
exact discipline of 14.14 above).

### 15.19 Known limitations after Phase 5E

1. Everything listed in 14.16 (Phase 5D's known limitations) still
   applies unchanged — none of it was in this phase's scope.
2. No live Fabric network verification was possible in this sandbox —
   see 15.18 (same, unchanged constraint as every prior Phase-5 session).
3. The `NotFoundException`-as-"unavailable" design choice (15.3, step
   8b) is a genuine judgment call made during this phase, not something
   explicitly dictated by the confirmed decisions in 15.2 (which spoke
   of "Fabric unavailable", not specifically "paper not found on the
   ledger"). The reasoning (a paper can legitimately have no ledger
   record today, because Phase 5D's own registration-time ledger write
   is itself best-effort — see 14.16 item 4) is documented in the
   `_verify_against_blockchain_ledger()` docstring and here, but this
   is flagged explicitly as a design decision made *during*
   implementation that the project owner has not separately signed off
   on, in case a different treatment is preferred (e.g. treating a
   missing ledger record as its own distinct, stricter case).
4. This sandbox's PostgreSQL/uvicorn background processes still do not
   persist reliably across separate tool-call boundaries (identical to
   the constraint noted in 14.16 item 6) — every live check in this
   phase was run via a single self-contained shell script (start
   server, run checks, stop server) within one tool invocation, not
   across several.
5. `supports_ledger_verification` is a plain class attribute, not
   enforced by the `BlockchainService` ABC's `@abstractmethod`
   machinery — a future backend author could forget to set it. This is
   a minor, low-risk limitation (the base class default of `False` is
   the safe direction to fail in) rather than a defect, but is noted
   for completeness.

### 15.20 Pending work / exact next recommended step

No open decisions remain from Phase 5E itself (all three
pre-implementation decisions in 15.2 were confirmed and implemented
exactly as specified, with the one additive refinement in 15.7
documented above). Recommended next steps, in order:

1. **Project-owner review of the `NotFoundException`-as-"unavailable"
   judgment call** (15.19 item 3) — confirm or override before treating
   it as final.
2. Per the original brief: **do not proceed to Phase 6 (React
   frontend), dashboard work, deployment, QR verification, or any AI
   insider-threat feature** — this phase stops here, as instructed.
3. Whenever a persistent-Docker environment becomes available: run the
   actual Phase 5A Fabric network + Phase 5B adapter + this phase's new
   `retrieve_paper()` path together for the first genuinely live,
   end-to-end blockchain-backed tamper-detection demonstration — this
   remains the single biggest gap between "designed and tested" and
   "demonstrated exactly as marketed," unchanged since Phase 5A.

---

## 16. PHASE 6A — React Frontend Foundation — COMPLETE

### 16.1 Objective

Create the React/TypeScript/Vite frontend **foundation only**: a
working dev server and production build, a centralized API client, an
authentication foundation genuinely compatible with the backend's
actual auth contract, a routing skeleton with protected routes, and
placeholder pages for the Admin Portal / Examination Centre Portal.
Explicitly **not** in scope: the Admin dashboard, the Exam Centre
dashboard, analytics, or any blockchain UI.

### 16.2 Mandatory inspection performed before any code was written

Per the phase's explicit process requirement, the following was read
directly from source (not assumed from documentation) before touching
any file:

- `backend/app/main.py`, `backend/app/config.py`
- `backend/app/api/v1/router.py`, `backend/app/api/v1/auth.py`
- `backend/app/schemas/auth.py`
- `backend/app/api/deps.py`, `backend/app/exceptions/handlers.py`
- `backend/app/models/role.py`
- `backend/.env.example`
- `backend/requirements.txt`
- Full backend test suite (baseline run before any change)
- `git log` / `git status` (clean at Phase 5E checkpoint `0818431`)
- Confirmed **no frontend directory existed** prior to this phase.

No discrepancy was found between `PROJECT_STATE.md`'s description of
the auth flow and the actual backend code — the two agree.

### 16.3 Confirmed backend contract used (nothing invented)

| Endpoint | Method | Request | Response |
|---|---|---|---|
| `/api/v1/auth/login` | POST | `{username, password}` | `{otp_required, pre_auth_token}` |
| `/api/v1/auth/otp/verify` | POST | `{pre_auth_token, otp_code}` | `{access_token, token_type, role}` |
| `/api/v1/auth/logout` | POST (Bearer) | — | `{detail}` |
| `/api/v1/auth/me` | GET (Bearer) | — | `{user_id, username, role, centre_id}` |

- Roles (fixed set, `backend/app/models/role.py`): `Admin`,
  `Examination Centre`, `Auditor`.
- Error shape (all non-2xx responses, `exceptions/handlers.py`):
  `{"error": {"message": string, "status_code": number}}`.
- CORS default origin: `http://localhost:3000` (`backend/.env.example`)
  — this is Vite's default dev port, so **no backend change was
  required**.

Endpoints that exist in the backend but are not consumed by Phase 6A
(papers, admin, exam-session, audit, health) were intentionally **not**
wrapped in `src/api/endpoints.ts` yet — they belong to Phase 6B+ and
will be added only when a page actually needs them.

### 16.4 Frontend technology

React 18 + TypeScript 5 + Vite 5, `react-router-dom` for routing,
Vitest + React Testing Library for tests. No UI component library, no
state-management library, no CSS framework — kept intentionally
minimal for a Phase 6A foundation.

### 16.5 Files created

```
frontend/
├── .env.example
├── README.md
├── index.html
├── package.json
├── tsconfig.json / tsconfig.app.json / tsconfig.node.json
├── vite.config.ts
└── src/
    ├── api/client.ts, endpoints.ts, client.test.ts
    ├── components/common/Button.tsx, Input.tsx, LoadingIndicator.tsx, ErrorBanner.tsx
    ├── components/layout/AppHeader.tsx, PageContainer.tsx
    ├── contexts/AuthContext.tsx
    ├── hooks/useAuth.ts
    ├── pages/auth/LoginPage.tsx (+.test.tsx), OTPPage.tsx (+.test.tsx), AuthFlow.integration.test.tsx
    ├── pages/placeholder/PlaceholderPage.tsx, AdminPlaceholderPage.tsx, ExamCentrePlaceholderPage.tsx
    ├── pages/errors/NotFoundPage.tsx, UnauthorizedPage.tsx
    ├── routes/AppRoutes.tsx, ProtectedRoute.tsx (+.test.tsx)
    ├── types/auth.ts, api.ts
    ├── test/setupTests.ts, testUtils.tsx
    ├── App.tsx, main.tsx, index.css, vite-env.d.ts
```

### 16.6 Files modified

- `.gitignore` — added `frontend/.env`, `frontend/.env.local`,
  `frontend/.env.*.local`, `frontend/coverage/` (node_modules/dist
  were already covered by pre-existing unscoped patterns).
- `PROJECT_STATE.md` — this section, plus the Section 3 status table.
- **No backend file was modified.** CORS already permitted the Vite
  default origin, so the "minimum necessary backend change" allowed by
  the brief turned out to be **zero changes**.

### 16.7 Authentication flow implemented

`unauthenticated` → `authenticating` → (`otp_required` |
back to `unauthenticated` on error) → `authenticated` →
`logging_out` → `unauthenticated`.

- Access token stored in `sessionStorage` (not `localStorage`) —
  survives a page refresh in the same tab, cleared when the tab
  closes. Deliberate, documented trade-off (see 16.11).
- `pre_auth_token` (OTP step) held **only in memory**, never
  persisted — it is short-lived by backend design and only needed
  within one login attempt.
- On every page load with a stored token, `GET /auth/me` is called to
  re-validate the token and fetch canonical identity; a failure clears
  storage and falls back to `unauthenticated`. The frontend never
  decodes the JWT or trusts a locally-cached role — `/auth/me` and the
  `/otp/verify` response are the only sources of role/identity used.
- Frontend route protection (`ProtectedRoute`, role-based redirects) is
  explicitly documented in code as a **UX layer only**; the backend's
  own `require_role` dependency remains the sole authorization
  boundary.

### 16.8 Routing created

`/login`, `/otp`, `/admin` (roles: Admin, Auditor — see rationale in
`AppRoutes.tsx`), `/exam-centre` (role: Examination Centre),
`/unauthorized`, `/` (redirects by role once authenticated), `*` → 404.
`/admin` and `/exam-centre` render explicit placeholder pages stating
the module is not yet implemented — no fake dashboard content.

### 16.9 Tests executed and results

```
npx vitest run
 Test Files  5 passed (5)
      Tests  12 passed (12)
```

Covers: login page render, empty-field validation blocks the API call,
loading state disables the submit button, backend error message is
displayed, full login→OTP→authenticated→logout integration flow via
real `AuthContext`, session restore via stored token, `ProtectedRoute`
blocking an unauthenticated user, API client's base-URL usage, 401
error-message extraction, and generic-fallback message on an
unparsable error body.

### 16.10 Build verification results

| Check | Result |
|---|---|
| `npm install` | Succeeded (180 packages) |
| `npx tsc -b --noEmit` | **0 errors** |
| `npx vitest run` | **12/12 passed**, 0 failed |
| `npm run build` (`tsc -b && vite build`) | Succeeded, no warnings (173.88 kB JS / 56.55 kB gzip) |
| `npm run dev` (manual curl check) | `HTTP 200` at `http://localhost:3000/` |
| Lint | No lint tool configured in this project yet (none introduced in this phase — out of scope; see 16.13). |

### 16.11 Security decisions / review

- No secrets, passwords, OTPs, JWTs, API keys, or credentials found
  anywhere in `frontend/` (explicit grep scan performed — see 16.12).
- No `console.*` call exists anywhere in the frontend source — OTP and
  password values are never logged, by construction (they simply never
  reach a logging call).
- Only `VITE_`-prefixed variables are read by the app
  (`VITE_API_BASE_URL`); `.env.example` contains no secret value.
- **Known, documented trade-off**: `sessionStorage` for the access
  token is vulnerable to XSS exfiltration in principle (as any
  JS-readable storage is); an httpOnly cookie would be stronger, but
  the backend does not currently issue one (it returns the JWT in the
  response body only — `backend/app/schemas/auth.py`). Changing that
  is a backend design decision out of scope for a frontend-only phase,
  and is recorded here for a future phase to reconsider rather than
  silently worked around.
- `npm audit` (see 16.13) flagged `react-router` (moderate, open
  redirect via backslash in `<Link>`/`useNavigate`) as still present
  even at the latest 6.x line (`6.30.6`, installed here); a fix
  requires the React Router v7 major version. Assessed risk for this
  phase: **low** — every `<Navigate>`/`useNavigate` target in this
  codebase is a static string literal, never derived from user input
  or a URL parameter, so the specific attack (attacker-controlled
  redirect target) has no exploitable path in the code that exists
  today. Deferred rather than silently ignored; flagged again in
  16.13 for Phase 6B+ to reassess once real navigation from
  user-influenced state (e.g. a "redirect back after login" `?next=`
  parameter) is ever introduced — at that point this must be revisited
  before shipping such a feature.

### 16.12 Security scan performed

```
grep -rniE "password\s*=\s*['\"][^'\"]|api[_-]?key\s*=\s*['\"]|secret\s*=\s*['\"][^'\"]|BEGIN (RSA|EC|PRIVATE) KEY|jwt\s*=\s*['\"]eyJ" frontend/src/
→ none found
grep -rn "console\." frontend/src/
→ no console usage found
find frontend -name ".env" -o -name ".env.local"
→ none found (only .env.example is present)
```

### 16.13 Known limitations (explicit, not hidden)

1. `npm audit`: 7 advisories (5 moderate, 1 high, 1 critical) remain
   after installing latest compatible versions. The high/critical
   entries are in `vite`/`esbuild`/`vitest` **dev-only** tooling
   (dev-server request handling / mock path traversal) — they do not
   ship in the production `dist/` bundle and only matter if an
   untrusted party can reach a developer's local `vite dev` server.
   The moderate `react-router` item is discussed in 16.11. None were
   silently suppressed; all are recorded here for a deliberate,
   explicit decision in a later phase (likely bundled with the React
   Router v7 upgrade Phase 6B or later would need to evaluate anyway).
2. No ESLint/Prettier configuration was introduced. The brief said "if
   the project has linting, run it" — none existed, and adding a new
   lint tool was judged out of scope for a foundation phase versus
   introducing genuine tooling debt; TypeScript's own `strict` mode
   (`noUnusedLocals`, `noUnusedParameters`, etc.) is the quality gate
   used instead. Flagged for Phase 6B+ to decide on explicitly.
3. If a user refreshes the browser *during* the OTP step (after
   password success, before OTP entry), the in-memory `pre_auth_token`
   is lost and they must restart from `/login`. This is a deliberate
   simplicity trade-off (the backend's `pre_auth_token` is short-lived
   by design anyway) rather than an oversight, but is recorded as a
   real UX limitation.
4. `AppRoutes`'s role→destination mapping (`Auditor` → `/admin`
   placeholder) is a Phase 6A navigation convenience, not a backend
   contract — documented inline in `AppRoutes.tsx` and flagged here for
   Phase 6B to confirm or revise once the Admin Portal's actual
   per-role views are designed.
5. No end-to-end (browser + live backend) test was run. All tests
   mock `fetch`; the dev-server check in 16.10 confirms only that the
   static app serves and responds, not a live login round-trip against
   a running backend. This was not claimed as tested.
6. Hyperledger Fabric / chaincode were **not touched, not tested from
   the browser, and not exercised in any way** this phase, consistent
   with the brief.

### 16.14 Backend regression result

```
cd backend && python3 -m pytest -q --ignore=tests/test_phase2_manual.py
→ 107 passed, 4 warnings (pre-existing FastAPI on_event deprecation
  warnings, unrelated to this phase — no backend file was modified)
```

Identical pass count to the pre-Phase-6A baseline run at the start of
this session. Zero regressions, because zero backend files changed.

### 16.15 Next phase

**Phase 6B — Admin Portal**, per the checkpoint sequence specified in
the original brief. Do not start it in this session/checkpoint.

**Phase 6A COMPLETE.**
**Phase 6B NOT STARTED.**

---

## 17. PHASE 6B — Admin Portal — COMPLETE (scope reduced by a real backend constraint)

### 17.1 Objective

Build a functional Admin Portal frontend (dashboard shell, question-paper
management, exam-centre management, audit logs, security events) on top
of the Phase 6A foundation, using only real, already-existing backend
endpoints. No backend API was invented, and no data was fabricated.

### 17.2 Mandatory inspection performed before any code was written

Read directly from source (not assumed):

- `backend/app/api/v1/router.py`, `admin.py`, `audit.py`, `papers.py`,
  `auth.py`, `exam_session.py`, `health.py`
- `backend/app/api/deps.py` (`CurrentUser`, `get_current_user`, `require_role`)
- `backend/app/schemas/papers.py`, `schemas/auth.py`
- `frontend/src/api/client.ts`, `endpoints.ts`
- `frontend/src/contexts/AuthContext.tsx`, `hooks/useAuth.ts`
- `frontend/src/routes/AppRoutes.tsx`, `ProtectedRoute.tsx`
- `frontend/src/components/**`, `frontend/src/pages/placeholder/**`
- `frontend/src/index.css`, `package.json`, `vite.config.ts`
- `.gitignore`, `git log`, `git status` (clean at Phase 6A checkpoint `9a77dca`)

**Discrepancy found and recorded here (Section 1's requirement):**
an empty, untracked directory literally named `frontend/src/{api,components`
(containing an empty `common,components` subdirectory) was present in
the extracted Phase 6A ZIP — clearly a leftover from a shell
brace-expansion `mkdir` typo in a previous session, never committed to
git (`git ls-files` does not list it; empty directories are never
tracked by git regardless). It was harmless but was removed as
housekeeping before starting Phase 6B work. No source file was
affected.

### 17.3 Critical finding that shaped this phase's real scope

Before writing any frontend code, the actual backend route bodies were
read (not just their signatures). The result changes what "Phase 6B"
can honestly mean for this project **today**:

| Backend route | File | Real status |
|---|---|---|
| `POST /papers/register` | `papers.py` | **Implemented** (Phase 3-5D) |
| `GET /papers/{paper_id}` | `papers.py` | **Implemented** |
| `GET /papers/{paper_id}/status` | `papers.py` | **Implemented** |
| `POST /papers/{paper_id}/authorize` | `papers.py` | **Implemented** |
| `GET /papers/{paper_id}/retrieve` | `papers.py` | Implemented (Exam-Centre only; out of scope for the Admin Portal) |
| `POST /admin/centres` | `admin.py` | **501 stub only** — RBAC real, business logic not written |
| `PATCH /admin/centres/{id}` | `admin.py` | **501 stub only** |
| `GET /admin/dashboard/summary` | `admin.py` | **501 stub only** |
| `GET /admin/exam-security-events` | `admin.py` | **501 stub only** |
| `GET /audit/logs` | `audit.py` | **501 stub only** |
| `GET /monitoring/security-events` | `audit.py` | **501 stub only** |
| `POST /exam-session/violation` | `exam_session.py` | **501 stub only** (Exam-Centre role; not Admin Portal scope anyway) |

Two further, load-bearing facts:

1. **There is no "list all papers" endpoint anywhere in the backend** —
   not even a stub. `GET /papers/{paper_id}` and
   `GET /papers/{paper_id}/status` are both single-paper lookups keyed
   by a UUID the caller must already know.
2. **There is no "list examination centres" endpoint anywhere in the
   backend** — not even a stub. Only `POST /admin/centres` (create,
   501) and `PATCH /admin/centres/{id}` (update, 501) exist.

Per the project's explicit rules ("Do NOT invent backend APIs," "Do
NOT fabricate data," "If a required admin operation genuinely cannot
be implemented because the backend does not expose it, document the
limitation instead of inventing data"), this phase does **not** build
a fake paper table, a fake exam-centre CRUD screen, fake audit-log
rows, or fake security events. What was built instead is documented
below, page by page, together with exactly which parts are real and
which are honestly labelled as not-yet-available.

### 17.4 What was implemented (real, working, backend-verified)

**Admin Portal shell** (`components/admin/AdminLayout.tsx`): header
(reused from Phase 6A `AppHeader`, unchanged) + a role-aware sidebar +
content outlet. Sidebar links are filtered by the signed-in user's
role using the *exact* RBAC matrix read from the backend's
`require_role(...)` calls (Admin sees all five sections; Auditor sees
only Dashboard, Audit Logs, Security Events — matching the backend,
which denies Auditor on papers/admin-centres endpoints). This is
documented in code as a UX convenience only; the backend independently
enforces every one of these checks regardless of what the sidebar
shows.

**Dashboard** (`pages/admin/AdminDashboardPage.tsx`): shows the signed-
in user's identity/role (real, from `AuthContext`), a session-local
count of papers seen so far, and, for Admin only, a real call to
`GET /admin/dashboard/summary` whose (currently 501) response is
surfaced honestly via `NotYetAvailableNotice` rather than hidden. No
chart, count, or statistic is fabricated. Auditor does not see this
card (backend denies Auditor on this endpoint).

**Question Papers** (`pages/admin/papers/PapersPage.tsx`,
`PaperUploadPage.tsx`, `PaperDetailPage.tsx`):
- **Upload** — a real multipart form calling `POST /papers/register`
  exactly as the backend defines it (`subject` + `release_timestamp`
  form fields, `file` as the raw PDF). All required UI states are
  implemented: Idle, Uploading (button disabled + "Please wait…"),
  Success (with the real `status`/`ledger_tx_reference` fields shown),
  Validation Error (empty fields, or backend 400/422), Authentication
  Error (401/403), Server Error (5xx), Network Error (client-side
  fetch failure). No encryption happens in the browser — the backend
  performs AES-256/SHA-256/Fabric registration entirely server-side,
  exactly as LLD Section 12/13 specifies.
- **Lookup / list** — because no list-all endpoint exists, this page
  is explicit about the constraint (visible note on the page) and
  offers: (a) a session-scoped table of papers the current admin has
  genuinely seen via real API responses this session (register or
  lookup — persisted only in `sessionStorage` via the new
  `useKnownPapers` hook, never fabricated), and (b) a real "look up by
  ID" form against `GET /papers/{paper_id}`.
- **Detail** — combines the real `GET /papers/{paper_id}` and
  `GET /papers/{paper_id}/status` responses (subject, status, SHA-256
  hash, release time, created time — exactly the fields
  `PaperMetadataResponse`/`PaperStatusResponse` return, nothing more),
  plus a real `POST /papers/{paper_id}/authorize` form. Because there
  is no centre-listing endpoint either, the examination-centre ID must
  be entered directly — the page says so rather than presenting a
  fake dropdown.

**Exam Centres** (`pages/admin/centres/ExamCentresPage.tsx`): per
17.3, this is a static, honest limitation notice — it does **not**
call `POST /admin/centres` on page load (that would be misusing a
"create" endpoint as a side effect of merely viewing a page) and does
**not** present a form for an operation that can never succeed. It
states plainly which two endpoints exist, that both are 501 stubs, and
that no listing endpoint exists at all.

**Audit Logs** (`pages/admin/audit/AuditLogsPage.tsx`) and **Security
Events** (`pages/admin/security/SecurityEventsPage.tsx`): both make
the real `GET` call on page load (a safe, idempotent read, unlike the
centres case), show a loading state, and then render the backend's own
501 response message via a shared `NotYetAvailableNotice` component —
or a genuine error banner if some other failure occurs. Both are
reachable by Admin and Auditor, matching the backend's
`require_role("Admin", "Auditor")`.

**Client extensions** (`api/client.ts`): two small, additive changes
only, per the brief's "modify the existing client cleanly" guidance —
no competing client was created:
1. `extractErrorMessage` now also recognizes the plain
   `{"detail": "..."}` body shape the 501 stub endpoints return
   (they never raise an `AppException`, so they never produce the
   app's usual `{"error": {"message": ...}}` shape) — without this,
   the backend's real "not implemented yet" message would have been
   silently replaced with a generic fallback string.
2. A new `apiRequestMultipart` function, a thin sibling of the
   existing `apiRequest`, for the one endpoint
   (`POST /papers/register`) that genuinely requires
   `multipart/form-data` rather than JSON. It reuses the same base
   URL, timeout, auth-token, and error-extraction logic — nothing is
   duplicated.

### 17.5 Routing added

```
/admin              (index)                 -> AdminDashboardPage        [Admin, Auditor]
/admin/papers                                -> PapersPage                [Admin only]
/admin/papers/upload                         -> PaperUploadPage           [Admin only]
/admin/papers/:paperId                       -> PaperDetailPage           [Admin only]
/admin/exam-centres                          -> ExamCentresPage           [Admin only]
/admin/audit-logs                            -> AuditLogsPage             [Admin, Auditor]
/admin/security-events                       -> SecurityEventsPage       [Admin, Auditor]
```

All nested under the existing `/admin` `ProtectedRoute` (unchanged
`allowedRoles={["Admin", "Auditor"]}`), now rendering `AdminLayout`
(sidebar + `<Outlet/>`) instead of the Phase 6A `AdminPlaceholderPage`.
Admin-only nested routes carry an additional inner `ProtectedRoute`
restricting them to `Admin`, matching the backend's own per-endpoint
RBAC. `/exam-centre` (Examination Centre placeholder) is untouched —
out of scope for this phase. `AdminPlaceholderPage.tsx` itself was
**left in place, unmodified, just no longer referenced by any route**
(per "do not remove previous functionality" — nothing was deleted).

### 17.6 Files created

```
frontend/src/types/papers.ts
frontend/src/components/admin/AdminLayout.tsx
frontend/src/components/admin/NotYetAvailableNotice.tsx
frontend/src/components/common/EmptyState.tsx
frontend/src/hooks/useKnownPapers.ts
frontend/src/pages/admin/AdminDashboardPage.tsx
frontend/src/pages/admin/AdminPortal.integration.test.tsx
frontend/src/pages/admin/papers/PapersPage.tsx
frontend/src/pages/admin/papers/PaperUploadPage.tsx
frontend/src/pages/admin/papers/PaperDetailPage.tsx
frontend/src/pages/admin/centres/ExamCentresPage.tsx
frontend/src/pages/admin/audit/AuditLogsPage.tsx
frontend/src/pages/admin/security/SecurityEventsPage.tsx
```

### 17.7 Files modified

```
frontend/src/api/client.ts       (extractErrorMessage `detail` fallback; apiRequestMultipart added)
frontend/src/api/endpoints.ts    (papers/admin/audit endpoint wrappers added)
frontend/src/routes/AppRoutes.tsx (nested /admin/* routes; AdminPlaceholderPage import removed, file kept)
frontend/src/index.css           (Admin Portal shell/table/form/notice styles added, nothing removed)
frontend/src/test/testUtils.tsx  (seedAuthenticatedSession, routedFetchMock helpers added)
PROJECT_STATE.md                 (this section)
```

**No backend file was modified.** Confirmed by `git status` showing
zero changes under `backend/` after this phase's work.

### 17.8 Backend APIs consumed (all real, verified against source)

```
POST /api/v1/papers/register
GET  /api/v1/papers/{paper_id}
GET  /api/v1/papers/{paper_id}/status
POST /api/v1/papers/{paper_id}/authorize
GET  /api/v1/admin/dashboard/summary   (real call; currently 501)
GET  /api/v1/audit/logs                (real call; currently 501)
GET  /api/v1/monitoring/security-events (real call; currently 501)
```

`createCentre()` (`POST /admin/centres`) was wrapped in `endpoints.ts`
for completeness/documentation but is **not called** anywhere in the
UI, for the reason given in 17.3/17.4 (ExamCentresPage).

### 17.9 Authentication / RBAC behaviour

Unchanged from Phase 6A: the backend remains the sole authorization
boundary; `ProtectedRoute` and the sidebar's role filtering are UX
layers only. Every new page still goes through the same
`AuthContext`/`apiRequest` machinery — no second authentication system
was introduced, and the bearer token is never read, copied, or logged
by any new code.

### 17.10 Upload behaviour

See 17.4. States implemented: Idle, Uploading, Success, Validation
Error, Authentication Error, Server Error, Network Error — all seven
named in the brief. `ApiError.status` (already provided by the Phase
6A client) is used to distinguish them; `status === null` is the
client's own signal for a network/timeout failure (see `client.ts`).

### 17.11 Exam-centre management behaviour

Not implemented as a working feature, by design — see 17.3/17.4. This
is a documented limitation, not an oversight.

### 17.12 Audit-log behaviour

Real `GET /audit/logs` call; backend's real 501 message surfaced. No
audit records are fabricated. No filtering UI was built (the backend
doesn't support any filter parameters yet either — `audit.py` takes no
query parameters).

### 17.13 Security-event behaviour

Same pattern as audit logs, calling `GET /monitoring/security-events`.
No AI/insider-threat detection was added (explicitly out of scope per
the project brief).

### 17.14 Tests

New file: `frontend/src/pages/admin/AdminPortal.integration.test.tsx`
(14 tests), covering:

- Admin dashboard renders for an authenticated Admin (17.4)
- Auditor does not see Question Papers / Exam Centres nav links
- Examination Centre role is blocked from `/admin/papers` (RBAC)
- Unauthenticated user hitting `/admin` is redirected to `/login`
- Question Papers empty state renders with no known papers
- Paper lookup by ID succeeds and navigates to the detail page
- Paper lookup shows a real 404 error message for an unknown ID
- Upload form renders (subject, release time, file, submit button)
- Upload validation error when required fields are missing
- Upload shows an authentication-error message on a 401 response
- Exam Centres page shows the documented limitation, not a fake form
- Audit Logs page surfaces the backend's real 501 message
- Security Events page shows a generic error banner for a non-501 failure
- Auditor can reach Audit Logs and Security Events (role permitted)

Combined with the 12 pre-existing Phase 6A tests (all still passing,
unmodified in behaviour), the full suite is:

```
npx vitest run
 Test Files  6 passed (6)
      Tests  26 passed (26)
```

**Coverage honestly stated**: this is a representative subset of the
Section 18 test list in the Phase 6B brief, not an exhaustive
one-test-per-bullet implementation (e.g. there is no dedicated
"loading state" unit test for every single page in isolation — several
pages share the same loading/error/empty pattern already exercised at
least once above). Given the backend-imposed scope reduction (17.3),
several of the brief's originally-listed test bullets (e.g. "successful
upload is handled" end-to-end with a real created row visible in a
list, or "supported management operations work" for exam centres) do
not have a corresponding real feature to test against yet.

### 17.15 TypeScript result

```
npx tsc -b --noEmit
→ 0 errors
```

### 17.16 Production build result

```
npm run build
✓ 64 modules transformed
dist/assets/index-*.js   189.50 kB (gzip: 60.60 kB)
dist/assets/index-*.css    6.39 kB (gzip:  1.79 kB)
✓ built in 1.94s
```

### 17.17 Security scan result

```
grep -rniE "password\s*=\s*['\"][^'\"]|api[_-]?key\s*=\s*['\"]|secret\s*=\s*['\"][^'\"]|BEGIN (RSA|EC|PRIVATE) KEY|jwt\s*=\s*['\"]eyJ" frontend/src/
→ none found
grep -rn "console\." frontend/src/
→ none found
find frontend -name ".env" -o -name ".env.local"
→ none found
git status --porcelain | grep -E "node_modules|dist/"
→ none found
```

No secrets, API keys, private keys, JWT literals, or `console.*` calls
were introduced. The AES key, wrapped DEK, and nonce continue to never
appear in any response type or component — verified again by re-
reading `backend/app/schemas/papers.py` and matching `types/papers.ts`
field-for-field.

### 17.18 Browser verification result

**Partial, honestly stated**: `npm run dev -- --port 3000 --strictPort`
was started and `curl http://localhost:3000/` returned `HTTP 200` with
the expected Vite-injected HTML shell — the same level of verification
Phase 6A itself performed and documented (16.10). **No actual
headless-or-real browser navigation of `/login`, `/otp`, `/admin`, or
any Admin Portal page was performed in this sandbox** (no browser
automation tool was available in this environment). This is not
claimed as done. All 26 automated tests do exercise real rendered
component trees via `@testing-library/react` + `jsdom`, which is a
meaningfully different (and narrower) form of verification than an
actual browser.

### 17.19 Backend regression result

```
cd backend && python -m pytest -q --ignore=tests/test_phase2_manual.py
→ 107 passed, 4 warnings (same pre-existing FastAPI on_event
  deprecation warnings as every prior phase — no backend file was
  modified this phase)
```

Identical pass count to the pre-Phase-6B baseline re-run at the start
of this session. Zero regressions, because zero backend files changed.

### 17.20 Known limitations (explicit, not hidden)

1. **Exam-centre management is not a working feature.** The backend
   has no list-centres endpoint at all, and its create/update
   endpoints are 501 stubs. This is the single biggest scope gap
   versus the original Phase 6B brief, and it is a backend gap, not a
   frontend oversight (see 17.3).
2. **Question-paper "list all papers" does not exist.** The Question
   Papers page's table is a session-local cache of papers the admin
   has personally registered or looked up, not a real catalogue. This
   is disclosed directly on the page, not hidden in a tooltip.
3. **Audit Logs and Security Events pages have no data to show even
   when "successful"** — the backend endpoints are 501 stubs, so there
   is currently no way to demonstrate a populated audit table or event
   list from this phase alone. The pages are built and wired
   correctly; they will render whatever the backend eventually returns
   once that phase's business logic exists (their `.catch` branches
   already stop treating 501 as an error once a future response no
   longer carries that status).
4. Dashboard shows no aggregate paper/centre counts, because no such
   backend endpoint exists (`/admin/dashboard/summary` is a 501 stub)
   and no list endpoint exists to derive counts from client-side.
5. `authorizeCentre` requires the operator to already know a valid
   examination-centre UUID (no picker/autocomplete is possible without
   a list endpoint). This is stated on the page itself.
6. No browser-level (real or headless) navigation test was performed —
   see 17.18. Only `jsdom`-based component tests and a dev-server
   HTTP-200 curl check were run.
7. Test coverage is a representative subset of the Section 18 test
   list in the brief, not one test per bullet — see 17.14's honest
   accounting of what is and is not covered.
8. `npm audit` advisories carried over unchanged from Phase 6A (dev-
   only `vite`/`esbuild`/`vitest` tooling; the `react-router` open-
   redirect item, still not exploitable in this codebase because no
   `<Navigate>`/`useNavigate` target is ever derived from user input —
   this remains true after Phase 6B, since every new redirect target
   added in this phase, e.g. `navigate(`/admin/papers/${paperId}`)`
   from `PapersPage`, is built from a value the backend itself
   returned for a paper the caller just successfully looked up or
   registered via an authenticated, RBAC-checked call — not from a raw
   attacker-controlled URL parameter).
9. The stray empty `frontend/src/{api,components...}` directory found
   during inspection (17.2) was removed as housekeeping; it was never
   tracked by git and had no effect on any prior phase's tests/build.

### 17.21 Decisions made (explicit, not silently assumed)

- Built the Admin Portal around the backend's real capabilities rather
  than deferring the entire phase or building non-functional UI for
  the 501-stub-only areas (exam centres). This was judged the better
  reading of the brief's own instruction to "implement only that
  subset" the backend supports, extended to the same principle for
  audit/security (page exists, makes the real call, shows the real
  501 honestly) versus exam centres (no safe idempotent call exists to
  make on page load, so a static notice was used instead).
- Session-scoped "known papers" cache (`sessionStorage`, not
  persisted server-side) is a Phase 6B UX decision, not a backend
  contract — clearly labelled as such in code and on the page.
- `release_timestamp` is converted from the browser's local
  `datetime-local` value to an explicit UTC ISO string
  (`new Date(...).toISOString()`) before sending, so a time-lock
  security control is never silently subject to timezone ambiguity
  between the browser and the backend.

### 17.22 Next phase

**Phase 6C — NOT STARTED.**

Recommended next steps, in order:
1. Project-owner review of the backend-scope gaps in 17.3/17.20 —
   confirm whether Phase 6C should implement the missing backend
   business logic (centre CRUD + list, dashboard summary, audit/
   security-event retrieval) before or alongside further frontend work,
   since several Admin Portal pages built in this phase are currently
   waiting on that backend work rather than any further frontend
   effort.
2. Per the original brief: do not start Phase 6C in this
   session/checkpoint.

**Phase 6B: COMPLETE.**
**Phase 6C: NOT STARTED.**
