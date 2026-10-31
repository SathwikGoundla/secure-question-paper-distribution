# Backend — setup, configuration, run, test

FastAPI service for the Blockchain-Enabled Secure Question Paper Distribution Framework. This file describes the code as it actually is (through Phase 6I). The phase history and evidence are in `../PROJECT_STATE.md`; if they disagree with the source, the source wins.

## 1. Prerequisites

- Python 3.11+ (developed and tested on 3.12)
- PostgreSQL 13+ for real use. **SQLite is for the automated tests only:** the test harness installs a shim that makes SQLite return timezone-aware datetimes; running the application itself on SQLite fails (for example `/auth/otp/verify` raises a naive/aware datetime error).

## 2. Install

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Phase 7A added `pyotp` (TOTP) and `segno` (pure-Python QR code). `requirements.txt` pins `bcrypt==4.0.1` because `passlib==1.7.4` breaks at runtime with newer bcrypt releases. Install exactly as listed.

## 3. Configure (`cp .env.example .env`; never commit `.env`)

| Variable | Needed | Meaning |
|---|---|---|
| `DATABASE_URL` | **required** | `postgresql+psycopg2://USER:PASS@HOST:5432/DB` |
| `JWT_SECRET_KEY` | **required** | `python -c "import secrets; print(secrets.token_urlsafe(64))"` |
| `QUESTION_PAPER_MASTER_KEY` | needed to register/retrieve papers | Base64 of 32 random bytes: `python -c "import secrets,base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"`. If missing, encryption fails with a clear error. |
| `APP_ENV` | optional (default `development`) | `development`, `staging` or `production`. Only the exact value `development` enables development-only behaviour. |
| `AUTH_SECOND_FACTOR` | optional (default `totp`) | `totp` (authenticator app, the real method) or `dev_console` (development-only console OTP). See section 6. |
| `TOTP_ENCRYPTION_KEY` | **required for `totp`** | Dedicated key that encrypts TOTP secrets at rest: base64 of 32 random bytes, generated like the master key above but **a different value**. Missing/invalid -> TOTP login and enrollment return 503. |
| `TOTP_ISSUER`, `TOTP_VALID_WINDOW`, `TOTP_ENROLLMENT_CODE_TTL_HOURS`, `TOTP_ENROLLMENT_MAX_ATTEMPTS` | optional | Authenticator-app label (default `QPaper System`); accepted skew in 30 s steps each side (default `1`, allowed 0-2); enrollment-code lifetime (default 24 h); wrong attempts before an enrollment is destroyed (default 5). |
| `OTP_DEV_LOG_ENABLED` | optional (default `false`) | Only for `AUTH_SECOND_FACTOR=dev_console`; see section 6. |
| `CORS_ORIGINS` | optional (default `http://localhost:3000`) | Comma-separated explicit origins. `*` is rejected at startup. |
| `OTP_EXPIRE_SECONDS`, `OTP_MAX_ATTEMPTS`, `AUTH_LOGIN_RATE_LIMIT`, `AUTH_LOGIN_RATE_WINDOW_SECONDS`, `AUTH_OTP_RATE_LIMIT`, `AUTH_OTP_RATE_WINDOW_SECONDS` | optional | OTP lifetime, failed attempts allowed per challenge, and per-IP request limits for login and OTP verify. |
| `JWT_EXPIRE_MINUTES`, `PRE_AUTH_TOKEN_EXPIRE_MINUTES` | optional | Session and pre-auth token lifetimes. |
| `STORAGE_BACKEND`, `STORAGE_LOCAL_PATH`, `PAPER_MAX_UPLOAD_SIZE_BYTES` | optional | Local encrypted-file storage (the only backend), and the upload size cap. |
| `BLOCKCHAIN_BACKEND` | optional (default `stub`) | `stub` or `fabric`; see "Blockchain" below. |
| `FABRIC_GATEWAY_ENDPOINT`, `FABRIC_GATEWAY_TIMEOUT_SECONDS`, `FABRIC_CHANNEL_NAME`, `FABRIC_CHAINCODE_NAME`, `FABRIC_VERIFICATION_MODE` | only with `fabric` | Adapter URL, timeout, channel/chaincode names, and `best_effort` (default) or `strict` behaviour when the ledger cannot confirm a hash. |

