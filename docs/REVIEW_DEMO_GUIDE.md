# Review Demo Guide

## Project

**BLOCKCHAIN-ENABLED SECURE QUESTION PAPER DISTRIBUTION FRAMEWORK WITH TIME-LOCKED ACCESS**

## What is safe to demonstrate from the supplied current code

### 1. Backend startup

```bash
cd backend
pip install -r requirements.txt
```

Configure `backend/.env` from `.env.example`, then:

```bash
uvicorn app.main:app --reload
```

Open:

```text
http://127.0.0.1:8000/docs
```

### 2. Database initialization

After configuring PostgreSQL:

```bash
cd backend
python -m scripts.init_db
```

### 3. Authentication demonstration

Provision a development user using the supplied CLI:

```bash
python -m scripts.create_user --username admin1 --password "Str0ng!Pass" --role Admin
```

Then demonstrate:

1. Username/password login
2. OTP verification
3. JWT issuance
4. `/auth/me`
5. Logout
6. Protected endpoint access / RBAC

The OTP delivery in this snapshot is development-only and is exposed through the configured development provider/logging path.

### 4. What the paper APIs currently demonstrate

The paper/admin/audit/exam-session routes have RBAC protection, but their business logic intentionally returns `501 Not Implemented` in this snapshot.

Do not present these as completed paper-distribution features.

## Suggested faculty explanation

> “The current implementation checkpoint establishes the secure backend foundation first. Authentication, OTP, JWT session control, RBAC, database models, audit/security event structures, storage abstraction, and blockchain service abstraction are implemented. The subsequent implementation phases will connect the cryptographic paper pipeline, real Hyperledger Fabric network, time-lock release, and frontend.”

## Important distinction

The project architecture includes AES-256, SHA-256, Hyperledger Fabric and time-locked access as target capabilities. The supplied code snapshot does not contain the later cryptographic service or real Fabric network implementation.

Do not claim that those later components are already operational during this review if they are not present in the source.

## Quick checks

```bash
python -m compileall backend
```

For the historical Phase 2 manual suite, the project documentation records 28/28 passing tests against the original real PostgreSQL + uvicorn setup. Re-run it in the actual development environment before presenting a fresh test count.
