# Phase 1 Implementation Status — Implementation Foundation

> **HISTORICAL DOCUMENT — superseded.** This is the original Phase 1 report, written when no later phase existed. Statements such as "latest phase" or "not yet implemented" describe that moment only. The current, verified state is in `../PROJECT_STATE.md` and the READMEs.


**Date:** 23 August 2026
**Source documents:** PRD v2.1, SRS v1.1, HLD v1.1, LLD v1.1 (all Faculty-Review Update)
**Status: Phase 1 COMPLETE. No later phase has been started.**

---

## 1. Cross-Document Consistency Check (performed before writing any code)

Result: **no contradictions found** between PRD/SRS/HLD/LLD. Two items are genuinely
undetermined *in the documents themselves* (not a conflict — a deferred decision) and
were resolved here as Phase-1 implementation decisions:

| Item | Where it was open | Resolution | Reversible? |
|---|---|---|---|
| ORM / DB access technology | LLD 4.6 names PostgreSQL, not an ORM | SQLAlchemy (declarative models) | Yes — isolated to `app/database.py` and `app/models/` |
| Off-chain storage provider | LLD DD-13: NOT YET DETERMINED | Local filesystem, dev-only, behind a `StorageService` interface | Yes — swap in `services/storage_service.py` only |

---

## 2. Files Created

```
qpaper-system/
├── README.md
├── frontend/                          (empty — not started, Phase 10)
├── blockchain/                        (empty — not started, Phase 9)
├── storage/                           (empty — reserved for future real storage config)
├── docs/
│   └── PHASE1_IMPLEMENTATION_STATUS.md   (this file)
└── backend/
    ├── README.md
    ├── requirements.txt
    ├── .env.example
    ├── .gitignore
    ├── scripts/
    │   ├── __init__.py
    │   └── init_db.py
    └── app/
        ├── __init__.py
        ├── main.py                    FastAPI app, CORS, exception handlers, startup log
        ├── config.py                  Typed settings, all from environment
        ├── database.py                SQLAlchemy engine/session, get_db, health check
        ├── logging_config.py          Structured logging setup
        ├── api/
        │   ├── __init__.py
        │   └── v1/
        │       ├── __init__.py
        │       ├── router.py          Aggregates all sub-routers
        │       ├── health.py          GET /health — REAL, working
        │       ├── auth.py            Scaffold — 501, LLD API-01–03
        │       ├── papers.py          Scaffold — 501, LLD API-04–08
        │       ├── exam_session.py    Scaffold — 501, LLD API-14 (Faculty-Review)
        │       ├── admin.py           Scaffold — 501, LLD API-11–13, API-15
        │       └── audit.py           Scaffold — 501, LLD API-09–10
        ├── models/
        │   ├── __init__.py            Registers all models on Base.metadata
        │   ├── common.py              Shared UUID PK / timestamp helpers
        │   ├── role.py                roles (LLD 7.2)
        │   ├── exam_centre.py         exam_centres (LLD 7.3)
        │   ├── user.py                users (LLD 7.1)
        │   ├── paper.py               papers (LLD 7.4)
        │   ├── paper_authorization.py paper_authorizations (LLD 7.5)
        │   ├── audit_event.py         audit_events (LLD 7.6)
        │   ├── security_event.py      security_events (LLD 7.7)
        │   ├── otp_code.py            otp_codes (LLD 7.8)
        │   ├── auth_session.py        auth_sessions (LLD 7.9)
        │   └── exam_security_event.py exam_security_events (LLD 7.10, Faculty-Review)
        ├── schemas/
        │   ├── __init__.py
        │   └── health.py
        ├── services/
        │   ├── __init__.py
        │   ├── storage_service.py     Abstraction + local dev implementation
        │   └── blockchain_service.py  Abstraction (CC-01–CC-09) + in-memory stub
        ├── security/
        │   ├── __init__.py
        │   ├── password.py            bcrypt hashing (SEC-010)
        │   ├── jwt_handler.py         JWT issue/decode (SEC-004)
        │   └── otp.py                 OTP generation + delivery interface (SRS OQ-4)
        ├── exceptions/
        │   ├── __init__.py
        │   ├── base.py                Typed exception hierarchy
        │   └── handlers.py            Consistent JSON error responses, no leakage
        └── utils/
            └── __init__.py            (empty — reserved for future phases)
```

**Files modified:** none — this is a new project; nothing pre-existing was touched.