## 4. Create the database

```sql
CREATE USER qpaper_user WITH PASSWORD 'your-local-password';
CREATE DATABASE qpaper_db OWNER qpaper_user;
```

```bash
python -m scripts.init_db        # creates all tables and the 3 roles; safe to re-run
```

Tables come from SQLAlchemy `create_all`; this project has no migration tool. `create_all` only creates **missing tables** (for example the Phase 6H `paper_schedule_history` table appears on the next `init_db`); it never alters existing ones. A database created before a phase that added **columns** needs the matching one-off helper (each is idempotent): `scripts/add_phase3_columns.py`, `scripts/add_phase5d_columns.py`, `scripts/add_phase6e1_columns.py`. A database created today needs none of them.

## 5. Provision users, run, check

```bash
python -m scripts.create_user --username admin1 --password '<strong password>' --role Admin
python -m scripts.create_user --username centre1 --password '<strong password>' \
    --role "Examination Centre" --centre-id <uuid of an exam_centres row>
uvicorn app.main:app --reload                      # http://127.0.0.1:8000, docs at /docs
curl http://127.0.0.1:8000/api/v1/health
```

There is no public registration endpoint. An Admin creates examination centres through the API/portal; centre login accounts are created with the CLI above.

## 6. Second factor: TOTP (Phase 7A)

**Choice and rationale.** Authenticator-app TOTP (RFC 6238, library `pyotp`) was chosen over SMTP email OTP because the existing challenge machinery (signed pre-auth token + `otp_codes` row for expiry, single use and the per-challenge attempt limit) already supplies everything except "check the code"; TOTP needs no mail server, credentials, deliverability or running cost, and works offline for exam centres. Its cost is enrollment (below). **No email/SMS OTP exists.**

**Login flow (`AUTH_SECOND_FACTOR=totp`, the default).**
1. `POST /auth/login` (username + password). Wrong password -> generic 401. Valid password but no *active* authenticator -> 403 "Authenticator setup is required…" and **no token**. Otherwise a challenge row is created and a restricted pre-auth token (`purpose=pre_auth`, `mfa=totp`) is returned with `second_factor: "totp"`.
2. `POST /auth/otp/verify` (pre-auth token + 6-digit code). On success, and only then, the normal JWT is issued. Every failure (wrong, malformed, expired, replayed, locked, spent challenge) returns the same generic 401 and no JWT.
The pre-auth token authorizes nothing else (rejected by every protected endpoint). Its `mfa` claim is signed and must equal the configured method, so a leftover development challenge is dead in TOTP mode and vice versa.

**TOTP rules.** SHA-1 / 6 digits / 30 s (the parameters every authenticator app supports); accepted skew `TOTP_VALID_WINDOW` steps each side (default +/-30 s); constant-time comparison over the whole window; **replay protection**: a code is accepted only for a time step strictly newer than the last accepted one (stored per user, updated atomically with consuming the challenge under a row lock), so after a login you wait for the next 30 s code; challenge expiry (`OTP_EXPIRE_SECONDS`), single use, `OTP_MAX_ATTEMPTS` per challenge, and the existing per-IP/challenge rate limits all apply unchanged. The enrollment confirmation code cannot be replayed as a login code.

**Secrets at rest.** Each user's secret is encrypted with AES-256-GCM under `TOTP_ENCRYPTION_KEY`, with the user id as associated data (a ciphertext cannot be moved to another account). The key must differ from `QUESTION_PAPER_MASTER_KEY` (checked). Secrets, enrollment codes and codes are never logged and never returned after enrollment confirmation. **Backup / rotation:** keep the key in your secret store, separate from database backups. There is no automatic rotation; changing or losing the key makes every stored secret undecryptable and every user must re-enroll (via new enrollment codes).

