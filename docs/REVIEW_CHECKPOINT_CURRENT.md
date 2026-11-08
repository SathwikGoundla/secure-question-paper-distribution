# Current Review Checkpoint

**Project:** Blockchain-Enabled Secure Question Paper Distribution Framework with Time-Locked Access and Tamper Detection
**Checkpoint:** Phase 7B (recovery codes, Admin enrollment management, TOTP key rotation; builds on Phase 7A)
**Authoritative record:** `../PROJECT_STATE.md` (per-phase evidence). If this file and the source disagree, the source is correct.

This file replaces an earlier snapshot (Phase 2 era) that said paper APIs returned 501, encryption was absent and the frontend was empty. None of that is true of the current code.

## Verified implementation status (checked against source)

| Module | Status | Where |
|---|---|---|
| Username + password, OTP, JWT, logout/revocation | IMPLEMENTED | `backend/app/api/v1/auth.py`, `services/auth_service.py` |
| Second factor | **IMPLEMENTED: TOTP authenticator app (Phase 7A)** | `app/security/totp.py`, `services/totp_service.py`; encrypted secrets, replay protection, one-time enrollment codes, admin/CLI recovery. **No email/SMS OTP.** |
| Recovery codes | **IMPLEMENTED (Phase 7B)** | one-time backup second factor, hashed at rest, used only after the password, atomic single use, regeneration with password step-up; `services/recovery_code_service.py` |
| Admin enrollment management UI | **IMPLEMENTED (Phase 7B)** | `/admin/totp`, `GET /admin/totp/users`; state only, no secrets |
| TOTP key rotation | **IMPLEMENTED (Phase 7B)** | versioned keyring (`v2` envelope with key id), `python -m scripts.rotate_totp_encryption_key` (dry-run, resumable, verified); operator procedure, not scheduled |
| Development console OTP | development only | `AUTH_SECOND_FACTOR=dev_console`; logs the OTP only with `APP_ENV=development` and `OTP_DEV_LOG_ENABLED=true` |
| OTP attempt limit, login/OTP rate limits, security headers | IMPLEMENTED | Phase 6E |
| RBAC (Admin, Examination Centre, Auditor) | IMPLEMENTED | `app/api/deps.py` |
| Paper registration, AES-256-GCM encryption, SHA-256, local storage | IMPLEMENTED | `services/paper_service.py`, `crypto_service.py`, `storage_service.py` |
| Centre authorization and revocation | IMPLEMENTED (PostgreSQL) | `paper_authorizations`; not recorded on the ledger |
| Time-locked retrieval (server clock) | IMPLEMENTED | `paper_service.retrieve_paper`, `is_released` |
| Release rescheduling (only while locked) and schedule history | IMPLEMENTED | Phases 6G, 6H |
| Tamper detection (GCM tag + SHA-256, optional ledger check) | IMPLEMENTED | Phases 3, 5E |
| Audit events, security events, Admin dashboard (counts) | IMPLEMENTED | Phase 6C |
| Existence-disclosure policy (centre gets identical 404) | IMPLEMENTED | Phase 6I |
| CORS limited to GET/POST/PATCH, three headers, no credentials | IMPLEMENTED | Phase 6I |
| React Admin portal and Examination Centre portal | IMPLEMENTED | `frontend/src`, Phases 6A–6H |
| Hyperledger Fabric | **PARTIAL, optional** | Default is an in-memory stub. With Fabric: chaincode supports RegisterPaper, GetPaper, VerifyPaperHash, RecordAuditEvent only; six other ledger operations are unsupported |
| Exam-session security (`/exam-session/violation`, `/admin/exam-security-events`) | NOT IMPLEMENTED (HTTP 501) | |
| Cloud storage | NOT IMPLEMENTED | local filesystem only |
| Evaluation and user-feedback modules | NOT IMPLEMENTED | planned |

## Verification evidence

Executed results (counts, SQLite vs PostgreSQL, mutation checks) for each phase are in `PROJECT_STATE.md`; Phase 6I results are in its section 26, Phase 7A in section 27 and Phase 7B in section 28. Phase 2's "28/28 manual checks" is historical. A live Fabric network was **not** exercised in Phase 6I.

## Honesty notes

- There is no email/SMS OTP; the real second factor is an authenticator app (TOTP). TOTP is not phishing-resistant. Recovery is by saved recovery codes or an Admin/operator-issued enrollment code.
- "Released" (`lock_status`) means the scheduled time has arrived on the server; it does not mean a centre opened the paper.
- This is a prototype and makes no production-security claim; open issues are listed in `PROJECT_STATE.md`.