---

## 3. Architecture Implemented

Matches HLD Section 6/7 layering exactly, scoped to what Phase 1 requires:

```
React Frontend (not built yet)
        │  HTTPS
        ▼
FastAPI Backend (app/main.py)
        │
        ├── API layer (app/api/v1/*)        — routing only, thin
        ├── Security layer (app/security/*)  — password, JWT, OTP
        ├── Services layer (app/services/*)  — Storage, Blockchain (both abstracted)
        └── Data layer (app/models/*, app/database.py)
                    │
                    ▼
              PostgreSQL (real, tested)
```

The frontend never talks to PostgreSQL, storage, or the blockchain layer directly —
only the backend does, per HLD Section 6/7.2.

---

## 4. Dependencies Added

See `backend/requirements.txt`. Notable ones and why:

| Package | Why |
|---|---|
| fastapi, uvicorn | Approved backend framework (PRD/SRS/HLD tech stack) |
| sqlalchemy, psycopg2-binary | PostgreSQL access (LLD Section 7) |
| passlib[bcrypt], **bcrypt==4.0.1 (pinned)** | Password hashing (SEC-010). Pinned because passlib 1.7.4 breaks with bcrypt≥4.1 — **this was an actual bug hit and fixed during Phase 1 testing**, not a theoretical concern (see Section 7 below). |
| pyjwt | JWT issuance/validation (SEC-004) |
| pydantic, pydantic-settings, python-dotenv | Typed configuration from environment |
| python-multipart | Needed for file uploads in the paper-registration phase (not used yet) |
| pytest, httpx | Testing tools (used manually this phase; no automated test suite committed yet — see Section 9) |

---

## 5. Database Setup Status

- **A real local PostgreSQL 16 server was installed and run** in this environment
  (not a substitute) — `qpaper_db` database, `qpaper_user` role.
- `python -m scripts.init_db` executed successfully: **all 10 tables created**.
- Verified directly in `psql` (`\dt`), not just trusted from the Python side.
- The circular foreign key between `users.centre_id → exam_centres` and
  `exam_centres.created_by → users` was resolved with SQLAlchemy `use_alter=True`
  and **confirmed present as a real constraint** in PostgreSQL's `pg_constraint`.

---

## 6. Tests Performed (all real, against the real local Postgres + running server)

