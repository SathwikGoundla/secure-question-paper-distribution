# BLOCKCHAIN-ENABLED SECURE QUESTION PAPER DISTRIBUTION FRAMEWORK WITH TIME-LOCKED ACCESS

B.Tech CSE Major Project.

## Current implementation status

**Phase 1 — Implementation Foundation: COMPLETE**  
**Phase 2 — Authentication Module: COMPLETE**  
**Phase 3 — Not present in this uploaded project snapshot.**

This review package represents the actual code supplied for packaging. It does not claim later-phase features that are not present in the source.

## Technology stack

- Frontend: React.js (frontend folder is currently a placeholder)
- Backend: Python FastAPI
- Database: PostgreSQL
- Authentication: Username + Password + OTP + JWT
- Password hashing: bcrypt
- Blockchain interface: Hyperledger Fabric abstraction with an in-memory stub
- Storage interface: local development storage abstraction
- Testing: pytest/manual integration validation

## Current implemented scope

- FastAPI application foundation
- PostgreSQL models and database initialization
- Username/password authentication
- OTP verification
- JWT access sessions
- JWT session revocation on logout
- Role-based access control
- Examination-centre-to-paper authorization service
- Security and audit event persistence
- Blockchain service abstraction and development stub
- Local off-chain storage abstraction

## Not yet implemented in this snapshot

- AES-256-GCM paper-encryption service
- SHA-256 paper-integrity pipeline
- End-to-end question-paper upload/retrieval workflow
- Real Hyperledger Fabric network/chaincode integration
- Time-locked decryption
- React frontend implementation
- Production cloud storage
- Complete monitoring dashboard
- Exam-session tab-switch/security enforcement

See `docs/REVIEW_CHECKPOINT_CURRENT.md` for the verified checkpoint status and `docs/REVIEW_DEMO_GUIDE.md` for tomorrow's demonstration plan.

## Repository layout

```text
qpaper-system/
├── backend/
├── frontend/
├── blockchain/
├── storage/
└── docs/
```
