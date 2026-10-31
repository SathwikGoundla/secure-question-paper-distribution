# Blockchain-Enabled Secure Question Paper Distribution Framework with Time-Locked Access and Tamper Detection

B.Tech CSE final-year major project. A prototype that protects an examination question paper from creation to controlled release: encryption at rest, integrity verification, time-locked access, authenticated and authorized retrieval, audit logging, and an optional Hyperledger Fabric ledger.

> **Latest completed phase: 7A (real TOTP authenticator-app second factor).**
>
> **Status: prototype for academic evaluation. It is not production-ready.** The authoritative, phase-by-phase record (what was built, how it was tested, and what is still open) is [`PROJECT_STATE.md`](PROJECT_STATE.md). If this README and the source code ever disagree, the source code is correct. This README deliberately quotes no test counts; per-phase results are in `PROJECT_STATE.md`.

## What the system does (verified in source)

| Area | Implemented |
|---|---|
| Authentication | Username + password, then a **6-digit authenticator-app code (TOTP, RFC 6238)**, then a JWT. Codes cannot be replayed; secrets are encrypted at rest under a dedicated key; enrollment needs a one-time code issued by an Admin or the server operator; a lost authenticator is recovered by issuing a new code. Logout revokes the session. Failed-code attempts are limited per challenge; login, code and enrollment endpoints are rate limited. |
| Authorization | Role-based access control (Admin, Examination Centre, Auditor). A centre can only reach papers it has been explicitly authorized for; the Admin can revoke that authorization. A centre asking for a paper it may not access receives the same 404 as for a paper that does not exist. |
| Paper protection | Each paper is encrypted with AES-256-GCM using a per-paper key that is itself wrapped by a master key from the environment. A SHA-256 hash of the plaintext is recorded. Only ciphertext is stored (local storage by default). |
| Time lock | The **server clock** decides. Retrieval before the scheduled release time is refused (HTTP 403) and logged. An Admin can reschedule a paper only while it is still locked; every effective change is recorded with the old and new times. |
| Tamper detection | On retrieval the ciphertext is authenticated (GCM tag) and the SHA-256 is re-checked; with the Fabric backend the hash is also checked against the ledger. A mismatch is never released (HTTP 409). |
| Audit and monitoring | Audit events and security events are stored; Admin/Auditor can query them. The Admin dashboard shows counts: papers (by registration status), exam centres (total/active), authorizations, audit events and security events (by severity). |
| Frontend | React + TypeScript (Vite): login/OTP, an Admin portal (papers, upload, paper detail with scheduling, authorization and schedule history, exam centres, audit logs, security events) and an Examination Centre portal (authorized papers, status, retrieval). |
| Blockchain | A pluggable ledger abstraction. **Default: an in-memory stub.** Optional: a Fabric network, chaincode and Node.js gateway adapter in `blockchain/`. |

### Three different questions about a paper (do not conflate them)

| Question | Field / source | Meaning |
|---|---|---|
| Is it registered? | `status` (persisted) | The paper exists in the system. Currently always `registered`. |
| Has its release time arrived? | `lock_status` (computed by the server on every response) | `released` once the server clock has reached the scheduled time, otherwise `locked`. It does **not** mean anyone has opened the paper. |
| Has a centre actually received it? | `PAPER_RELEASED` audit event | Written only after authorization, time-lock, integrity checks and decryption all succeeded. |

## Not implemented / known limitations

