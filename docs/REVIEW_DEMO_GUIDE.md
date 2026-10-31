# Review Demo Guide

Describes what can be demonstrated from the **current** code (Phase 7A) and what must not be claimed. Verify anything here against the source if in doubt.

## Setup (local)

See the root `README.md` quick start. You need PostgreSQL, an authenticator app on a phone (or any RFC 6238 tool), and a backend `.env` with `DATABASE_URL`, `JWT_SECRET_KEY`, `QUESTION_PAPER_MASTER_KEY` and a *different* `TOTP_ENCRYPTION_KEY`.

```bash
cd backend && python -m scripts.init_db
python -m scripts.create_user --username admin1 --password '<password>' --role Admin
python -m scripts.totp_enroll_code --username admin1   # prints a one-time enrollment code
uvicorn app.main:app --reload
cd ../frontend && npm run dev            # http://localhost:3000
```

## Suggested demonstration

1. **Enroll and log in:** open `/enroll`, enter username, password and the enrollment code, scan the QR, confirm with the app's code. Then sign in: username/password, then a fresh 6-digit code, then the Admin portal. (Codes are single-use per 30-second step; wait for the next code if you just enrolled.)
2. **Create an examination centre** (Admin portal) and a centre login with `scripts.create_user --role "Examination Centre" --centre-id <id>`.
3. **Register a paper** with a release time a few minutes ahead. Point out: ciphertext only on disk, SHA-256 recorded.
4. **Authorize the centre.** In the centre portal the paper shows registration status `registered` and release state `Locked`; retrieval is refused (403 "not yet available") and logged.
5. **Reschedule** while locked and open the **schedule history** (old/new times, who, when).
6. **After the release time** the centre retrieves the PDF. Show the audit log (`PAPER_RELEASED`), the evidence it was actually opened. `lock_status = released` alone proves nothing about access.
7. **Authorization boundary:** a second centre requesting the paper, or a random id, gets the identical "not found". **Revoke** the first centre and retrieve again: same result.
8. **Tamper detection (optional, with a prepared copy):** altering the stored ciphertext makes retrieval fail integrity verification (409); it is never released.
9. **Security events:** failed logins and OTP lockouts appear for Admin/Auditor.
10. **Lost phone:** an Admin issues a new enrollment code for the user (`POST /admin/totp/enrollment-codes`); the old authenticator and sessions stop working immediately; the user re-enrolls at `/enroll`.

## What you may claim

AES-256-GCM per-paper encryption; SHA-256 integrity; server-side time lock with logged denials; role-based and per-paper authorization with revocation; audit and security-event trail; rate limiting, OTP attempt limiting and security headers; restricted CORS.

## What you must not claim

- Email/SMS OTP (not implemented; the second factor is an authenticator app). Do not claim TOTP is phishing-resistant.
- That Hyperledger Fabric is required or fully integrated. The default is an in-memory stub; with Fabric only four chaincode operations are supported.
- That centre authorization or revocation is recorded on the blockchain (it is in PostgreSQL).
- Exam-session security, evaluation or feedback modules, cloud storage.
- That this is production-ready, "better" or "first". `PROJECT_STATE.md` lists open issues.

## Likely follow-up questions

- *Why not store the paper on the blockchain?* Large and confidential; only hashes/audit metadata go on-chain.
- *Who decides release time?* The backend clock; the browser clock is never trusted.
- *Why does an unauthorized centre see "not found"?* So it cannot discover which paper ids exist.
- *Is the code sent by email/SMS?* No. It is a TOTP computed by the user's authenticator app; recovery is an Admin/operator-issued one-time enrollment code.