**Enrollment (no password-only enrollment, by design).** If a not-yet-enrolled user could enroll with just a password, anyone who stole that password could attach their own authenticator. So enrollment needs a **one-time enrollment code** issued out-of-band:
1. *Issue a code:* the first Admin (and anyone locked out) is bootstrapped by the **server operator**: `python -m scripts.totp_enroll_code --username admin1` (needs server/database access, the system's trust root; prints the code once). Afterwards an **Admin** can issue one for another user: `POST /admin/totp/enrollment-codes {"username": "..."}` (Admin only; not for yourself).
2. *Start:* the user opens `/enroll` in the portal and enters username + password + code (`POST /auth/totp/enroll/start`, rate limited, one generic 401 for every failure, code destroyed after `TOTP_ENROLLMENT_MAX_ATTEMPTS` wrong tries). The secret/QR is returned **once**; the authenticator is *not yet usable*.
3. *Confirm:* a valid code from the app (`POST /auth/totp/enroll/confirm`, accepts only the short-lived enrollment token) activates it. No session is issued; the user then signs in normally.

**Lost authenticator / recovery.** An Admin issues a new enrollment code for the user (or the operator uses the CLI for an Admin). Issuing a code **immediately wipes the old authenticator and revokes the user's sessions**. Recovery therefore depends on a trusted human channel to hand over the code. An Admin cannot reset their own authenticator through the API (a hijacked admin session must not be able to enroll the attacker's device).

**Upgrading an existing database.** `python -m scripts.init_db` creates the new `user_totp` table (no existing table is altered, no data is touched). Existing users have no authenticator and cannot sign in until you run `scripts.totp_enroll_code` for each (or an Admin issues codes). `create_user` prints this reminder.

**Audit/monitoring.** Audit events: `TOTP_ENROLLMENT_CODE_ISSUED` (actor = issuing Admin, none for the CLI), `TOTP_ENROLLMENT_STARTED`, `TOTP_ENROLLED`. Security events: `LOGIN_BLOCKED_NOT_ENROLLED`, `TOTP_ENROLLMENT_FAILED`, `TOTP_ENROLLMENT_LOCKED`, `TOTP_REPLAY_REJECTED`, plus the existing `INVALID_OTP`/`OTP_CHALLENGE_LOCKED`. `audit_events` has no "target user" column, so who a code was issued *for* is recorded in `user_totp.code_issued_by`/`code_issued_at` (overwritten by a later issuance).

**Residual risks.** Phishing of a live code is possible (TOTP is not phishing-resistant). The "valid password, not enrolled" 403 reveals account state to someone who already knows the password. TOTP's recovery relies on an Admin/operator. The key is a single point of failure (backup it). SHA-1 HMAC is the app-compatible standard and is not weakened by the known SHA-1 collision attacks, but stronger algorithms are not reliably supported by authenticator apps.

**Development-only legacy flow (`AUTH_SECOND_FACTOR=dev_console`).** Retained so local development and the older test suite work without an authenticator. The OTP is written to the server log, and only when `APP_ENV=development` **and** `OTP_DEV_LOG_ENABLED=true` (Phase 6I gating, unchanged); otherwise login returns 503. It cannot be enabled in production, and TOTP is the default.

## 7. CORS

Fixed in `app/main.py` to what the routes and the frontend actually use: methods `GET`, `POST`, `PATCH`; request headers `Accept`, `Authorization`, `Content-Type`; no credentials (the API uses a Bearer token, not cookies). Only the origin list is configurable (`CORS_ORIGINS`). CORS is enforced by browsers, not servers; it is not an authentication control. A reverse proxy that adds its own CORS headers is outside what the tests cover.

## 8. Paper endpoints and the disclosure policy

All under `/api/v1`. Roles in brackets.

