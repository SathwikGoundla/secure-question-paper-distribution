/**
 * index.ts — package entry point consumed by the OFFICIAL
 * `fabric-chaincode-node` CLI (bundled with fabric-shim; see
 * package.json's "start" script). The CLI's bootstrap logic
 * (fabric-shim/lib/contract-spi/bootstrap.js) requires this module and
 * looks specifically for a `contracts` array export — this is the
 * documented convention, not a custom wrapper.
 *
 * Why CCaaS (the `server` subcommand) rather than the classic
 * Docker-per-chaincode model: this project's sandbox/CI environment
 * can run the Fabric peer/orderer as native binaries but has no access
 * to Docker Hub (network egress to registry-1.docker.io is blocked —
 * confirmed and documented in PROJECT_STATE.md's Phase 5 readiness
 * section). CCaaS is an OFFICIAL Fabric deployment mode, bundled
 * directly in the Fabric binary release under builders/ccaas/, and is
 * also the standard recommended approach for Kubernetes deployments —
 * this is not a workaround invented for this project.
 *
 * On a real Windows + Docker Desktop machine, the classic
 * Docker-per-chaincode model works too; see network/scripts/ for that
 * alternative path.
 */

import { PaperLedgerContract } from "./paperContract";

export const contracts = [PaperLedgerContract];
