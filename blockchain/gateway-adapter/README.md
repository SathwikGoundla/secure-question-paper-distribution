# blockchain/gateway-adapter — Fabric Gateway Adapter (Phase 5B)

## Purpose

A small internal HTTP service that translates simple JSON requests
into real transactions against the `paper-ledger` chaincode, using the
**official** `@hyperledger/fabric-gateway` client library (not
`fabric-sdk-py`, not a CLI subprocess wrapper, not a mock).

This exists because there is no officially-supported Python Fabric
Gateway client (confirmed during the Phase 5 readiness inspection —
see `PROJECT_STATE.md`); Go, Node/TypeScript, and Java are the only
official options. TypeScript was chosen to match the chaincode
language too, minimizing the number of new languages this project
introduces.

**Phase 5B scope boundary:** this adapter is complete and independently
verified against a real Fabric network, but the FastAPI backend does
**not** call it yet — `backend/app/services/blockchain_service.py`
still only contains the Phase 1 `StubBlockchainService`, untouched
this phase. Wiring FastAPI to this adapter is Phase 5C.

## Architecture

```
Internet -> FastAPI -> (not yet wired — Phase 5C) -> this adapter (127.0.0.1 only) -> real Fabric network -> paper-ledger chaincode
```

The adapter binds to `127.0.0.1` exclusively (see `server.ts`'s
`main()`) — it is never exposed publicly. No authentication is added
at this layer yet, by design: the bind address is the security
boundary for this phase, matching the Phase 5B brief.

## Prerequisites

- Node.js >= 18, npm
- A running Phase 5A Fabric network — see `../network/README.md`:
  ```bash
  cd ../network/scripts
  bash generate-crypto.sh
  bash generate-channel-artifacts.sh
  bash start-network.sh
  bash deploy-chaincode.sh
  ```
- `/etc/hosts` must resolve `orderer.example.com` / `peer0.org1.example.com`
  to `127.0.0.1` (same requirement as Phase 5A — cryptogen issues TLS
  certificates for these hostnames, not bare IPs).

## Environment variables

Copy `.env.example` to `.env` — the example file's values already
match Phase 5A's actual network exactly (MSP ID, channel, chaincode
name, peer endpoint, and the Org1 Admin identity paths Phase 5A's own
scripts use for every lifecycle/invoke operation).

| Variable | Meaning |
|---|---|
| `ADAPTER_PORT` | HTTP port to listen on (default 8081) |
| `FABRIC_MSP_ID` | `Org1MSP` |
| `FABRIC_CHANNEL_NAME` | `paperchannel` |
| `FABRIC_CHAINCODE_NAME` | `paper-ledger` |
| `FABRIC_PEER_ENDPOINT` | `peer0.org1.example.com:7051` |
| `FABRIC_PEER_HOST_ALIAS` | Optional — only if connecting via a hostname that doesn't match the peer's TLS cert |
| `FABRIC_TLS_CERT_PATH` | Peer's TLS root CA (verifies the peer's server certificate) |
| `FABRIC_CERT_PATH` | This adapter's identity certificate |
| `FABRIC_PRIVATE_KEY_PATH` | This adapter's identity private key |

None of these are hardcoded anywhere in source — `fabricGateway.ts`
reads every one from `process.env` and fails fast with a clear error
naming the missing variable if one is absent.

**Identity note:** this phase reuses Phase 5A's Org1 Admin identity
(there is no narrower "application" identity in this project yet).
Using a dedicated, more restricted identity is a reasonable production
hardening step for later — flagged in `fabricGateway.ts`'s module
docstring, not silently treated as permanently fine.

## Starting the adapter

```bash
npm install
npm run build
cp .env.example .env   # adjust if your paths differ
npm start
```

## API endpoints

### `GET /health`
```json
{"status":"ok","service":"fabric-gateway-adapter","fabric_connected":true}
```
Cheap by design — reports whether a Gateway connection has been
established (lazy-connect-on-first-use), not a live round-trip call.

