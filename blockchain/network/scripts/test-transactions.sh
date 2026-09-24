#!/bin/bash
# test-transactions.sh — Phase 5A, step 5.
#
# Runs exactly the transaction sequence used to verify Phase 5A in
# PROJECT_STATE.md: RegisterPaper, duplicate rejection, GetPaper,
# VerifyPaperHash (match + mismatch), RecordAuditEvent, GetPaper on a
# missing paper_id. Every step here produced a real, logged result
# during Phase 5A development — re-run it any time to re-verify.
set -uo pipefail  # not -e: some steps are EXPECTED to fail (that's the test)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NETDIR="$(dirname "$SCRIPT_DIR")"
FABRIC_BIN_DIR="${FABRIC_BIN_DIR:-$NETDIR/../bin}"

ORG_ROOT="$NETDIR/organizations"
ORDERER_TLS="$ORG_ROOT/ordererOrganizations/example.com/orderers/orderer.example.com/tls"
PEER_TLS="$ORG_ROOT/peerOrganizations/org1.example.com/peers/peer0.org1.example.com/tls"
ADMIN_MSP="$ORG_ROOT/peerOrganizations/org1.example.com/users/Admin@org1.example.com/msp"
ORDERER_CA="$ORDERER_TLS/ca.crt"
PEER_CA="$PEER_TLS/ca.crt"

export FABRIC_CFG_PATH="$NETDIR/peercfg"
export CORE_PEER_ADDRESS=peer0.org1.example.com:7051
export CORE_PEER_LOCALMSPID=Org1MSP
export CORE_PEER_TLS_ENABLED=true
export CORE_PEER_TLS_CERT_FILE="$PEER_TLS/server.crt"
export CORE_PEER_TLS_KEY_FILE="$PEER_TLS/server.key"
export CORE_PEER_TLS_ROOTCERT_FILE="$PEER_CA"
export CORE_PEER_MSPCONFIGPATH="$ADMIN_MSP"

HASH_A=$(printf 'a%.0s' {1..64})
HASH_B=$(printf 'b%.0s' {1..64})
PAPER_ID="paper-demo-$(date +%s)"

invoke() {
  "$FABRIC_BIN_DIR/peer" chaincode invoke \
    -o orderer.example.com:7050 --tls --cafile "$ORDERER_CA" \
    -C paperchannel -n paper-ledger \
    --peerAddresses peer0.org1.example.com:7051 --tlsRootCertFiles "$PEER_CA" \
    -c "$1"
}
query() {
  "$FABRIC_BIN_DIR/peer" chaincode query -C paperchannel -n paper-ledger -c "$1"
}

echo "### 1. RegisterPaper ($PAPER_ID)"
invoke "{\"function\":\"RegisterPaper\",\"Args\":[\"$PAPER_ID\",\"$HASH_A\",\"2026-01-01T00:00:00Z\",\"admin-demo\",\"Demo Subject\",\"AES-256-GCM\"]}"
# Wait past the orderer's BatchTimeout (configtx.yaml: 2s) so this
# transaction is actually committed to a block before the dependent
# steps below query/depend on its effect. Without this, back-to-back
# calls race ahead of block-cutting: a query issued before commit sees
# "not found" even though the invoke itself endorsed successfully, and
# a second RegisterPaper submitted before the first commits will ALSO
# endorse successfully (it simulates against the last-COMMITTED state,
# which doesn't include the still-pending first transaction yet) —
# Fabric's own MVCC validation would still catch that specific race at
# commit time, but this script's purpose is to demonstrate the
# CHAINCODE's explicit duplicate-check path, so it waits instead.
sleep 3

echo; echo "### 2. Duplicate RegisterPaper (MUST fail with DUPLICATE_PAPER)"
invoke "{\"function\":\"RegisterPaper\",\"Args\":[\"$PAPER_ID\",\"$HASH_A\",\"2026-01-01T00:00:00Z\",\"admin-demo\",\"Demo Subject\",\"AES-256-GCM\"]}"

echo; echo "### 3. GetPaper"
query "{\"function\":\"GetPaper\",\"Args\":[\"$PAPER_ID\"]}"

echo; echo "### 4. VerifyPaperHash — correct hash (expect match:true)"
query "{\"function\":\"VerifyPaperHash\",\"Args\":[\"$PAPER_ID\",\"$HASH_A\"]}"

echo; echo "### 5. VerifyPaperHash — incorrect hash (expect match:false)"
query "{\"function\":\"VerifyPaperHash\",\"Args\":[\"$PAPER_ID\",\"$HASH_B\"]}"

echo; echo "### 6. RecordAuditEvent"
invoke "{\"function\":\"RecordAuditEvent\",\"Args\":[\"evt-$(date +%s)\",\"PAPER_REGISTRATION_COMPLETED\",\"admin-demo\",\"$PAPER_ID\",\"SUCCESS\",\"2026-01-01T00:00:01Z\"]}"
sleep 3

echo; echo "### 7. GetPaper on a NON-existent paper_id (MUST fail with PAPER_NOT_FOUND)"
query "{\"function\":\"GetPaper\",\"Args\":[\"does-not-exist\"]}"

echo
echo "Done. Steps 2 and 7 are EXPECTED to print an Error line — that is the correct, tested behaviour."
