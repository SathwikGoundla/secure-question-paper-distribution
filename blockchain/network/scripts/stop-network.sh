#!/bin/bash
# stop-network.sh — Phase 5A, step 6.
#
# Stops the orderer, peer, and chaincode server processes started by
# start-network.sh / deploy-chaincode.sh. Ledger data under
# network/data/ is left in place (delete it manually, or via
# start-network.sh's own cleanup, to fully reset the network).
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NETDIR="$(dirname "$SCRIPT_DIR")"

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

for pidfile in orderer.pid peer0.pid chaincode.pid; do
  f="$NETDIR/data/$pidfile"
  if [ -f "$f" ]; then
    pid=$(cat "$f")
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" && echo "Stopped $pidfile (pid $pid)"
    fi
    rm -f "$f"
  fi
done

# Fallback in case a pidfile was missing/stale
safe_kill_matching "orderer$"
safe_kill_matching "peer node start"
safe_kill_matching "fabric-chaincode-node"

echo "Network stopped."
