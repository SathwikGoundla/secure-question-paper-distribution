#!/bin/bash
# deploy-chaincode.sh — Phase 5A, step 4.
#
# Packages paper-ledger as a Chaincode-as-a-Service (CCaaS) package
# (metadata.json + code.tar.gz{connection.json}), installs it on
# peer0, approves + commits the chaincode definition on paperchannel,
# then starts the actual chaincode logic as a plain Node.js process
# that the peer connects to over TCP (port 9999) — no Docker image
# build required for the chaincode itself.
#
# NOTE on `peer lifecycle chaincode package --lang`: that flag only
# recognizes source-based languages (golang/node/java) for its
# path-normalization step. CCaaS packages are hand-built instead (this
# is the officially documented convention for external chaincode
# launchers, not a workaround) — see the manual tar construction below.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NETDIR="$(dirname "$SCRIPT_DIR")"
BLOCKCHAIN_DIR="$(dirname "$NETDIR")"
CCDIR="$BLOCKCHAIN_DIR/chaincode/paper-ledger"
FABRIC_BIN_DIR="${FABRIC_BIN_DIR:-$NETDIR/../bin}"
CCAAS_PORT="${CCAAS_PORT:-9999}"

ORG_ROOT="$NETDIR/organizations"
ORDERER_TLS="$ORG_ROOT/ordererOrganizations/example.com/orderers/orderer.example.com/tls"
PEER_TLS="$ORG_ROOT/peerOrganizations/org1.example.com/peers/peer0.org1.example.com/tls"
ADMIN_MSP="$ORG_ROOT/peerOrganizations/org1.example.com/users/Admin@org1.example.com/msp"
ORDERER_CA="$ORDERER_TLS/ca.crt"
PEER_CA="$PEER_TLS/ca.crt"

export FABRIC_CFG_PATH="$NETDIR/peercfg"
export CORE_PEER_ID=peer0.org1.example.com
export CORE_PEER_ADDRESS=peer0.org1.example.com:7051
export CORE_PEER_LOCALMSPID=Org1MSP
export CORE_PEER_TLS_ENABLED=true
export CORE_PEER_TLS_CERT_FILE="$PEER_TLS/server.crt"
export CORE_PEER_TLS_KEY_FILE="$PEER_TLS/server.key"
export CORE_PEER_TLS_ROOTCERT_FILE="$PEER_CA"
export CORE_PEER_MSPCONFIGPATH="$ADMIN_MSP"

echo "1. Building the chaincode (npm install + tsc)..."
( cd "$CCDIR" && npm install && npm run build )

echo "2. Packaging chaincode as CCaaS..."
PKG_STAGE="$NETDIR/data/ccpkg"
rm -rf "$PKG_STAGE" && mkdir -p "$PKG_STAGE"
cat > "$PKG_STAGE/connection.json" <<EOF
{"address":"127.0.0.1:${CCAAS_PORT}","dial_timeout":"10s","tls_required":false}
EOF
cat > "$PKG_STAGE/metadata.json" <<EOF
{"type":"ccaas","label":"paper-ledger_1.0"}
EOF
tar -C "$PKG_STAGE" -czf "$PKG_STAGE/code.tar.gz" connection.json
tar -C "$PKG_STAGE" -czf "$NETDIR/data/paper-ledger.tar.gz" metadata.json code.tar.gz

echo "3. Installing chaincode package on peer0..."
"$FABRIC_BIN_DIR/peer" lifecycle chaincode install "$NETDIR/data/paper-ledger.tar.gz"
PACKAGE_ID=$("$FABRIC_BIN_DIR/peer" lifecycle chaincode queryinstalled | grep -oE "paper-ledger_1.0:[a-f0-9]+" | head -1)
[ -n "$PACKAGE_ID" ] || { echo "ERROR: could not determine package ID"; exit 1; }
echo "PACKAGE_ID=$PACKAGE_ID"
echo "$PACKAGE_ID" > "$NETDIR/data/package-id.txt"

echo "4. Approving chaincode definition for Org1MSP (retrying briefly if the Raft leader isn't ready yet)..."
APPROVE_OK=0
for attempt in 1 2 3 4 5; do
  APPROVE_OUT=$("$FABRIC_BIN_DIR/peer" lifecycle chaincode approveformyorg \
    --channelID paperchannel --name paper-ledger --version 1.0 \
    --package-id "$PACKAGE_ID" --sequence 1 \
    --orderer orderer.example.com:7050 --tls --cafile "$ORDERER_CA" 2>&1)
  echo "attempt $attempt: $APPROVE_OUT"
  if echo "$APPROVE_OUT" | grep -qi "committed"; then APPROVE_OK=1; break; fi
  sleep 4
done
[ "$APPROVE_OK" = "1" ] || echo "WARNING: approveformyorg did not confirm success after retries"

echo "5. Checking commit readiness..."
"$FABRIC_BIN_DIR/peer" lifecycle chaincode checkcommitreadiness \
  --channelID paperchannel --name paper-ledger --version 1.0 --sequence 1 \
  --orderer orderer.example.com:7050 --tls --cafile "$ORDERER_CA" --output json

echo "6. Committing chaincode definition..."
"$FABRIC_BIN_DIR/peer" lifecycle chaincode commit \
  --channelID paperchannel --name paper-ledger --version 1.0 --sequence 1 \
  --orderer orderer.example.com:7050 --tls --cafile "$ORDERER_CA" \
  --peerAddresses peer0.org1.example.com:7051 --tlsRootCertFiles "$PEER_CA"

"$FABRIC_BIN_DIR/peer" lifecycle chaincode querycommitted --channelID paperchannel --name paper-ledger

echo "7. Starting the chaincode server (real Node.js process, CCaaS)..."
( cd "$CCDIR" && \
  CHAINCODE_ID="$PACKAGE_ID" CHAINCODE_SERVER_ADDRESS="0.0.0.0:${CCAAS_PORT}" \
  nohup npm start > "$NETDIR/data/chaincode_server.log" 2>&1 & echo $! > "$NETDIR/data/chaincode.pid" )
sleep 5
ss -tln 2>/dev/null | grep -q "$CCAAS_PORT" || { echo "ERROR: chaincode server did not start — see $NETDIR/data/chaincode_server.log"; exit 1; }

echo
echo "Chaincode deployed and running. Next: ./test-transactions.sh"