### `POST /fabric/register-paper`
Request:
```json
{
  "paper_id": "paper-123",
  "sha256_hash": "aaaa...(64 hex chars)",
  "registered_at": "2026-01-01T00:00:00Z",
  "admin_id": "admin-1",
  "subject": "Data Structures Final",
  "encryption_algorithm": "AES-256-GCM"
}
```
Success (201):
```json
{"success":true,"transaction_id":"e54a5563...(real 64-char Fabric tx id)","paper_id":"paper-123"}
```
Duplicate `paper_id` (409):
```json
{"error":{"message":"DUPLICATE_PAPER: paper_id 'paper-123' is already registered on the ledger.","type":"DUPLICATE"}}
```

### `GET /fabric/paper/:paper_id`
Success (200): the ledger record as JSON. Unknown paper (404):
```json
{"error":{"message":"PAPER_NOT_FOUND: no paper is registered with paper_id '...'.","type":"NOT_FOUND"}}
```

### `POST /fabric/verify-hash`
Request: `{"paper_id":"paper-123","candidate_hash":"..."}`
Response: `{"paper_id":"paper-123","match":true}` or `{"...,"match":false}`

### `POST /fabric/audit-event`
Request:
```json
{"event_id":"evt-1","event_type":"PAPER_REGISTRATION_COMPLETED","actor_id":"admin-1","paper_id":"paper-123","outcome":"SUCCESS","timestamp":"2026-01-01T00:00:01Z"}
```
Success (201): `{"success":true,"transaction_id":"...","event_id":"evt-1"}`

## Timeouts

Set in `fabricGateway.ts` and documented there: 5s for read-only
evaluate calls (GetPaper/VerifyPaperHash), 15s for endorsement, 15s
for submitting to the orderer, 30s for waiting on commit
confirmation. A failed/unreachable Fabric network surfaces as a clean
`503 FABRIC_UNAVAILABLE` JSON response rather than hanging indefinitely.

## Testing

```bash
npm run test:unit         # mocked Fabric contract — no network needed
npm run test:integration  # REAL Fabric network required (see Prerequisites)
```

`tests/unit/` mocks the Fabric contract entirely to test HTTP-layer
behaviour (validation, response shaping, error-status mapping) in
isolation. `tests/integration/` makes **zero** use of mocks — it
exercises the real running network end-to-end and checks that
returned transaction IDs are genuine 64-character hex Fabric
transaction identifiers, not placeholders. It skips itself cleanly
(printing which environment variable is missing) rather than
false-passing if `.env` isn't configured or the network isn't running.

## Troubleshooting

- **`ECONNREFUSED 127.0.0.1:7051`**: the Fabric network isn't running.
  Run `../network/scripts/start-network.sh` and
  `deploy-chaincode.sh` first.
- **`Name resolution failed for target dns:peer0.org1.example.com:7051`**:
  `/etc/hosts` doesn't resolve the peer hostname — see Prerequisites.
- **`Failed to read identity certificate at '...'`**: `.env`'s paths
  are wrong, or `generate-crypto.sh` hasn't been run yet (it creates
  the `../network/organizations/` directory these paths point into).
- **A chaincode-level error** (`DUPLICATE_PAPER`, `PAPER_NOT_FOUND`,
  etc.) is surfaced with its real message and an appropriate HTTP
  status — this is the network and chaincode working correctly, not
  an adapter bug.

## Security notes

- Internal service only — binds to `127.0.0.1`, never `0.0.0.0`.
- No private key, certificate content, or stack trace is ever included
  in an HTTP response — only chaincode error messages (which never
  contain key material by the chaincode's own design) or short, fixed
  strings. Full error detail (including stack traces) is logged
  server-side only, to the adapter's own console.
- `.env` is git-ignored (see the project root `.gitignore`); `.env.example`
  contains only paths, never actual key/certificate content.
