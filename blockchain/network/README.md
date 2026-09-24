# blockchain/network — Phase 5A Fabric Network

## What this is

A minimal Hyperledger Fabric 2.5 network for the `paper-ledger` chaincode:
1 organization (Org1), 1 peer, 1 Raft orderer (single node), LevelDB,
1 channel (`paperchannel`). This matches the approved Phase 5
architecture recorded in `PROJECT_STATE.md`.

## Two ways to run it

### Path A — native binaries (ACTUALLY TESTED end-to-end this phase)

Uses the official Fabric binary release (peer, orderer, cryptogen,
configtxgen, osnadmin — downloaded from GitHub Releases, not Docker
Hub) run as plain OS processes, with chaincode deployed via
**Chaincode-as-a-Service (CCaaS)** — a real Node.js process the peer
connects to over TCP, no Docker image build needed for the chaincode.

This is the path used to produce the real transaction IDs recorded in
`PROJECT_STATE.md`'s Phase 5A section (RegisterPaper, GetPaper,
VerifyPaperHash match/mismatch, RecordAuditEvent, duplicate rejection —
all genuinely executed against a live network).

**Why this path exists at all** (rather than just Docker Compose): the
development sandbox used to build this phase has no route to Docker
Hub (`registry-1.docker.io` → HTTP 403). Fabric's binaries are hosted
on GitHub Releases instead, which *was* reachable, so this became both
a necessity and — usefully — a fully real, verified deployment path
that also works well for CI or any Docker-restricted environment.

```bash
# 1. Get the Fabric binaries (Linux; see "Windows" section below for WSL2)
curl -sL -o /tmp/fabric.tar.gz \
  https://github.com/hyperledger/fabric/releases/download/v2.5.16/hyperledger-fabric-linux-amd64-2.5.16.tar.gz
mkdir -p /tmp/fabric-bin && tar -xzf /tmp/fabric.tar.gz -C /tmp/fabric-bin
export FABRIC_BIN_DIR=/tmp/fabric-bin/bin

# 2. Make orderer.example.com / peer0.org1.example.com resolve locally
#    (cryptogen issues TLS certs for these HOSTNAMES, not for 127.0.0.1 —
#    connecting via a bare IP fails TLS certificate verification)
echo "127.0.0.1 orderer.example.com peer0.org1.example.com" | sudo tee -a /etc/hosts

# 3. Generate crypto material and the channel genesis block
cd blockchain/network/scripts
bash generate-crypto.sh
bash generate-channel-artifacts.sh

# 4. Start the network (orderer + peer, joins paperchannel)
bash start-network.sh

# 5. Build, package, install, approve, commit the chaincode, and start
#    its CCaaS server process
bash deploy-chaincode.sh

# 6. Run the demonstration transaction sequence
bash test-transactions.sh

# 7. When done
bash stop-network.sh
```

Each script is idempotent/self-cleaning at the start (`start-network.sh`
wipes and recreates `network/data/`), so re-running from step 4 after a
failure is safe.

### Path B — Docker Compose (written this phase, NOT yet runtime-tested)

`network/docker-compose.yaml` defines the same topology using the
official `hyperledger/fabric-orderer:2.5` / `hyperledger/fabric-peer:2.5`
images. **This was not run end-to-end in the development sandbox**
(no Docker Hub access there — see above) but should work on a normal
Docker Desktop machine where Docker Hub is reachable normally. Steps 1–3
above (crypto material + channel genesis block) are shared — you still
need the native `cryptogen`/`configtxgen` binaries (or WSL2) to
generate those, even if you then run the network itself via
docker-compose. After that:

```bash
cd blockchain/network
docker compose up -d
```

**If you use this path, please verify it works and let the project
maintainer know of any adjustments needed** — it has real, correct
configuration but has not had a live confirmation pass the way Path A
has.

## Windows setup

Fabric does not publish native Windows binaries for `peer`/`orderer`/
`cryptogen`/`configtxgen`. Two realistic options on Windows:

1. **WSL2** (recommended for Path A): install WSL2 + a Linux
   distribution (Ubuntu), then run every command above inside the WSL2
   shell exactly as written. The project's `blockchain/` directory is
   accessible from WSL2 at `/mnt/c/...` if the repo lives on the
   Windows filesystem, or clone it directly inside the WSL2 filesystem
   for better performance.
2. **Docker Desktop** (Path B): Docker Desktop for Windows runs Linux
   containers via its own Linux VM, so `docker compose up` needs no
   WSL2 Fabric binaries at all — only `cryptogen`/`configtxgen` for the
   one-time crypto/genesis-block generation step, which can itself be
   run via a temporary Fabric tools container instead of native
   binaries if preferred (not scripted here — ask if this is needed).

Do not assume WSL2 is already installed — check with `wsl --version`
in PowerShell first.

## Directory layout

```
network/
├── crypto-config/crypto-config.yaml   cryptogen input (committed)
├── configtx/configtx.yaml             configtxgen input (committed)
├── orderercfg/orderer.yaml            orderer config template (committed, values overridden by env vars)
├── peercfg/core.yaml                  peer config template incl. CCaaS externalBuilder (committed)
├── organizations/                     cryptogen OUTPUT — private keys, NEVER committed (.gitignore)
├── channel-artifacts/                 configtxgen OUTPUT — regenerate, not committed
├── data/                              runtime ledger/logs — not committed
├── docker-compose.yaml                Path B (see above)
└── scripts/                           all six scripts described above
```