| # | Test | Result |
|---|---|---|
| 1 | `py_compile` every `.py` file | ✅ PASS — no syntax errors |
| 2 | `pip install -r requirements.txt` | ✅ PASS (after bcrypt fix, see Section 7) |
| 3 | `python -m scripts.init_db` against real PostgreSQL | ✅ PASS — 10/10 tables created |
| 4 | `\dt` and `pg_constraint` check directly in `psql` | ✅ PASS — tables and FKs present |
| 5 | Start `uvicorn app.main:app` | ✅ PASS — clean startup, no import errors |
| 6 | `GET /` | ✅ PASS — 200, correct JSON |
| 7 | `GET /api/v1/health` (DB up) | ✅ PASS — 200, `"status":"ok"`, `"database":"connected"` |
| 8 | `GET /api/v1/health` (DB deliberately pointed at a bad connection string) | ✅ PASS — 200, `"status":"degraded"`, `"database":"unavailable"` (fails gracefully, doesn't crash) |
| 9 | `GET /docs` (Swagger UI) | ✅ PASS — 200 |
| 10 | `POST /api/v1/auth/login` (scaffold) | ✅ PASS — 501 with clear message, at the LLD-correct path |
| 11 | `POST /api/v1/exam-session/violation` (scaffold) | ✅ PASS — 501, correct path |
| 12 | `GET /api/v1/nonexistent` | ✅ PASS — 404, standard FastAPI response |
| 13 | Secret-leakage check (grepped all responses/logs for the test DB password and JWT secret) | ✅ PASS — no leakage found |
| 14 | ORM smoke test: create Role/User/ExamCentre rows, exercise the circular FK, then clean up | ✅ PASS |
| 15 | Password hashing: `hash_password()` output ≠ plaintext; `verify_password()` correct on match and non-match | ✅ PASS |
| 16 | JWT: `create_access_token`/`decode_access_token` round-trip correct; tampered token correctly rejected | ✅ PASS |
| 17 | Blockchain stub: `register_paper`, `get_paper_metadata`, `authorize_centre`, `record_exam_violation` (CC-09) all functioned; unknown `paper_id` correctly raised instead of silently succeeding | ✅ PASS |
| 18 | Storage service: save/retrieve encrypted bytes round-trip exactly; missing reference returns `None` not an exception | ✅ PASS |

---

## 7. Errors Found and Fixed During Testing

**Real bug, not hypothetical:** `passlib==1.7.4` (latest passlib release, unmaintained
since 2020) crashed at runtime — `AttributeError: module 'bcrypt' has no attribute
'__about__'` — because the environment installed `bcrypt==5.0.0`, and passlib's bcrypt
backend-detection code depends on an attribute that bcrypt removed in 4.1+.

**Fix applied:** pinned `bcrypt==4.0.1` in `requirements.txt`, force-reinstalled, and
re-ran the full password-hashing test — confirmed working. This fix is documented
inline in `requirements.txt` and in `backend/README.md` so it isn't silently lost.

No other errors were encountered in this phase.

---

## 8. Unresolved Documentation Items (carried over, not invented here)

These were already flagged as `NOT YET DETERMINED` in the LLD and remain open —
Phase 1 did not need to resolve them, and did not silently pick answers:

- Exact off-chain storage provider (LLD DD-13) — dev-only local filesystem used for now
- OTP delivery channel (SRS OQ-4, LLD DD-12) — dev-only console logger used for now
- JWT expiry duration (LLD 14.6) — a working default (30 min) was set in config, clearly commented as provisional
- Password hashing algorithm "officially" NOT YET DETERMINED at LLD level (14.1) — bcrypt used as the Phase-1 working default, consistent with the LLD's own suggestion ("a standard adaptive hashing algorithm is assumed appropriate")
- Examination-time violation policy (zero-tolerance vs. warning-then-terminate, PRD 24.5 / LLD DD-14) — not yet relevant to Phase 1 (no violation-handling logic implemented yet), will matter starting in the Examination-Session Security phase

None of these block Phase 1. All are visible in code comments at the exact point they matter, not buried.

---

## 9. Known Limitations of This Phase (explicitly, not hidden)

- **No migration tool.** `scripts/init_db.py` uses `Base.metadata.create_all()`, which
  is fine for a fresh prototype database but cannot apply incremental schema changes
  safely. Introducing Alembic (or similar) before any schema change post-deployment
  is recommended, but is out of scope for Phase 1 per the instructions.
- **No automated test suite committed yet.** All 18 tests in Section 6 were run
  manually against a real database and server for this report. `pytest`/`httpx` are
  installed and ready; formalizing these into a committed `tests/` suite is a
  reasonable addition for a later phase but wasn't requested for Phase 1.
- **StubBlockchainService is not Hyperledger Fabric.** It provides zero
  immutability/tamper-evidence guarantees (SEC-008 is NOT satisfied by it). It exists
  solely so the interface boundary is real and testable ahead of the Blockchain
  Development phase.
- **LocalFileSystemStorageService is not a production storage decision.** Dev/demo only.
- **No rate limiting, no HTTPS termination configured** — expected for local dev; will
  matter at deployment time, not in scope here.
- **auth.py / papers.py / exam_session.py / admin.py / audit.py return 501 by design.**
  This is intentional Phase 1 scaffolding, not missing functionality that was
  supposed to exist yet.

---

## 10. Dependency Environment Notes

| Dependency | Why required | Install command | Verified | Unverified |
|---|---|---|---|---|
| Python 3.12 | Runtime | (pre-installed in this environment) | Yes — used throughout | — |
| PostgreSQL 16 | Approved DB (LLD 4.6) | `apt-get install postgresql postgresql-contrib` | Yes — installed, running, tables created, real data inserted/queried/deleted | Production-grade config (replication, backups, tuning) — not attempted, not in scope |
| pip packages | See requirements.txt | `pip install -r requirements.txt` | Yes — all imported and exercised | — |

No dependency could not be installed or tested in this environment. Everything
reported "PASS" above was actually executed, not assumed.

---

## 11. Next Implementation Phase

Per the phase-by-phase development lifecycle, **Phase 2 (of the implementation
sub-lifecycle)** should be: **Authentication Module** — implement `AuthService`,
`OTPService`, `JWTService` behind `POST /auth/login`, `POST /auth/otp/verify`,
`POST /auth/logout` (LLD API-01–03, Section 14), replacing the current 501 stubs.

**Waiting for your approval before starting Phase 2**, per the instruction to stop
after each phase.
