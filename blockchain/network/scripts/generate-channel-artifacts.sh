#!/bin/bash
# generate-channel-artifacts.sh — Phase 5A, step 2.
#
# Generates the application-channel genesis block for "paperchannel"
# from configtx/configtx.yaml, using the Fabric 2.3+ "channel-less
# system channel" model (this block is joined directly via osnadmin —
# there is no separate system-channel bootstrap step).
#
# Must be run AFTER generate-crypto.sh (configtx.yaml references the
# MSP directories that script creates).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NETDIR="$(dirname "$SCRIPT_DIR")"
FABRIC_BIN_DIR="${FABRIC_BIN_DIR:-$NETDIR/../bin}"

CONFIGTXGEN="$(command -v configtxgen || echo "$FABRIC_BIN_DIR/configtxgen")"
[ -x "$CONFIGTXGEN" ] || { echo "ERROR: configtxgen not found. Set FABRIC_BIN_DIR."; exit 1; }

if [ ! -d "$NETDIR/organizations/ordererOrganizations" ]; then
  echo "ERROR: $NETDIR/organizations not found — run generate-crypto.sh first."
  exit 1
fi

mkdir -p "$NETDIR/channel-artifacts"
export FABRIC_CFG_PATH="$NETDIR/configtx"

"$CONFIGTXGEN" -profile PaperChannel \
  -outputBlock "$NETDIR/channel-artifacts/paperchannel.block" \
  -channelID paperchannel

echo
echo "Genesis block written to: $NETDIR/channel-artifacts/paperchannel.block"