- **Second factor is TOTP only.** There is no email or SMS OTP. TOTP is not phishing-resistant, and recovery depends on an Admin or the server operator issuing an enrollment code. A development-only console OTP remains behind `AUTH_SECOND_FACTOR=dev_console` (it logs the plaintext OTP, works only with `APP_ENV=development` **and** `OTP_DEV_LOG_ENABLED=true`, and cannot be enabled in production). See `backend/README.md` section 6.
- **Fabric is optional and partial.** With the default stub every ledger operation works in memory. With `BLOCKCHAIN_BACKEND=fabric` the deployed chaincode supports only `RegisterPaper`, `GetPaper`, `VerifyPaperHash` and `RecordAuditEvent`. The other ledger operations (`authorize_centre`, `revoke_centre`, `record_access_attempt`, `record_integrity_result`, `record_release`, `record_exam_violation`) are **unsupported** on Fabric and raise an "unsupported operation" error; the application does not call them against the ledger today. Authorization and revocation live in PostgreSQL, not on the ledger.
- Routes still returning HTTP 501: `POST /exam-session/violation` and `GET /admin/exam-security-events` (examination-session security is future work).
- Off-chain storage is the local filesystem (`./storage_data`); cloud storage is not implemented.
- Tables are created with SQLAlchemy `create_all` (no migration tool). Databases created by older phases need the `scripts/add_phase*_columns.py` helpers; see `backend/README.md`.
- Evaluation and user-feedback modules (project objectives 2 and 3) are not implemented.
- `PROJECT_STATE.md` lists the security issues that are still open. This is a student prototype and makes no security guarantee.
- According to `PROJECT_STATE.md`, the Fabric network, chaincode and adapter were exercised against a real network in earlier phases. That is historical evidence and was **not** re-run for Phase 6I.

## Repository layout

```text
qpaper-system/
├── backend/      FastAPI service, SQLAlchemy models, pytest tests      -> backend/README.md
├── frontend/     React + TypeScript + Vite portal, Vitest tests         -> frontend/README.md
├── blockchain/   Fabric network scripts, chaincode, Node gateway adapter -> blockchain/README.md
├── storage/      placeholder for local encrypted storage
├── docs/         historical phase reports and review notes
└── PROJECT_STATE.md   permanent continuity record, phase by phase
```

`docs/PHASE1_*` and `docs/PHASE2_*` are historical records of the earliest phases (labelled as such). `docs/REVIEW_*` describe the current checkpoint for reviewers.

## Quick start (local development)

Prerequisites: Python 3.11+ (3.12 used), Node.js 20+, PostgreSQL 13+.

```bash
# 1. Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then edit .env (never commit it)
#   required:  DATABASE_URL, JWT_SECRET_KEY
#   for papers: QUESTION_PAPER_MASTER_KEY  (base64 of 32 random bytes)
#   for sign-in: TOTP_ENCRYPTION_KEY  (a DIFFERENT base64 32-byte key; AUTH_SECOND_FACTOR defaults to totp)
python -m scripts.init_db   # creates the tables and the three roles
python -m scripts.create_user --username admin1 --password '<a strong password>' --role Admin
python -m scripts.totp_enroll_code --username admin1   # prints a one-time enrollment code (bootstrap)
uvicorn app.main:app --reload            # http://127.0.0.1:8000  (API docs at /docs)

# 2. Frontend (second terminal)
cd frontend
npm install
cp .env.example .env.local               # VITE_API_BASE_URL=http://localhost:8000/api/v1
npm run dev                              # http://localhost:3000
```

First sign-in: open http://localhost:3000/enroll, enter the username, password and the enrollment code, scan the QR with an authenticator app, type the 6-digit code to activate, then sign in normally (password + a fresh code). For a quick throw-away demo without an authenticator you can instead set `AUTH_SECOND_FACTOR=dev_console`, `OTP_DEV_LOG_ENABLED=true` (APP_ENV=development): the OTP is then printed in the backend console.

## Running the tests

```bash
# Backend. There is no pytest configuration file, so exclude the manual script explicitly.
cd backend
pytest -q --ignore=tests/test_phase2_manual.py                     # SQLite (temporary file)
DATABASE_URL=postgresql+psycopg2://USER:PASS@localhost/EMPTY_DB \
  pytest -q --ignore=tests/test_phase2_manual.py                   # PostgreSQL

# Frontend
cd frontend && npm test && npm run typecheck && npm run build
```

- Use a **brand-new, empty PostgreSQL database for each run.** The suite creates tables but does not drop them or clean up its rows, so re-using a database makes some tests (for example fixed centre names) fail with conflicts that are not code defects.
- A few tests are PostgreSQL-only and are skipped on SQLite. SQLite is for tests only; run the application on PostgreSQL.
- `backend/tests/test_phase2_manual.py` is a manual script that needs a running server; it is not part of the automated suite.
- Nothing in the backend suite proves a live Fabric deployment works; the Fabric parts have their own instructions in `blockchain/`.
