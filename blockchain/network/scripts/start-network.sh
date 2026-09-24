#!/bin/bash
# start-network.sh — Phase 5A, step 3.
#
# Starts orderer.example.com and peer0.org1.example.com as NATIVE OS
# processes (no Docker) and joins both to "paperchannel".
#
# WHY NATIVE BINARIES INSTEAD OF DOCKER COMPOSE HERE:
# this project's development/CI sandbox has no route to Docker Hub
# (registry-1.docker.io returned HTTP 403 host_not_allowed when tested
# during Phase 5A — see PROJECT_STATE.md's Phase 5A section), so the
# classic "docker-compose up" model could not be exercised there. The
# Fabric project also publishes plain binary releases (peer, orderer,
# cryptogen, configtxgen, osnadmin) via GitHub Releases, completely
# independent of Docker Hub, so this script uses those instead — this
# is the same approach as Fabric's own official
# "test-network-nano-bash" sample, not a project-specific hack.
#
# On a normal Windows + Docker Desktop machine (this project's actual
# target dev environment) where Docker Hub IS reachable, prefer
# `network/docker-compose.yaml` instead — see network/README.md for
# both paths. This script still works fine under WSL2 if you prefer
# the native-binary approach there too.
set -euo pipefail

# pkill -f has been observed to hang unreliably in some sandboxed
# environments (gVisor/runsc); pgrep -f + kill is used instead here,
# since both were confirmed to behave reliably in that environment.
safe_kill_matching() {
  local pattern="$1"
  local pid
  for pid in $(pgrep -f "$pattern" 2>/dev/null || true); do
    kill -9 "$pid" 2>/dev/null || true
  done
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NETDIR="$(dirname "$SCRIPT_DIR")"
FABRIC_BIN_DIR="${FABRIC_BIN_DIR:-$NETDIR/../bin}"

ORG_ROOT="$NETDIR/organizations"
ORDERER_MSP="$ORG_ROOT/ordererOrganizations/example.com/orderers/orderer.example.com/msp"
ORDERER_TLS="$ORG_ROOT/ordererOrganizations/example.com/orderers/orderer.example.com/tls"
PEER_MSP="$ORG_ROOT/peerOrganizations/org1.example.com/peers/peer0.org1.example.com/msp"
PEER_TLS="$ORG_ROOT/peerOrganizations/org1.example.com/peers/peer0.org1.example.com/tls"
ADMIN_MSP="$ORG_ROOT/peerOrganizations/org1.example.com/users/Admin@org1.example.com/msp"
ORDERER_CA="$ORDERER_TLS/ca.crt"
PEER_CA="$PEER_TLS/ca.crt"

for f in "$ORDERER_MSP" "$PEER_MSP" "$NETDIR/channel-artifacts/paperchannel.block"; do
  [ -e "$f" ] || { echo "ERROR: $f not found. Run generate-crypto.sh and generate-channel-artifacts.sh first."; exit 1; }
done

# Requires 127.0.0.1 to resolve orderer.example.com and
# peer0.org1.example.com (cryptogen issues TLS certs for these
# HOSTNAMES, not for a bare IP address — connecting via 127.0.0.1
# directly fails TLS verification with "doesn't contain any IP SANs").
if ! getent hosts orderer.example.com >/dev/null 2>&1; then
  echo "ERROR: orderer.example.com does not resolve. Add this to /etc/hosts:"
  echo "  127.0.0.1 orderer.example.com peer0.org1.example.com"
  exit 1
fi

echo "Stopping any previous run..."
safe_kill_matching "$FABRIC_BIN_DIR/orderer"
safe_kill_matching "peer node start"
sleep 1
rm -rf "$NETDIR/data"
rm -rf /var/hyperledger/production  # stale global default path from any earlier run/version of this script
mkdir -p "$NETDIR/data/orderer" "$NETDIR/data/peer0"

echo "Starting orderer.example.com..."
export FABRIC_CFG_PATH="$NETDIR/orderercfg"
export ORDERER_GENERAL_LISTENADDRESS=0.0.0.0
export ORDERER_GENERAL_LISTENPORT=7050
export ORDERER_GENERAL_LOCALMSPID=OrdererMSP
export ORDERER_GENERAL_LOCALMSPDIR="$ORDERER_MSP"
export ORDERER_GENERAL_TLS_ENABLED=true
export ORDERER_GENERAL_TLS_PRIVATEKEY="$ORDERER_TLS/server.key"
export ORDERER_GENERAL_TLS_CERTIFICATE="$ORDERER_TLS/server.crt"
export ORDERER_GENERAL_TLS_ROOTCAS="$ORDERER_CA"
export ORDERER_GENERAL_BOOTSTRAPMETHOD=none
export ORDERER_CHANNELPARTICIPATION_ENABLED=true
export ORDERER_ADMIN_TLS_ENABLED=true
export ORDERER_ADMIN_TLS_PRIVATEKEY="$ORDERER_TLS/server.key"
export ORDERER_ADMIN_TLS_CERTIFICATE="$ORDERER_TLS/server.crt"
export ORDERER_ADMIN_TLS_ROOTCAS="$ORDERER_CA"
export ORDERER_ADMIN_TLS_CLIENTAUTHREQUIRED=true
export ORDERER_ADMIN_TLS_CLIENTROOTCAS="$ORDERER_CA"
export ORDERER_ADMIN_LISTENADDRESS=0.0.0.0:7053
export ORDERER_FILELEDGER_LOCATION="$NETDIR/data/orderer/ledger"
export ORDERER_CONSENSUS_WALDIR="$NETDIR/data/orderer/etcdraft/wal"
export ORDERER_CONSENSUS_SNAPDIR="$NETDIR/data/orderer/etcdraft/snapshot"
export ORDERER_OPERATIONS_LISTENADDRESS=0.0.0.0:9443
nohup "$FABRIC_BIN_DIR/orderer" > "$NETDIR/data/orderer.log" 2>&1 &
echo $! > "$NETDIR/data/orderer.pid"
sleep 4
ss -tln 2>/dev/null | grep -q 7050 || { echo "ERROR: orderer did not start — see $NETDIR/data/orderer.log"; exit 1; }
echo "orderer started (pid $(cat "$NETDIR/data/orderer.pid"))"

echo "Joining orderer to paperchannel..."
"$FABRIC_BIN_DIR/osnadmin" channel join --channelID paperchannel \
  --config-block "$NETDIR/channel-artifacts/paperchannel.block" \
  -o orderer.example.com:7053 --ca-file "$ORDERER_CA" \
  --client-cert "$ORDERER_TLS/server.crt" --client-key "$ORDERER_TLS/server.key"

echo "Starting peer0.org1.example.com..."
export FABRIC_CFG_PATH="$NETDIR/peercfg"
export CORE_PEER_ID=peer0.org1.example.com
export CORE_PEER_ADDRESS=peer0.org1.example.com:7051
export CORE_PEER_LISTENADDRESS=0.0.0.0:7051
export CORE_PEER_CHAINCODEADDRESS=peer0.org1.example.com:7052
export CORE_PEER_CHAINCODELISTENADDRESS=0.0.0.0:7052
export CORE_PEER_GOSSIP_BOOTSTRAP=peer0.org1.example.com:7051
export CORE_PEER_GOSSIP_EXTERNALENDPOINT=peer0.org1.example.com:7051
export CORE_PEER_LOCALMSPID=Org1MSP
export CORE_PEER_MSPCONFIGPATH="$PEER_MSP"
export CORE_PEER_TLS_ENABLED=true
export CORE_PEER_TLS_CERT_FILE="$PEER_TLS/server.crt"
export CORE_PEER_TLS_KEY_FILE="$PEER_TLS/server.key"
export CORE_PEER_TLS_ROOTCERT_FILE="$PEER_CA"
export CORE_PEER_FILESYSTEMPATH="$NETDIR/data/peer0/production"
export CORE_OPERATIONS_LISTENADDRESS=0.0.0.0:9444
export CORE_PEER_PROFILE_ENABLED=false
nohup "$FABRIC_BIN_DIR/peer" node start > "$NETDIR/data/peer0.log" 2>&1 &
echo $! > "$NETDIR/data/peer0.pid"
sleep 6
ss -tln 2>/dev/null | grep -q 7051 || { echo "ERROR: peer did not start — see $NETDIR/data/peer0.log"; exit 1; }
echo "peer0 started (pid $(cat "$NETDIR/data/peer0.pid"))"

echo "Joining peer0 to paperchannel..."
export CORE_PEER_MSPCONFIGPATH="$ADMIN_MSP"
"$FABRIC_BIN_DIR/peer" channel join -b "$NETDIR/channel-artifacts/paperchannel.block"
echo "Waiting for single-node Raft leader election..."
sleep 8

echo
echo "Network is up. paperchannel joined by orderer and peer0."
echo "Next: ./deploy-chaincode.sh"