- Auth: `POST /auth/login`, `/auth/otp/verify`, `/auth/logout`, `GET /auth/me`; Phase 7A: `POST /auth/totp/enroll/start`, `/auth/totp/enroll/confirm`; Admin: `POST /admin/totp/enrollment-codes`.
- `POST /papers/register` [Admin]: upload, encrypt, hash, store, register on the ledger.
- `GET /papers` [Admin, Centre (authorized papers only)]; `GET /papers/{id}`, `GET /papers/{id}/status` [Admin, authorized Centre].
- `POST /papers/{id}/authorize`, `POST /papers/{id}/revoke` [Admin]; `PATCH /papers/{id}/schedule` [Admin, only while locked]; `GET /papers/{id}/schedule-history` [Admin].
- `GET /papers/{id}/retrieve` [Centre]: authorization, then time lock, then decrypt and integrity checks.
- Audit/monitoring: `GET /audit/logs`, `GET /monitoring/security-events` [Admin, Auditor]; `GET /admin/dashboard/summary`, `/admin/centres…` [Admin].

**Existence disclosure (Phase 6I):** for an Examination Centre, a paper that does not exist, one it was never authorized for, and one whose authorization was revoked all return the **identical** `404 "The requested resource was not found."` (no subject, hash or schedule). The denial is still audited. A centre that *is* authorized but asks before the release time gets `403 "This paper is not yet available."` (it is entitled to know the paper exists). Admin-only routes return 403 to a non-admin before any lookup. Not mitigated: response timing could in theory differ between the two 404 cases.

**Status fields:** `status` = registration; `lock_status` = release state computed by the server clock; whether a centre actually received the paper is the `PAPER_RELEASED` audit event. They are different things.

Routes that still return 501: `POST /exam-session/violation`, `GET /admin/exam-security-events`.

## 9. Blockchain

- **Default (`BLOCKCHAIN_BACKEND=stub`):** an in-memory stand-in implementing every ledger operation. Nothing is persisted; this is what the automated tests use.
- **Fabric (`BLOCKCHAIN_BACKEND=fabric`):** calls a Node.js gateway adapter (`../blockchain/gateway-adapter`) which talks to a Fabric network. The deployed chaincode (`../blockchain/chaincode/paper-ledger`) supports four operations: `RegisterPaper`, `GetPaper`, `VerifyPaperHash`, `RecordAuditEvent`. The backend uses them at paper registration, at retrieval (hash verification) and for audit events. `authorize_centre`, `revoke_centre`, `record_access_attempt`, `record_integrity_result`, `record_release` and `record_exam_violation` are **not supported** on Fabric (they raise an unsupported-operation error and are not called against the ledger).
- A ledger failure never prevents the audit row being written in PostgreSQL. With `FABRIC_VERIFICATION_MODE=strict`, retrieval is refused (503) if the ledger cannot confirm the hash; with `best_effort` it proceeds on the local AES-GCM and SHA-256 checks. A ledger answer of "hash does not match" always rejects.
- The PDF, keys, passwords and OTPs are never sent to the ledger.
- Unit tests here use fakes and the stub; they do **not** prove a live Fabric deployment works.

## 10. Tests

```bash
cd backend
pytest -q --ignore=tests/test_phase2_manual.py          # SQLite
DATABASE_URL=postgresql+psycopg2://USER:PASS@localhost/EMPTY_DB pytest -q --ignore=tests/test_phase2_manual.py
```

- The test environment (`tests/conftest.py`) sets `AUTH_SECOND_FACTOR=dev_console`, `OTP_DEV_LOG_ENABLED=true`, `APP_ENV=development` and a random `TOTP_ENCRYPTION_KEY`, like a developer's local `.env`, so the pre-7A suite can read OTPs; the OTP-gating and `test_totp_auth.py` tests override these per test.
- There is no pytest configuration file, so plain `pytest` also tries to collect `tests/test_phase2_manual.py`, which needs a running server and fails at collection. Exclude it as shown.
- The suite creates tables but does not drop them or clean its rows. **Use a new, empty database for each PostgreSQL run**; re-using one causes spurious conflict failures in tests that create fixed-name centres.
- Some tests are PostgreSQL-only (for example a real row-lock race) and skip on SQLite.
- `tests/test_phase2_manual.py` (needs `uvicorn` running and `PYTHONPATH=.`) predates later phases and is historical.
